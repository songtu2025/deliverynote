import asyncio
import os
from pathlib import Path
from threading import Lock
from typing import Annotated, Callable
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..excel_io import (
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
)
from ..input_inspection import (
    inspect_input_version_with_preview,
    preview_input_version_page,
)
from ..migrations.runner import migrate_schema as run_schema_migrations
from .auth_routes import register_auth_routes
from .dependencies import build_request_dependencies
from .health_routes import register_health_routes
from .auth import hash_password
from .job_routes import build_job_queue, register_job_routes
from .batch_creation import DeliveryBatchCreator
from .batch_creation_routes import register_batch_creation_routes
from .batch_file_edits import BatchFileEditor
from .batch_file_uploads import BatchFileUploader
from .batch_file_routes import register_batch_file_routes
from .batch_export_routes import register_batch_export_routes
from .batch_read_routes import register_batch_read_routes
from .batch_maintenance import BatchMaintenance
from .batch_maintenance_routes import register_batch_maintenance_routes
from .batch_views import (
    batch_json, batch_list_json, merged_export_path, merged_export_ready,
)
from .database import Database
from .errors import (
    register_exception_handlers,
)
from .position_draft_import import PositionDraftImporter
from .position_draft_import_routes import register_position_draft_import_routes
from .position_draft_lifecycle import PositionDraftLifecycle
from .position_draft_lifecycle_routes import register_position_draft_lifecycle_routes
from .position_draft_row_routes import register_position_draft_row_routes
from .position_draft_read_routes import register_position_draft_read_routes
from .position_import_candidates import PositionImportCandidates
from .overreceipt_routes import register_overreceipt_routes
from .self_operated_rule_routes import register_self_operated_rule_routes
from .input_version_routes import register_input_version_routes
from .input_versions import SELF_OPERATED_INPUT_KINDS
from .input_versions import bootstrap_builtin_templates
from .uploads import _safe_filename, _save_upload
from .gerpgo_routes import register_gerpgo_routes
from .exception_views import (
    _exception_json, _exception_position_values, _split_records_by_exception,
)
from .exception_read_routes import register_exception_read_routes
from .exception_write_routes import register_exception_write_routes
from .input_version_read_routes import register_input_version_read_routes
from .models import (
    AuditLog,
    Batch,
    BatchFile,
    InputVersion,
    SelfOperatedBatch,
    SelfOperatedOverreceiptRuleVersion,
    User,
)
from .sync_routes import register_sync_routes
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
    register_position_draft_row_routes(app, dependencies, import_candidates_state)
    register_position_draft_import_routes(
        app, dependencies,
        PositionDraftImporter(app, import_candidates_state, parse_uploaded_workbook),
    )
    register_position_draft_lifecycle_routes(
        app, dependencies,
        PositionDraftLifecycle(
            storage, _audit, draft_analysis_cache, import_candidates_state
        ),
    )














    register_batch_creation_routes(
        app, dependencies,
        DeliveryBatchCreator(app, storage, _audit, parse_uploaded_workbook),
    )
    register_batch_file_routes(
        app, dependencies,
        BatchFileUploader(app, dependencies, storage, _audit, parse_uploaded_workbook),
        BatchFileEditor(dependencies, _audit),
    )
    register_batch_maintenance_routes(
        app, dependencies, BatchMaintenance(storage, _audit)
    )



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













    queue_job = build_job_queue(_audit)
    register_job_routes(app, dependencies, queue_job, _audit)

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


    return app
