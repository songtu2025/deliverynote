import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import shutil
from threading import Lock
from typing import Annotated, Callable
from uuid import uuid4

import pandas as pd
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..config import (
    resolve_supplier,
)
from ..excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
    read_supplier_workbook,
    validate_self_operated_template_workbook,
    validate_template_workbook,
)
from ..exception_reasons import exception_reason_code
from ..input_inspection import (
    inspect_input_version_with_preview,
    position_change_warnings,
    position_diff,
    preview_input_version_page,
    validate_position_frame,
)
from ..migrations.runner import migrate_schema as run_schema_migrations
from ..pipeline import (
    IMPORT_COLUMNS,
    POSITION_VALUE_COLUMNS,
    enrich_pending_import_rows,
)
from .auth_routes import register_auth_routes
from .dependencies import build_request_dependencies
from .health_routes import register_health_routes
from .auth import hash_password
from .batch_export_routes import register_batch_export_routes
from .batch_read_routes import register_batch_read_routes
from .batch_queries import VERSION_FIELDS
from .batch_views import (
    batch_json, batch_list_json, file_json,
    merged_export_path, merged_export_ready,
)
from .database import Database
from .errors import (
    CodedHTTPException,
    DRAFT_IMPORT_PREVIEW_EXPIRED_CODE,
    INPUT_VERSION_NAME_EXISTS_CODE,
    commit_once,
    register_exception_handlers,
    rollback_draft_conflict,
    rollback_integrity_conflict,
)
from .position_draft_read_routes import register_position_draft_read_routes
from .position_import_candidates import PositionImportCandidates
from .overreceipt_routes import register_overreceipt_routes
from .self_operated_rule_routes import register_self_operated_rule_routes
from .input_version_routes import register_input_version_routes
from .input_versions import INPUT_KINDS, SELF_OPERATED_INPUT_KINDS
from .input_versions import bootstrap_builtin_templates
from .uploads import _safe_filename, _save_upload, _unlink_after_commit
from .gerpgo_routes import register_gerpgo_routes
from .exception_read_routes import register_exception_read_routes
from .exception_write_routes import register_exception_write_routes
from .input_version_read_routes import register_input_version_read_routes
from .models import (
    AuditLog,
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputDraft,
    InputVersion,
    Job,
    OverreceiptRuleVersion,
    PositionDraftRow,
    SelfOperatedBatch,
    SelfOperatedOverreceiptRuleVersion,
    SelfOperatedSiteResolution,
    SplitRecord,
    User,
)
from .position_drafts import (
    DraftConflictError,
    DuplicateInputVersionNameError,
    create_or_resume_draft,
    delete_draft_rows,
    discard_draft,
    list_draft_rows,
    position_frame,
    mutate_draft_row,
    publish_draft,
    replace_draft_from_frame,
    require_revision,
)
from .position_draft_read import (
    draft_json, summarize_issues, position_row_json,
)
from .sync_routes import register_sync_routes
from .schemas import (
    BatchPayload,
    BatchDeletePayload,
    FileOrderPayload,
    DraftMutationPayload,
    PositionRowPayload,
    BulkDeletePayload,
    ImportApplyPayload,
    PublishDraftPayload,
)
from .caches import (
    InputInspectionCache,
    PositionFrameCache,
    DraftAnalysisCache,
)
from .serializers import (
    utc_isoformat,
    version_json,
    job_json,
)


BATCH_STATUSES = {
    "draft",
    "preflight_ready",
    "queued",
    "running",
    "succeeded",
    "failed",
    "expired",
}
INPUT_INSPECTION_CACHE_SIZE = 32
INPUT_INSPECTION_PAGES_PER_VERSION = 4
DRAFT_ANALYSIS_CACHE_SIZE = 32
_TRUE_BOOLEAN_VALUES = {"1", "true", "yes", "on"}
_FALSE_BOOLEAN_VALUES = {"0", "false", "no", "off"}


def _boolean_environment(name: str, default: bool) -> bool:
    """读取布尔环境变量，并拒绝无法识别的配置。"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in _TRUE_BOOLEAN_VALUES:
        return True
    if value in _FALSE_BOOLEAN_VALUES:
        return False
    raise ValueError(f"{name} 必须是 true 或 false")


def _split_records_by_exception(
    session: Session,
    exceptions: list[ExceptionRecord],
) -> dict[int, list[SplitRecord]]:
    exception_ids = [exception.id for exception in exceptions]
    if not exception_ids:
        return {}
    records = session.scalars(
        select(SplitRecord)
        .where(SplitRecord.exception_id.in_(exception_ids))
        .order_by(SplitRecord.exception_id, SplitRecord.id)
    ).all()
    grouped: dict[int, list[SplitRecord]] = {}
    for record in records:
        grouped.setdefault(record.exception_id, []).append(record)
    return grouped


def _batch_input_signature(
    batch: Batch,
    sources: list[BatchFile],
    self_operated: SelfOperatedBatch | None,
) -> tuple:
    return (
        tuple(getattr(batch, VERSION_FIELDS[kind]) for kind in INPUT_KINDS),
        tuple(
            (source.id, source.storage_path, source.original_name, source.file_order)
            for source in sources
        ),
        (
            self_operated.template_version_id,
            self_operated.rule_version_id,
            self_operated.inbound_storage_path,
        )
        if self_operated is not None
        else None,
    )




def _inspect_position_import(
    path: Path,
    current_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list, dict]:
    """在线程池中读取并检查库位导入文件。"""
    candidate_frame = read_position_workbook(path)
    issues = [
        *validate_position_frame(candidate_frame),
        *position_change_warnings(current_frame, candidate_frame),
    ]
    return candidate_frame, issues, position_diff(current_frame, candidate_frame)


def _exception_position_values(
    exceptions: list[ExceptionRecord],
    batch: Batch,
    session: Session,
    position_frame_cache: PositionFrameCache,
) -> dict[int, dict[str, str | int | float]]:
    if not exceptions:
        return {}
    version = session.get(InputVersion, batch.position_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="批次锁定的库位资料不存在")
    pending_rows = pd.DataFrame(
        [
            {
                "*目的仓": exception.destination,
                "*供应商编码": "",
                "*SKU": exception.sku,
                "*本次交货量": exception.manual_quantity,
                "*站点": exception.full_site,
                "单据备注": "",
                "交货备注": exception.reason,
            }
            for exception in exceptions
        ],
        index=[exception.id for exception in exceptions],
        columns=IMPORT_COLUMNS,
    )
    try:
        position_rows = position_frame_cache.get(
            version.id,
            Path(version.storage_path),
        )
        enriched = enrich_pending_import_rows(
            pending_rows,
            position_rows,
        )
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=409,
            detail=f"批次锁定的库位资料无法读取：{error}",
        ) from error

    result: dict[int, dict[str, str | int | float]] = {}
    for exception_id, row in enriched.iterrows():
        values = {}
        for column, key in zip(
            POSITION_VALUE_COLUMNS,
            ("scale_position", "stocking_position"),
            strict=True,
        ):
            value = row[column]
            if pd.isna(value):
                value = ""
            elif hasattr(value, "item"):
                value = value.item()
            values[key] = value
        result[int(exception_id)] = values
    return result


def _exception_json(
    exception: ExceptionRecord,
    parts: list[SplitRecord],
    position_values: dict[str, str | int | float] | None = None,
    *,
    self_operated: bool = False,
) -> dict:
    position_values = position_values or {}
    reason_code = exception.reason_code or exception_reason_code(exception.reason)
    if self_operated:
        allowed_actions = (
            ["resolve_site"] if reason_code == "ambiguous_product_site" else []
        )
    else:
        allowed_actions = ["split"]
    return {
        "id": exception.id,
        "batch_file_id": exception.batch_file_id,
        "sku": exception.sku,
        "original_site": exception.original_site,
        "full_site": exception.full_site,
        "destination": exception.destination,
        "delivery_quantity": exception.delivery_quantity,
        "allocated_quantity": exception.allocated_quantity,
        "purchase_allocated_quantity": exception.purchase_allocated_quantity,
        "overreceipt_allocated_quantity": exception.overreceipt_allocated_quantity,
        "overreceipt_remaining_quantity": exception.overreceipt_remaining_quantity,
        "manual_quantity": exception.manual_quantity,
        "reason": exception.reason,
        "reason_code": reason_code,
        "allowed_actions": allowed_actions,
        "status": exception.status,
        "scale_position": position_values.get("scale_position", ""),
        "stocking_position": position_values.get("stocking_position", ""),
        "parts": [
            {
                "id": part.id,
                "quantity": part.quantity,
                "destination": part.destination,
                "site": part.site,
                "supplier_code": part.supplier_code,
                "sku": part.sku,
                "delivery_note": part.delivery_note,
                "resolved": part.resolved,
            }
            for part in parts
        ],
    }


def _audit(
    session: Session,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | str,
    details: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details or {},
        )
    )


def create_app(
    database_url: str | None = None,
    storage_root: Path | str | None = None,
    bootstrap_admin: tuple[str, str] | None = None,
    max_upload_bytes: int | None = None,
    import_candidate_ttl_seconds: int | None = None,
    position_frame_cache_size: int | None = None,
    auto_migrate_schema: bool | None = None,
    max_concurrent_upload_parses: int | None = None,
    max_batch_upload_files: int | None = None,
    session_cookie_secure: bool | None = None,
) -> FastAPI:
    resolved_database_url = database_url or os.getenv(
        "DATABASE_URL", "sqlite+pysqlite:///delivery_note.db"
    )
    if auto_migrate_schema is None:
        auto_migrate_schema = os.getenv("AUTO_MIGRATE_SCHEMA", "true").lower() not in {
            "0",
            "false",
            "no",
        }
    if auto_migrate_schema:
        run_schema_migrations(resolved_database_url)
    database = Database(resolved_database_url)
    storage = Path(storage_root or os.getenv("STORAGE_ROOT", "storage")).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    configured_max_upload_bytes = (
        max_upload_bytes
        if max_upload_bytes is not None
        else int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    )
    if configured_max_upload_bytes <= 0:
        raise ValueError("MAX_UPLOAD_BYTES 必须大于 0")
    configured_max_concurrent_upload_parses = (
        max_concurrent_upload_parses
        if max_concurrent_upload_parses is not None
        else int(os.getenv("MAX_CONCURRENT_UPLOAD_PARSES", "2"))
    )
    if configured_max_concurrent_upload_parses <= 0:
        raise ValueError("MAX_CONCURRENT_UPLOAD_PARSES 必须大于 0")
    configured_max_batch_upload_files = (
        max_batch_upload_files
        if max_batch_upload_files is not None
        else int(os.getenv("MAX_BATCH_UPLOAD_FILES", "50"))
    )
    if configured_max_batch_upload_files <= 0:
        raise ValueError("MAX_BATCH_UPLOAD_FILES 必须大于 0")
    configured_import_candidate_ttl = (
        import_candidate_ttl_seconds
        if import_candidate_ttl_seconds is not None
        else int(os.getenv("IMPORT_CANDIDATE_TTL_SECONDS", "900"))
    )
    if configured_import_candidate_ttl <= 0:
        raise ValueError("IMPORT_CANDIDATE_TTL_SECONDS 必须大于 0")
    configured_position_frame_cache_size = (
        position_frame_cache_size
        if position_frame_cache_size is not None
        else int(os.getenv("POSITION_FRAME_CACHE_SIZE", "8"))
    )
    if configured_position_frame_cache_size <= 0:
        raise ValueError("POSITION_FRAME_CACHE_SIZE 必须大于 0")
    configured_session_cookie_secure = (
        session_cookie_secure
        if session_cookie_secure is not None
        else _boolean_environment("SESSION_COOKIE_SECURE", False)
    )
    import_candidate_root = storage / "temporary" / "position-imports"
    import_candidates_state = PositionImportCandidates(import_candidate_root)
    import_candidates_state.remove_expired(configured_import_candidate_ttl)
    batch_file_upload_lock = asyncio.Lock()
    upload_parse_semaphore = asyncio.Semaphore(
        configured_max_concurrent_upload_parses
    )
    overreceipt_rule_lock = Lock()
    overreceipt_warehouse_cache: dict[int, tuple[str, ...]] = {}
    position_frame_cache = PositionFrameCache(configured_position_frame_cache_size)
    draft_analysis_cache = DraftAnalysisCache(DRAFT_ANALYSIS_CACHE_SIZE)
    input_inspection_cache = InputInspectionCache(
        INPUT_INSPECTION_CACHE_SIZE,
        INPUT_INSPECTION_PAGES_PER_VERSION,
    )

    admin_credentials = bootstrap_admin
    if admin_credentials is None:
        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        if username and password:
            admin_credentials = (username, password)
    if admin_credentials:
        with database.session() as session:
            existing = session.scalar(
                select(User).where(User.username == admin_credentials[0])
            )
            if existing is None:
                session.add(
                    User(
                        username=admin_credentials[0],
                        password_hash=hash_password(admin_credentials[1]),
                        role="admin",
                    )
                )
                session.commit()

    bootstrap_builtin_templates(database)

    app = FastAPI(title="供应链交货处理系统", version="1.0.0")
    register_exception_handlers(app)


    app.state.database = database
    app.state.storage_root = storage
    app.state.max_upload_bytes = configured_max_upload_bytes
    app.state.max_concurrent_upload_parses = configured_max_concurrent_upload_parses
    app.state.max_batch_upload_files = configured_max_batch_upload_files
    app.state.import_candidate_ttl_seconds = configured_import_candidate_ttl
    app.state.position_frame_cache_size = configured_position_frame_cache_size
    app.state.position_frame_cache = position_frame_cache
    app.state.draft_analysis_cache = draft_analysis_cache
    app.state.session_cookie_secure = configured_session_cookie_secure
    app.state.position_import_candidates = import_candidates_state.entries
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080"
            ).split(",")
            if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    dependencies = build_request_dependencies(
        database, position_frame_cache, configured_session_cookie_secure
    )
    get_session = dependencies.get_session
    current_user = dependencies.current_user
    admin_user = dependencies.admin_user
    get_batch_or_404 = dependencies.get_batch_or_404
    get_draft_or_404 = dependencies.get_draft_or_404
    register_health_routes(app, database)
    register_auth_routes(app, dependencies, configured_session_cookie_secure, _audit)

    async def parse_uploaded_workbook(function: Callable, *args):
        """限制进程内并发，并在线程池执行工作簿解析。"""
        async with upload_parse_semaphore:
            return await run_in_threadpool(function, *args)

    def inspect_version(
        version: InputVersion,
        offset: int,
        limit: int,
    ) -> dict:
        return input_inspection_cache.get(
            version.id,
            offset,
            limit,
            lambda: inspect_input_version_with_preview(
                version.kind,
                Path(version.storage_path),
                offset,
                limit,
            ),
            lambda summary: preview_input_version_page(
                version.kind,
                Path(version.storage_path),
                offset,
                limit,
                summary,
            ),
        )


    register_input_version_routes(
        app, dependencies, storage, parse_uploaded_workbook, _audit
    )

    register_gerpgo_routes(app, dependencies, storage, _audit)
    register_overreceipt_routes(
        app, dependencies, overreceipt_rule_lock, _audit, overreceipt_warehouse_cache
    )
    register_self_operated_rule_routes(app, dependencies, overreceipt_rule_lock, _audit)

    register_sync_routes(
        app=app,
        storage=storage,
        get_session=get_session,
        current_user=current_user,
        audit=_audit,
        version_json=version_json,
        utc_isoformat=utc_isoformat,
    )
    register_batch_read_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        batch_json=batch_json,
        batch_list_json=batch_list_json,
        get_batch_or_404=get_batch_or_404,
    )
    register_exception_read_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        get_batch_or_404=get_batch_or_404,
        exception_position_values=_exception_position_values,
        position_frame_cache=position_frame_cache,
        split_records_by_exception=_split_records_by_exception,
        exception_json=_exception_json,
    )


    register_input_version_read_routes(
        app=app,
        get_session=get_session,
        admin_user=admin_user,
        inspect_version=inspect_version,
    )


    register_position_draft_read_routes(
        app, dependencies, draft_analysis_cache, storage
    )

    @app.post(
        "/api/input-drafts/position",
        status_code=status.HTTP_201_CREATED,
    )
    def create_position_draft(
        response: Response,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        list(
            session.scalars(
                select(InputVersion.id)
                .where(InputVersion.kind == "position")
                .order_by(InputVersion.id)
                .with_for_update()
            )
        )
        existing = session.scalar(
            select(InputDraft)
            .where(
                InputDraft.kind == "position",
                InputDraft.status == "editing",
            )
            .with_for_update()
        )
        if existing is not None:
            version = session.get(
                InputVersion,
                existing.base_version_id,
                populate_existing=True,
            )
        else:
            active_version_id = session.scalar(
                select(InputVersion.id).where(
                    InputVersion.kind == "position",
                    InputVersion.active.is_(True),
                )
            )
            version = (
                session.get(
                    InputVersion,
                    active_version_id,
                    populate_existing=True,
                )
                if active_version_id is not None
                else None
            )
        if version is None:
            raise HTTPException(status_code=404, detail="当前启用的库位版本不存在")
        try:
            draft = create_or_resume_draft(session, version, admin.id)
            if existing is not None:
                _audit(
                    session,
                    admin.id,
                    "resume_input_draft",
                    "input_draft",
                    draft.id,
                    {"base_version_id": draft.base_version_id},
                )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
        return draft_json(session, draft, draft_analysis_cache)



    @app.post(
        "/api/input-drafts/{draft_id}/rows",
        status_code=status.HTTP_201_CREATED,
    )
    def create_position_draft_row(
        draft_id: int,
        payload: PositionRowPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        try:
            row = mutate_draft_row(
                session,
                draft,
                payload.revision,
                admin.id,
                payload.model_dump(exclude={"revision"}),
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        session.refresh(row)
        import_candidates_state.remove_draft(draft.id)
        return {"row": position_row_json(row), "revision": draft.revision}

    @app.put("/api/input-drafts/{draft_id}/rows/{row_id}")
    def update_position_draft_row(
        draft_id: int,
        row_id: int,
        payload: PositionRowPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        existing_row = session.get(PositionDraftRow, row_id)
        if existing_row is None or existing_row.draft_id != draft.id:
            raise HTTPException(status_code=404, detail="草稿行不存在")
        try:
            row = mutate_draft_row(
                session,
                draft,
                payload.revision,
                admin.id,
                payload.model_dump(exclude={"revision"}),
                row_id=row_id,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        session.refresh(row)
        import_candidates_state.remove_draft(draft.id)
        return {"row": position_row_json(row), "revision": draft.revision}

    @app.delete("/api/input-drafts/{draft_id}/rows/{row_id}")
    def delete_position_draft_row(
        draft_id: int,
        row_id: int,
        payload: DraftMutationPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        existing_row = session.get(PositionDraftRow, row_id)
        if existing_row is None or existing_row.draft_id != draft.id:
            raise HTTPException(status_code=404, detail="草稿行不存在")
        try:
            mutate_draft_row(
                session,
                draft,
                payload.revision,
                admin.id,
                {},
                row_id=row_id,
                delete=True,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return {"row_id": row_id, "revision": draft.revision}

    @app.post("/api/input-drafts/{draft_id}/rows/bulk-delete")
    def bulk_delete_position_draft_rows(
        draft_id: int,
        payload: BulkDeletePayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        if len(payload.row_ids) != len(set(payload.row_ids)):
            raise HTTPException(status_code=400, detail="批量删除行不可重复")
        rows = session.scalars(
            select(PositionDraftRow).where(
                PositionDraftRow.draft_id == draft.id,
                PositionDraftRow.id.in_(payload.row_ids),
            )
        ).all()
        if len(rows) != len(payload.row_ids):
            raise HTTPException(status_code=404, detail="草稿行不存在")
        try:
            delete_draft_rows(
                session,
                draft,
                payload.revision,
                admin.id,
                rows,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return {"deleted_ids": payload.row_ids, "revision": draft.revision}

    @app.post("/api/input-drafts/{draft_id}/import-preview")
    async def preview_position_draft_import(
        draft_id: int,
        revision: Annotated[int, Form(ge=1)],
        file: UploadFile = File(...),
        _admin: User = Depends(admin_user),
        session: Session = Depends(get_session),
    ):
        await run_in_threadpool(
            import_candidates_state.remove_expired,
            app.state.import_candidate_ttl_seconds,
        )
        draft = get_draft_or_404(draft_id, session)
        try:
            require_revision(draft, revision)
        except DraftConflictError as error:
            await file.close()
            rollback_draft_conflict(session, error)
        original_name = _safe_filename(file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            await file.close()
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        token = uuid4().hex
        suffix = Path(original_name).suffix.lower()
        destination = import_candidate_root / f"{draft.id}_{revision}_{token}{suffix}"
        await _save_upload(file, destination, app.state.max_upload_bytes)
        try:
            current_frame = position_frame(list_draft_rows(session, draft.id))
            candidate_frame, issues, diff = await parse_uploaded_workbook(
                _inspect_position_import,
                destination,
                current_frame,
            )
        except Exception as error:
            await run_in_threadpool(destination.unlink, missing_ok=True)
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"导入文件校验失败：{error}",
            ) from error
        await run_in_threadpool(import_candidates_state.remove_draft, draft.id)
        await run_in_threadpool(
            import_candidates_state.register,
            token,
            {
                "draft_id": draft.id,
                "revision": revision,
                "path": str(destination),
                "created_by": _admin.id,
                "expires_at": datetime.utcnow()
                + timedelta(seconds=app.state.import_candidate_ttl_seconds),
            },
        )
        return {
            "token": token,
            "draft_id": draft.id,
            "revision": revision,
            "row_count": len(candidate_frame),
            "diff": diff,
            **summarize_issues(issues),
        }

    @app.post("/api/input-drafts/{draft_id}/import-apply")
    def apply_position_draft_import(
        draft_id: int,
        payload: ImportApplyPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        import_candidates_state.remove_expired(app.state.import_candidate_ttl_seconds)
        draft = get_draft_or_404(draft_id, session)
        candidate = import_candidates_state.peek(payload.token)
        if candidate is not None and candidate["created_by"] != admin.id:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=403,
                detail="导入预览属于其他管理员",
            )
        if (
            candidate is None
            or candidate["draft_id"] != draft.id
            or candidate["revision"] != payload.revision
        ):
            import_candidates_state.remove(payload.token)
            if session.in_transaction():
                session.rollback()
            raise CodedHTTPException(
                code=DRAFT_IMPORT_PREVIEW_EXPIRED_CODE,
                detail="导入预览已失效，请重新预览",
            )
        try:
            require_revision(draft, payload.revision)
        except DraftConflictError as error:
            import_candidates_state.remove(payload.token)
            rollback_draft_conflict(session, error)
        candidate = import_candidates_state.take(payload.token)
        if candidate is None:
            if session.in_transaction():
                session.rollback()
            raise CodedHTTPException(
                code=DRAFT_IMPORT_PREVIEW_EXPIRED_CODE,
                detail="导入预览已失效，请重新预览",
            )
        candidate_path = Path(candidate["path"])
        try:
            candidate_frame = read_position_workbook(candidate_path)
            diff = replace_draft_from_frame(
                session,
                draft,
                payload.revision,
                admin.id,
                candidate_frame,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except Exception as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"导入草稿失败：{error}",
            ) from error
        finally:
            candidate_path.unlink(missing_ok=True)
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return {"diff": diff, "revision": draft.revision}



    @app.post(
        "/api/input-drafts/{draft_id}/publish",
        status_code=status.HTTP_201_CREATED,
    )
    def publish_position_draft(
        draft_id: int,
        payload: PublishDraftPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        original_name = _safe_filename(f"{payload.name}.xlsx")
        destination = storage / "master" / "position" / f"{uuid4().hex}_{original_name}"
        try:
            version = publish_draft(
                session,
                draft,
                payload.revision,
                admin.id,
                name=payload.name,
                storage_path=destination,
                confirm_warnings=payload.confirm_warnings,
                original_name=original_name,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except DuplicateInputVersionNameError as error:
            if session.in_transaction():
                session.rollback()
            raise CodedHTTPException(
                code=INPUT_VERSION_NAME_EXISTS_CODE, detail=str(error)
            ) from error
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"草稿发布失败：{error}",
            ) from error
        session.refresh(version)
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return {
            **version_json(version),
            "draft_revision": draft.revision,
            "draft_status": draft.status,
        }

    @app.post("/api/input-drafts/{draft_id}/discard")
    def discard_position_draft(
        draft_id: int,
        payload: DraftMutationPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        try:
            discard_draft(
                session,
                draft,
                payload.revision,
                admin.id,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return draft_json(session, draft, draft_analysis_cache)

    @app.post("/api/batches", status_code=status.HTTP_201_CREATED)
    def create_batch(
        payload: BatchPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        active_versions = {
            version.kind: version
            for version in session.scalars(
                select(InputVersion).where(InputVersion.active.is_(True))
            )
        }
        missing = [kind for kind in INPUT_KINDS if kind not in active_versions]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"缺少启用的输入版本：{', '.join(missing)}",
            )
        active_overreceipt_rule = session.scalar(
            select(OverreceiptRuleVersion).where(
                OverreceiptRuleVersion.active.is_(True)
            )
        )
        batch = Batch(
            name=payload.name,
            created_by=user.id,
            **{VERSION_FIELDS[kind]: active_versions[kind].id for kind in INPUT_KINDS},
        )
        session.add(batch)
        session.flush()
        if active_overreceipt_rule is not None:
            session.add(
                BatchOverreceiptRule(
                    batch_id=batch.id,
                    rule_version_id=active_overreceipt_rule.id,
                )
            )
        _audit(
            session,
            user.id,
            "create_batch",
            "batch",
            batch.id,
            {
                "overreceipt_rule_version_id": (
                    active_overreceipt_rule.id
                    if active_overreceipt_rule is not None
                    else None
                )
            },
        )
        session.commit()
        return batch_json(batch, session)

    @app.post(
        "/api/batches/with-files",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_batch_with_files(
        name: Annotated[str, Form()],
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        files: list[UploadFile] = File(...),
    ):
        batch_name = name.strip()
        if not batch_name:
            raise HTTPException(status_code=400, detail="批次名称不能为空")
        if len(batch_name) > 200:
            raise HTTPException(status_code=400, detail="批次名称不能超过 200 个字符")
        if not files:
            raise HTTPException(status_code=400, detail="请至少上传一份交货文件")
        if len(files) > app.state.max_batch_upload_files:
            for upload in files:
                await upload.close()
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"单批次最多上传 {app.state.max_batch_upload_files} 份交货文件",
            )

        active_versions = {
            version.kind: version
            for version in session.scalars(
                select(InputVersion).where(InputVersion.active.is_(True))
            )
        }
        missing = [kind for kind in INPUT_KINDS if kind not in active_versions]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"缺少启用的输入版本：{', '.join(missing)}",
            )
        original_names = [_safe_filename(file.filename or "") for file in files]
        if any(
            Path(original_name).suffix.lower() not in {".xls", ".xlsx"}
            for original_name in original_names
        ):
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        if len(original_names) != len(set(original_names)):
            raise HTTPException(status_code=400, detail="同一批次不可上传同名文件")

        temporary_root = storage / "temporary" / "delivery-batches"
        token = uuid4().hex
        temporary_paths = [
            temporary_root / f"{token}_{index}_{original_name}"
            for index, original_name in enumerate(original_names, start=1)
        ]
        created_paths: list[Path] = []
        active_overreceipt_rule = session.scalar(
            select(OverreceiptRuleVersion).where(
                OverreceiptRuleVersion.active.is_(True)
            )
        )
        try:
            for file, temporary_path in zip(files, temporary_paths):
                await _save_upload(
                    file,
                    temporary_path,
                    app.state.max_upload_bytes,
                )
                await parse_uploaded_workbook(
                    read_delivery_workbook,
                    temporary_path,
                )

            batch = Batch(
                name=batch_name,
                created_by=user.id,
                **{
                    VERSION_FIELDS[kind]: active_versions[kind].id
                    for kind in INPUT_KINDS
                },
            )
            session.add(batch)
            session.flush()
            input_root = storage / "batches" / str(batch.id) / "inputs"
            await run_in_threadpool(input_root.mkdir, parents=True, exist_ok=True)
            for file_order, (original_name, temporary_path) in enumerate(
                zip(original_names, temporary_paths),
                start=1,
            ):
                destination = input_root / f"{uuid4().hex}_{original_name}"
                await run_in_threadpool(os.replace, temporary_path, destination)
                created_paths.append(destination)
                session.add(
                    BatchFile(
                        batch_id=batch.id,
                        original_name=original_name,
                        storage_path=str(destination),
                        file_order=file_order,
                    )
                )
            if active_overreceipt_rule is not None:
                session.add(
                    BatchOverreceiptRule(
                        batch_id=batch.id,
                        rule_version_id=active_overreceipt_rule.id,
                    )
                )
            _audit(
                session,
                user.id,
                "create_batch_with_files",
                "batch",
                batch.id,
                {
                    "file_count": len(original_names),
                    "overreceipt_rule_version_id": (
                        active_overreceipt_rule.id
                        if active_overreceipt_rule is not None
                        else None
                    ),
                },
            )
            session.commit()
        except HTTPException:
            session.rollback()
            for path in created_paths:
                await run_in_threadpool(path.unlink, missing_ok=True)
            raise
        except Exception as error:
            session.rollback()
            for path in created_paths:
                await run_in_threadpool(path.unlink, missing_ok=True)
            if isinstance(error, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"交货文件校验失败：{error}",
                ) from error
            raise
        finally:
            for temporary_path in temporary_paths:
                await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        return batch_json(batch, session)

    @app.post(
        "/api/self-operated-batches",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_self_operated_batch(
        request: Request,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        name: Annotated[str | None, Form()] = None,
        delivery_file: list[UploadFile] | None = File(None),
        inbound_file: UploadFile | None = File(None),
    ):
        if name is None:
            try:
                name = str((await request.json()).get("name") or "")
            except ValueError:
                name = ""
        batch_name = name.strip()
        if not batch_name:
            raise HTTPException(status_code=400, detail="批次名称不能为空")
        if len(batch_name) > 200:
            raise HTTPException(status_code=400, detail="批次名称不能超过 200 个字符")

        active_versions = {
            version.kind: version
            for version in session.scalars(
                select(InputVersion).where(InputVersion.active.is_(True))
            )
        }
        missing = [
            kind for kind in SELF_OPERATED_INPUT_KINDS if kind not in active_versions
        ]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"缺少启用的输入版本：{', '.join(missing)}",
            )
        delivery_files = delivery_file or []
        if not delivery_files and inbound_file is None:
            active_rule = session.scalar(
                select(SelfOperatedOverreceiptRuleVersion).where(
                    SelfOperatedOverreceiptRuleVersion.active.is_(True)
                )
            )
            batch = Batch(
                name=batch_name,
                created_by=user.id,
                purchase_version_id=None,
                product_version_id=active_versions["product"].id,
                supplier_version_id=active_versions["supplier"].id,
                position_version_id=None,
                template_version_id=None,
            )
            session.add(batch)
            session.flush()
            session.add(
                SelfOperatedBatch(
                    batch_id=batch.id,
                    template_version_id=active_versions["inbound_template"].id,
                    rule_version_id=(
                        active_rule.id if active_rule is not None else None
                    ),
                    inbound_original_name="",
                    inbound_storage_path="",
                )
            )
            _audit(
                session,
                user.id,
                "create_empty_self_operated_batch",
                "batch",
                batch.id,
            )
            session.commit()
            return batch_json(batch, session)
        if not delivery_files:
            raise HTTPException(status_code=400, detail="缺少质检交货单")
        if len(delivery_files) > app.state.max_batch_upload_files:
            for upload in delivery_files:
                await upload.close()
            if inbound_file is not None:
                await inbound_file.close()
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "单批次最多上传 "
                    f"{app.state.max_batch_upload_files} 份质检交货单"
                ),
            )
        api_inbound_version = active_versions.get("self_operated_inbound")
        if inbound_file is None and api_inbound_version is None:
            raise HTTPException(
                status_code=409,
                detail="缺少启用的待入库 API 数据",
            )
        delivery_names = [
            _safe_filename(upload.filename or "") for upload in delivery_files
        ]
        if len(delivery_names) != len(set(delivery_names)):
            for upload in delivery_files:
                await upload.close()
            if inbound_file is not None:
                await inbound_file.close()
            raise HTTPException(status_code=409, detail="同一批次不可上传同名文件")
        inbound_name = (
            _safe_filename(inbound_file.filename or "")
            if inbound_file is not None
            else api_inbound_version.original_name
        )
        if any(
            Path(delivery_name).suffix.lower() not in {".xls", ".xlsx"}
            for delivery_name in delivery_names
        ):
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        if inbound_file is not None and Path(inbound_name).suffix.lower() not in {
            ".xls",
            ".xlsx",
        }:
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")

        temporary_root = storage / "temporary" / "self-operated-batches"
        token = uuid4().hex
        temporary_deliveries = [
            temporary_root / f"{token}_delivery_{index}_{delivery_name}"
            for index, delivery_name in enumerate(delivery_names, start=1)
        ]
        temporary_inbound = (
            temporary_root / f"{token}_inbound_{inbound_name}"
            if inbound_file is not None
            else None
        )
        created_paths: list[Path] = []
        active_rule = session.scalar(
            select(SelfOperatedOverreceiptRuleVersion).where(
                SelfOperatedOverreceiptRuleVersion.active.is_(True)
            )
        )
        try:
            for upload, temporary_delivery in zip(
                delivery_files,
                temporary_deliveries,
                strict=True,
            ):
                await _save_upload(
                    upload,
                    temporary_delivery,
                    app.state.max_upload_bytes,
                )
                await parse_uploaded_workbook(
                    read_self_operated_delivery_workbook,
                    temporary_delivery,
                )
            if inbound_file is not None and temporary_inbound is not None:
                await _save_upload(
                    inbound_file,
                    temporary_inbound,
                    app.state.max_upload_bytes,
                )
                await parse_uploaded_workbook(
                    read_self_operated_inbound_workbook,
                    temporary_inbound,
                )
                inbound_source_path = temporary_inbound
            else:
                inbound_source_path = Path(api_inbound_version.storage_path)
                if not await run_in_threadpool(inbound_source_path.is_file):
                    raise ValueError("启用的待入库 API 数据文件不存在")
                await parse_uploaded_workbook(
                    read_self_operated_inbound_workbook,
                    inbound_source_path,
                )

            batch = Batch(
                name=batch_name,
                created_by=user.id,
                purchase_version_id=None,
                product_version_id=active_versions["product"].id,
                supplier_version_id=active_versions["supplier"].id,
                position_version_id=None,
                template_version_id=None,
            )
            session.add(batch)
            session.flush()
            input_root = storage / "batches" / str(batch.id) / "inputs"
            await run_in_threadpool(input_root.mkdir, parents=True, exist_ok=True)
            delivery_paths = []
            for temporary_delivery, delivery_name in zip(
                temporary_deliveries,
                delivery_names,
                strict=True,
            ):
                delivery_path = input_root / f"{uuid4().hex}_{delivery_name}"
                await run_in_threadpool(
                    os.replace,
                    temporary_delivery,
                    delivery_path,
                )
                created_paths.append(delivery_path)
                delivery_paths.append(delivery_path)
            if inbound_file is not None:
                inbound_path = input_root / f"{uuid4().hex}_{inbound_name}"
                await run_in_threadpool(os.replace, inbound_source_path, inbound_path)
                created_paths.append(inbound_path)
            else:
                inbound_path = inbound_source_path

            session.add_all(
                [
                    BatchFile(
                        batch_id=batch.id,
                        original_name=delivery_name,
                        storage_path=str(delivery_path),
                        file_order=file_order,
                    )
                    for file_order, (delivery_name, delivery_path) in enumerate(
                        zip(delivery_names, delivery_paths, strict=True),
                        start=1,
                    )
                ]
            )
            session.add(
                SelfOperatedBatch(
                    batch_id=batch.id,
                    template_version_id=active_versions["inbound_template"].id,
                    rule_version_id=(
                        active_rule.id if active_rule is not None else None
                    ),
                    inbound_original_name=inbound_name,
                    inbound_storage_path=str(inbound_path),
                )
            )
            _audit(
                session,
                user.id,
                "create_self_operated_batch",
                "batch",
                batch.id,
                {
                    "rule_version_id": (
                        active_rule.id if active_rule is not None else None
                    ),
                    "template_version_id": active_versions["inbound_template"].id,
                    "delivery_file": delivery_names[0],
                    "delivery_files": delivery_names,
                    "inbound_file": inbound_name,
                    "inbound_version_id": (
                        api_inbound_version.id if inbound_file is None else None
                    ),
                },
            )
            session.commit()
        except HTTPException:
            session.rollback()
            for path in created_paths:
                await run_in_threadpool(path.unlink, missing_ok=True)
            raise
        except Exception as error:
            session.rollback()
            for path in created_paths:
                await run_in_threadpool(path.unlink, missing_ok=True)
            if isinstance(error, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"自营仓文件校验失败：{error}",
                ) from error
            raise
        finally:
            for temporary_delivery in temporary_deliveries:
                await run_in_threadpool(temporary_delivery.unlink, missing_ok=True)
            if temporary_inbound is not None:
                await run_in_threadpool(temporary_inbound.unlink, missing_ok=True)
        return batch_json(batch, session)

    @app.delete("/api/batches")
    def delete_batches(
        payload: BatchDeletePayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch_ids = list(dict.fromkeys(payload.batch_ids))
        batches = session.scalars(
            select(Batch)
            .where(Batch.id.in_(batch_ids))
            .order_by(Batch.id)
            .with_for_update()
        ).all()
        found_ids = {batch.id for batch in batches}
        missing_ids = [batch_id for batch_id in batch_ids if batch_id not in found_ids]
        if missing_ids:
            missing_text = "、".join(str(batch_id) for batch_id in missing_ids)
            raise HTTPException(
                status_code=404,
                detail=f"批次不存在：{missing_text}",
            )

        active_job_batch_ids = set(
            session.scalars(
                select(Job.batch_id).where(
                    Job.batch_id.in_(batch_ids),
                    Job.status.in_({"queued", "running"}),
                )
            ).all()
        )
        active_batches = [
            batch
            for batch in batches
            if batch.status in {"queued", "running"}
            or batch.id in active_job_batch_ids
        ]
        if active_batches:
            active_text = "、".join(
                f"{batch.id}（{batch.name}）" for batch in active_batches
            )
            raise HTTPException(
                status_code=409,
                detail=f"以下批次存在排队或运行中的任务，不能删除：{active_text}",
            )

        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id.in_(batch_ids))
        ).all()
        source_ids = [source.id for source in sources]
        exception_ids = (
            session.scalars(
                select(ExceptionRecord.id).where(
                    ExceptionRecord.batch_file_id.in_(source_ids)
                )
            ).all()
            if source_ids
            else []
        )
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
            )
            session.execute(
                delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
            )
        session.execute(
            delete(SelfOperatedSiteResolution).where(
                SelfOperatedSiteResolution.batch_id.in_(batch_ids)
            )
        )
        session.execute(delete(BatchFile).where(BatchFile.batch_id.in_(batch_ids)))
        session.execute(
            delete(BatchOverreceiptRule).where(
                BatchOverreceiptRule.batch_id.in_(batch_ids)
            )
        )
        session.execute(delete(Job).where(Job.batch_id.in_(batch_ids)))
        session.execute(
            delete(SelfOperatedBatch).where(SelfOperatedBatch.batch_id.in_(batch_ids))
        )
        session.execute(delete(Batch).where(Batch.id.in_(batch_ids)))
        _audit(
            session,
            admin.id,
            "delete_batches",
            "batch",
            "bulk",
            {
                "batch_ids": batch_ids,
                "batch_names": [batch.name for batch in batches],
            },
        )
        session.commit()

        file_cleanup_failed_ids = []
        for batch_id in batch_ids:
            batch_root = storage / "batches" / str(batch_id)
            try:
                if batch_root.exists():
                    shutil.rmtree(batch_root)
            except OSError:
                file_cleanup_failed_ids.append(batch_id)
        return {
            "deleted_count": len(batch_ids),
            "deleted_ids": batch_ids,
            "file_cleanup_failed_ids": file_cleanup_failed_ids,
        }

    @app.delete("/api/batches/empty")
    def delete_empty_delivery_batches(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        empty_batches = session.scalars(
            select(Batch)
            .outerjoin(
                SelfOperatedBatch,
                SelfOperatedBatch.batch_id == Batch.id,
            )
            .where(
                Batch.status == "draft",
                SelfOperatedBatch.batch_id.is_(None),
                ~select(BatchFile.id).where(BatchFile.batch_id == Batch.id).exists(),
            )
        ).all()
        batch_ids = [batch.id for batch in empty_batches]
        if not batch_ids:
            return {"deleted_count": 0, "deleted_ids": []}

        session.execute(
            delete(BatchOverreceiptRule).where(
                BatchOverreceiptRule.batch_id.in_(batch_ids)
            )
        )
        session.execute(delete(Job).where(Job.batch_id.in_(batch_ids)))
        session.execute(delete(Batch).where(Batch.id.in_(batch_ids)))
        _audit(
            session,
            user.id,
            "delete_empty_delivery_batches",
            "batch",
            "delivery_empty",
            {"batch_ids": batch_ids},
        )
        session.commit()
        return {"deleted_count": len(batch_ids), "deleted_ids": batch_ids}

    @app.delete("/api/self-operated-batches/empty")
    def delete_empty_self_operated_batches(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        empty_batches = session.scalars(
            select(Batch)
            .join(SelfOperatedBatch, SelfOperatedBatch.batch_id == Batch.id)
            .where(
                Batch.status == "draft",
                SelfOperatedBatch.inbound_storage_path == "",
                ~select(BatchFile.id).where(BatchFile.batch_id == Batch.id).exists(),
            )
        ).all()
        batch_ids = [batch.id for batch in empty_batches]
        if not batch_ids:
            return {"deleted_count": 0, "deleted_ids": []}

        session.execute(
            delete(SelfOperatedSiteResolution).where(
                SelfOperatedSiteResolution.batch_id.in_(batch_ids)
            )
        )
        session.execute(delete(Job).where(Job.batch_id.in_(batch_ids)))
        session.execute(
            delete(SelfOperatedBatch).where(SelfOperatedBatch.batch_id.in_(batch_ids))
        )
        session.execute(delete(Batch).where(Batch.id.in_(batch_ids)))
        _audit(
            session,
            user.id,
            "delete_empty_self_operated_batches",
            "batch",
            "self_operated_empty",
            {"batch_ids": batch_ids},
        )
        session.commit()
        return {"deleted_count": len(batch_ids), "deleted_ids": batch_ids}

    @app.post("/api/batches/{batch_id}/refresh-supplier-version")
    def refresh_batch_supplier_version(
        batch_id: int,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = session.scalar(
            select(Batch).where(Batch.id == batch_id).with_for_update()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        if batch.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="仅草稿状态批次可以更新供应商资料版本",
            )
        active_supplier = session.scalar(
            select(InputVersion).where(
                InputVersion.kind == "supplier",
                InputVersion.active.is_(True),
            )
        )
        if active_supplier is None:
            raise HTTPException(status_code=409, detail="当前没有启用的供应商资料版本")

        previous_version_id = batch.supplier_version_id
        batch.supplier_version_id = active_supplier.id
        _audit(
            session,
            admin.id,
            "refresh_batch_supplier_version",
            "batch",
            batch.id,
            {
                "previous_supplier_version_id": previous_version_id,
                "supplier_version_id": active_supplier.id,
            },
        )
        session.commit()
        return batch_json(batch, session)

    @app.post("/api/self-operated-batches/{batch_id}/inbound-file")
    async def upload_self_operated_inbound_file(
        batch_id: int,
        file: UploadFile = File(...),
        user: User = Depends(current_user),
        session: Session = Depends(get_session),
    ):
        batch = get_batch_or_404(batch_id, session)
        profile = session.get(SelfOperatedBatch, batch.id)
        if profile is None:
            raise HTTPException(status_code=404, detail="自营仓入库批次不存在")
        if batch.status not in {"draft", "preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可修改文件")
        original_name = _safe_filename(file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        destination = (
            storage
            / "batches"
            / str(batch.id)
            / "inputs"
            / f"{uuid4().hex}_{original_name}"
        )
        await _save_upload(file, destination, app.state.max_upload_bytes)
        try:
            await parse_uploaded_workbook(
                read_self_operated_inbound_workbook,
                destination,
            )
        except Exception as error:
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"自营仓收货入库单校验失败：{error}",
            ) from error

        try:
            batch = get_batch_or_404(batch_id, session, for_update=True)
            if batch.status not in {"draft", "preflight_ready", "failed"}:
                raise HTTPException(status_code=409, detail="当前批次状态不可修改文件")
            profile = session.scalar(
                select(SelfOperatedBatch)
                .where(SelfOperatedBatch.batch_id == batch_id)
                .execution_options(populate_existing=True)
            )
            if profile is None:
                raise HTTPException(status_code=404, detail="自营仓入库批次不存在")
            old_path = (
                Path(profile.inbound_storage_path)
                if profile.inbound_storage_path
                else None
            )
            profile.inbound_original_name = original_name
            profile.inbound_storage_path = str(destination)
            batch.status = "draft"
            batch.error_message = None
            batch.zip_path = None
            _audit(
                session,
                user.id,
                "upload_self_operated_inbound_file",
                "batch",
                batch.id,
                {"original_name": original_name},
            )
            session.commit()
        except Exception:
            session.rollback()
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise
        if old_path is not None and old_path != destination:
            await run_in_threadpool(_unlink_after_commit, old_path)
        return batch_json(batch, session)

    @app.post(
        "/api/batches/{batch_id}/files",
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_batch_file(
        batch_id: int,
        file: UploadFile = File(...),
        user: User = Depends(current_user),
        session: Session = Depends(get_session),
    ):
        batch = get_batch_or_404(batch_id, session)
        if batch.status not in {"draft", "preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可修改文件")
        source_count = session.scalar(
            select(func.count())
            .select_from(BatchFile)
            .where(BatchFile.batch_id == batch.id)
        )
        if source_count >= app.state.max_batch_upload_files:
            await file.close()
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"单批次最多上传 {app.state.max_batch_upload_files} 份交货文件",
            )
        original_name = _safe_filename(file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        duplicate = session.scalar(
            select(BatchFile).where(
                BatchFile.batch_id == batch.id,
                BatchFile.original_name == original_name,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="同一批次不可上传同名文件")
        destination = (
            storage
            / "batches"
            / str(batch.id)
            / "inputs"
            / f"{uuid4().hex}_{original_name}"
        )
        await _save_upload(file, destination, app.state.max_upload_bytes)
        try:
            async with batch_file_upload_lock:
                batch = get_batch_or_404(batch_id, session, for_update=True)
                if batch.status not in {"draft", "preflight_ready", "failed"}:
                    raise HTTPException(
                        status_code=409,
                        detail="当前批次状态不可修改文件",
                    )
                source_count = session.scalar(
                    select(func.count())
                    .select_from(BatchFile)
                    .where(BatchFile.batch_id == batch.id)
                )
                if source_count >= app.state.max_batch_upload_files:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            "单批次最多上传 "
                            f"{app.state.max_batch_upload_files} 份交货文件"
                        ),
                    )
                duplicate = session.scalar(
                    select(BatchFile).where(
                        BatchFile.batch_id == batch.id,
                        BatchFile.original_name == original_name,
                    )
                )
                if duplicate is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="同一批次不可上传同名文件",
                    )
                current_max = (
                    session.scalar(
                        select(func.max(BatchFile.file_order)).where(
                            BatchFile.batch_id == batch.id
                        )
                    )
                    or 0
                )
                source = BatchFile(
                    batch_id=batch.id,
                    original_name=original_name,
                    storage_path=str(destination),
                    file_order=current_max + 1,
                )
                session.add(source)
                batch.status = "draft"
                batch.error_message = None
                session.flush()
                _audit(
                    session,
                    user.id,
                    "upload_batch_file",
                    "batch_file",
                    source.id,
                    {"batch_id": batch.id},
                )
                session.commit()
        except HTTPException:
            session.rollback()
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise
        except IntegrityError as error:
            session.rollback()
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="文件上传发生并发冲突，请刷新后重试",
            ) from error
        return file_json(source)

    @app.delete("/api/batches/{batch_id}/files/{file_id}")
    def delete_batch_file(
        batch_id: int,
        file_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session, for_update=True)
        if batch.status not in {"draft", "preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可删除文件")
        source = session.scalar(
            select(BatchFile).where(
                BatchFile.id == file_id,
                BatchFile.batch_id == batch.id,
            )
        )
        if source is None:
            raise HTTPException(status_code=404, detail="交货文件不存在")
        storage_path = Path(source.storage_path)
        exception_ids = session.scalars(
            select(ExceptionRecord.id).where(ExceptionRecord.batch_file_id == source.id)
        ).all()
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
            )
            session.execute(
                delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
            )
        session.delete(source)
        session.flush()
        remaining = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        for item in remaining:
            item.file_order = -item.id
        session.flush()
        for file_order, item in enumerate(remaining, start=1):
            item.file_order = file_order
        batch.status = "draft"
        batch.error_message = None
        batch.zip_path = None
        _audit(
            session,
            user.id,
            "delete_batch_file",
            "batch_file",
            source.id,
            {"batch_id": batch.id, "original_name": source.original_name},
        )
        session.commit()
        _unlink_after_commit(storage_path)
        return batch_json(batch, session)

    @app.put("/api/batches/{batch_id}/files/order")
    def reorder_batch_files(
        batch_id: int,
        payload: FileOrderPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session, for_update=True)
        if batch.status not in {"draft", "preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可调整顺序")
        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id == batch.id)
        ).all()
        by_id = {source.id: source for source in sources}
        if len(payload.file_ids) != len(set(payload.file_ids)) or set(
            payload.file_ids
        ) != set(by_id):
            raise HTTPException(status_code=400, detail="文件顺序必须完整且不可重复")
        for source in sources:
            source.file_order = -source.id
        session.flush()
        for file_order, source_id in enumerate(payload.file_ids, start=1):
            by_id[source_id].file_order = file_order
        batch.status = "draft"
        _audit(
            session,
            user.id,
            "reorder_batch_files",
            "batch",
            batch.id,
            {"file_ids": payload.file_ids},
        )
        session.commit()
        return batch_json(batch, session)

    @app.post("/api/batches/{batch_id}/preflight")
    def preflight_batch(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        if batch.status not in {"draft", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可预检")
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        if not sources:
            raise HTTPException(status_code=400, detail="批次至少需要一个交货文件")
        self_operated = session.get(SelfOperatedBatch, batch.id)
        input_signature = _batch_input_signature(batch, sources, self_operated)
        versions = {}
        version_kinds = (
            ("product", "supplier") if self_operated is not None else INPUT_KINDS
        )
        for kind in version_kinds:
            version_id = getattr(batch, VERSION_FIELDS[kind])
            if version_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="批次锁定的输入文件不完整",
                )
            version = session.get(InputVersion, version_id)
            if version is None or not Path(version.storage_path).is_file():
                raise HTTPException(status_code=400, detail="批次锁定的输入文件不完整")
            versions[kind] = Path(version.storage_path)
        if any(not Path(source.storage_path).is_file() for source in sources):
            raise HTTPException(status_code=400, detail="批次锁定的输入文件不完整")

        validation_error = None
        try:
            supplier_rows = read_supplier_workbook(versions["supplier"])
            read_product_workbook(versions["product"])
            if self_operated is not None:
                inbound_path = Path(self_operated.inbound_storage_path)
                if not self_operated.inbound_storage_path or not inbound_path.is_file():
                    raise ValueError("尚未上传自营仓收货入库单")
                template = session.get(
                    InputVersion,
                    self_operated.template_version_id,
                )
                if template is None or not Path(template.storage_path).is_file():
                    raise ValueError("批次锁定的积加入库模板不存在")
                read_self_operated_inbound_workbook(inbound_path)
                validate_self_operated_template_workbook(Path(template.storage_path))
                for source in sources:
                    try:
                        read_self_operated_delivery_workbook(
                            Path(source.storage_path)
                        )
                        resolve_supplier(Path(source.original_name), supplier_rows)
                    except Exception as error:
                        raise ValueError(
                            f"{source.original_name}：{error}"
                        ) from error
            else:
                read_purchase_workbook(versions["purchase"])
                read_position_workbook(versions["position"])
                validate_template_workbook(versions["template"])
                for source in sources:
                    read_delivery_workbook(Path(source.storage_path))
                    resolve_supplier(Path(source.original_name), supplier_rows)
        except Exception as error:
            validation_error = error
        batch = get_batch_or_404(batch_id, session, for_update=True)
        current_sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch_id)
            .order_by(BatchFile.file_order)
            .execution_options(populate_existing=True)
        ).all()
        current_self_operated = session.scalar(
            select(SelfOperatedBatch)
            .where(SelfOperatedBatch.batch_id == batch_id)
            .execution_options(populate_existing=True)
        )
        if batch.status not in {"draft", "failed"} or _batch_input_signature(
            batch, current_sources, current_self_operated
        ) != input_signature:
            raise HTTPException(
                status_code=409,
                detail="预检期间批次输入已变更，请重新执行预检",
            )
        if validation_error is not None:
            raise HTTPException(
                status_code=400,
                detail=f"预检失败：{validation_error}",
            ) from validation_error
        batch.status = "preflight_ready"
        batch.error_message = None
        _audit(session, user.id, "preflight_batch", "batch", batch.id)
        session.commit()
        return batch_json(batch, session)

    def queue_job(batch: Batch, kind: str, user: User, session: Session) -> Job:
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == kind)
        )
        if existing and existing.status in {"queued", "running", "succeeded"}:
            return existing
        if existing is None:
            existing = Job(batch_id=batch.id, kind=kind, status="queued")
            session.add(existing)
        else:
            existing.status = "queued"
            existing.error_message = None
            existing.output_path = None
            existing.claim_token = None
            existing.claimed_at = None
            existing.heartbeat_at = None
            existing.finished_at = None
        session.flush()
        _audit(
            session,
            user.id,
            f"queue_{kind}",
            "job",
            existing.id,
            {"batch_id": batch.id},
        )
        return existing

    @app.post("/api/batches/{batch_id}/compute", status_code=status.HTTP_202_ACCEPTED)
    def start_compute(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session, for_update=True)
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "compute")
        )
        if existing and existing.status in {"queued", "running", "succeeded"}:
            return job_json(existing)
        if batch.status not in {"preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="批次尚未通过预检")
        try:
            job = queue_job(batch, "compute", user, session)
            batch.status = "queued"
            batch.error_message = None
            session.commit()
        except IntegrityError:
            session.rollback()
            job = session.scalar(
                select(Job).where(Job.batch_id == batch.id, Job.kind == "compute")
            )
            if job is None:
                raise
        return job_json(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job_json(job)

    register_exception_write_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        position_frame_cache=position_frame_cache,
        exception_position_values=_exception_position_values,
        split_records_by_exception=_split_records_by_exception,
        exception_json=_exception_json,
        queue_job=queue_job,
        job_json=job_json,
        audit=_audit,
    )

    register_batch_export_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        get_batch_or_404=get_batch_or_404,
        merged_export_path=merged_export_path,
        merged_export_ready=merged_export_ready,
        queue_job=queue_job,
        job_json=job_json,
    )

    @app.get("/api/audit-logs")
    def list_audit_logs(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        logs = session.scalars(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(200)
        ).all()
        return [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": utc_isoformat(log.created_at),
            }
            for log in logs
        ]

    return app
