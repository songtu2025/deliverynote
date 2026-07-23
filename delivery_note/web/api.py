from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
from threading import Lock
from typing import Annotated
from uuid import uuid4

import pandas as pd
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..application import SplitPart, project_split
from ..config import PURCHASE_STATUSES, resolve_supplier, warehouse_sort_key
from ..excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_supplier_workbook,
    validate_template_workbook,
)
from ..input_inspection import (
    inspect_input_version,
    position_change_warnings,
    position_diff,
    preview_input_version,
    validate_position_frame,
    write_position_workbook,
)
from ..pipeline import (
    IMPORT_COLUMNS,
    POSITION_SOURCE_COLUMNS,
    POSITION_VALUE_COLUMNS,
    enrich_pending_import_rows,
)
from .auth import hash_password, hash_token, new_session_token, verify_password
from .database import Database
from .models import (
    AuditLog,
    AuthSession,
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputDraft,
    InputVersion,
    Job,
    OverreceiptRuleVersion,
    PositionDraftRow,
    SplitRecord,
    User,
)
from .position_drafts import (
    FIELD_TO_COLUMN,
    ROW_FIELDS,
    DraftConflict,
    create_or_resume_draft,
    delete_draft_rows,
    discard_draft,
    list_draft_rows,
    load_draft_frames,
    mutate_draft_row,
    publish_draft,
    replace_draft_from_frame,
    require_revision,
)


INPUT_KINDS = ("purchase", "product", "supplier", "position", "template")
VERSION_FIELDS = {
    "purchase": "purchase_version_id",
    "product": "product_version_id",
    "supplier": "supplier_version_id",
    "position": "position_version_id",
    "template": "template_version_id",
}
BATCH_STATUSES = {
    "draft",
    "preflight_ready",
    "queued",
    "running",
    "succeeded",
    "failed",
    "expired",
}
ROLES = {"admin", "operator"}
POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL = (
    "库位资料已有正式版本，请使用“开始网页维护”通过草稿流程发布新版本"
)


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class LoginPayload(BaseModel):
    username: str
    password: str


class UserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: str = "operator"


class UserStatusPayload(BaseModel):
    active: bool


class PasswordResetPayload(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class BatchPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FileOrderPayload(BaseModel):
    file_ids: list[int]


class SplitPartPayload(BaseModel):
    quantity: int
    destination: str = ""
    site: str = ""
    supplier_code: str = ""
    sku: str = ""
    delivery_note: str = ""
    resolved: bool = True


class SplitPayload(BaseModel):
    parts: list[SplitPartPayload]


class DraftMutationPayload(BaseModel):
    revision: int = Field(ge=1)


class PositionRowPayload(DraftMutationPayload):
    store_site: str = Field(min_length=1)
    jiaji_sku: str = Field(min_length=1)
    msku: str = ""
    scale_position: str = ""
    stocking_position: str = ""
    ordered_days: str = ""


class BulkDeletePayload(DraftMutationPayload):
    row_ids: list[int] = Field(min_length=1)


class ImportApplyPayload(DraftMutationPayload):
    token: str = Field(min_length=1)


class PublishDraftPayload(DraftMutationPayload):
    name: str = Field(min_length=1, max_length=200)
    confirm_warnings: bool = False


class OverreceiptRulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    short_tail_limit: int = Field(ge=0)
    medium_tail_limit: int = Field(ge=0)
    long_tail_limit: int = Field(ge=0)
    allowed_warehouses: list[str]


def _user_json(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "active": user.active,
    }


def _version_json(version: InputVersion) -> dict:
    return {
        "id": version.id,
        "kind": version.kind,
        "name": version.name,
        "original_name": version.original_name,
        "active": version.active,
        "created_by": version.created_by,
        "created_at": _utc_isoformat(version.created_at),
    }


def _overreceipt_rule_json(version: OverreceiptRuleVersion) -> dict:
    return {
        "id": version.id,
        "name": version.name,
        "short_tail_limit": version.short_tail_limit,
        "medium_tail_limit": version.medium_tail_limit,
        "long_tail_limit": version.long_tail_limit,
        "allowed_warehouses": version.allowed_warehouses,
        "active": version.active,
        "created_by": version.created_by,
        "created_at": _utc_isoformat(version.created_at),
    }


def _position_row_json(
    row: PositionDraftRow,
    issues: list[dict] | None = None,
) -> dict:
    return {
        "id": row.id,
        "draft_id": row.draft_id,
        "row_order": row.row_order,
        "store_site": row.store_site,
        "jiaji_sku": row.jiaji_sku,
        "msku": row.msku,
        "scale_position": row.scale_position,
        "stocking_position": row.stocking_position,
        "ordered_days": row.ordered_days,
        "change_type": row.change_type,
        "deleted": row.deleted,
        "issues": issues or [],
    }


def _position_frame(rows: list[PositionDraftRow]) -> pd.DataFrame:
    records = [
        {
            FIELD_TO_COLUMN[field]: getattr(row, field)
            for field in ROW_FIELDS
        }
        for row in rows
        if not row.deleted
    ]
    return pd.DataFrame(records, columns=POSITION_SOURCE_COLUMNS)


def _position_issue_map(rows: list[PositionDraftRow]) -> tuple[list[dict], dict[int, list[dict]]]:
    active_rows = [row for row in rows if not row.deleted]
    issues = validate_position_frame(_position_frame(active_rows))
    by_row_id: dict[int, list[dict]] = {row.id: [] for row in active_rows}
    for issue in issues:
        for row_number in issue["row_numbers"]:
            offset = row_number - 2
            if 0 <= offset < len(active_rows):
                by_row_id[active_rows[offset].id].append(issue)
    return issues, by_row_id


def _issue_summary(issues: list[dict]) -> dict:
    error_count = sum(
        max(1, len(issue["row_numbers"]))
        for issue in issues
        if issue["severity"] == "error"
    )
    warning_count = sum(
        max(1, len(issue["row_numbers"]))
        for issue in issues
        if issue["severity"] == "warning"
    )
    return {
        "issues": issues,
        "error_count": error_count,
        "warning_count": warning_count,
        "valid": error_count == 0,
    }


def _draft_analysis(
    session: Session,
    draft: InputDraft,
) -> tuple[list[PositionDraftRow], dict[str, int], list[dict]]:
    """一次生成草稿摘要所需的行、差异和校验结果。"""

    rows, base_frame, current_frame = load_draft_frames(session, draft)
    issues = [
        *validate_position_frame(current_frame),
        *position_change_warnings(base_frame, current_frame),
    ]
    return rows, position_diff(base_frame, current_frame), issues


def _draft_json(session: Session, draft: InputDraft) -> dict:
    rows, diff, issues = _draft_analysis(session, draft)
    active_rows = [row for row in rows if not row.deleted]
    base_version = session.get(InputVersion, draft.base_version_id)
    active_version = session.scalar(
        select(InputVersion).where(
            InputVersion.kind == "position",
            InputVersion.active.is_(True),
        )
    )
    issue_summary = _issue_summary(issues)
    return {
        "id": draft.id,
        "kind": draft.kind,
        "base_version_id": draft.base_version_id,
        "base_version_name": (
            base_version.name
            if base_version is not None
            else f"版本 #{draft.base_version_id}"
        ),
        "active_version_id": active_version.id if active_version is not None else None,
        "active_version_name": active_version.name if active_version is not None else None,
        "status": draft.status,
        "revision": draft.revision,
        "created_by": draft.created_by,
        "updated_by": draft.updated_by,
        "created_at": _utc_isoformat(draft.created_at),
        "updated_at": _utc_isoformat(draft.updated_at),
        "row_count": len(active_rows),
        "modified_count": sum(row.change_type != "unchanged" for row in rows),
        "diff": diff,
        **issue_summary,
    }


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


def _batch_exception_data(
    session: Session,
    sources: list[BatchFile],
) -> tuple[
    dict[int, list[ExceptionRecord]],
    dict[int, list[SplitRecord]],
]:
    source_ids = [source.id for source in sources]
    if not source_ids:
        return {}, {}
    exceptions = session.scalars(
        select(ExceptionRecord)
        .where(ExceptionRecord.batch_file_id.in_(source_ids))
        .order_by(ExceptionRecord.batch_file_id, ExceptionRecord.id)
    ).all()
    grouped: dict[int, list[ExceptionRecord]] = {}
    for exception in exceptions:
        grouped.setdefault(exception.batch_file_id, []).append(exception)
    return grouped, _split_records_by_exception(session, exceptions)


def _file_totals(
    source: BatchFile,
    exceptions: list[ExceptionRecord],
    splits_by_exception: dict[int, list[SplitRecord]],
) -> tuple[int, int]:
    import_total = source.import_total
    manual_total = 0
    for exception in exceptions:
        parts = splits_by_exception.get(exception.id, [])
        if not parts:
            manual_total += exception.manual_quantity
            continue
        import_total += sum(part.quantity for part in parts if part.resolved)
        manual_total += sum(part.quantity for part in parts if not part.resolved)
    return import_total, manual_total


def _file_json(
    source: BatchFile,
    exceptions: list[ExceptionRecord] | None = None,
    splits_by_exception: dict[int, list[SplitRecord]] | None = None,
) -> dict:
    if exceptions is None or splits_by_exception is None:
        import_total = source.import_total
        manual_total = source.manual_total
    else:
        import_total, manual_total = _file_totals(
            source,
            exceptions,
            splits_by_exception,
        )
    return {
        "id": source.id,
        "batch_id": source.batch_id,
        "original_name": source.original_name,
        "file_order": source.file_order,
        "supplier_name": source.supplier_name,
        "supplier_code": source.supplier_code,
        "document_note": source.document_note,
        "delivery_total": source.delivery_total,
        "import_total": import_total,
        "manual_total": manual_total,
        "download_ready": bool(source.result_path),
    }


def _batch_summary(
    sources: list[BatchFile],
    exceptions_by_source: dict[int, list[ExceptionRecord]],
    splits_by_exception: dict[int, list[SplitRecord]],
) -> dict:
    delivery_total = sum(source.delivery_total for source in sources)
    import_total = sum(source.import_total for source in sources)
    manual_total = 0
    for source in sources:
        for exception in exceptions_by_source.get(source.id, []):
            parts = splits_by_exception.get(exception.id, [])
            if not parts:
                manual_total += exception.manual_quantity
                continue
            import_total += sum(
                part.quantity for part in parts if part.resolved
            )
            manual_total += sum(
                part.quantity for part in parts if not part.resolved
            )
    return {
        "delivery_total": delivery_total,
        "import_total": import_total,
        "manual_total": manual_total,
        "conserved": delivery_total == import_total + manual_total,
    }


def _merged_export_path(batch: Batch) -> Path | None:
    if not batch.zip_path:
        return None
    return Path(batch.zip_path).with_name(f"batch-{batch.id}-merged.xlsx")


def _merged_export_ready(batch: Batch, source_count: int) -> bool:
    path = _merged_export_path(batch)
    return source_count > 1 and path is not None and path.is_file()


def _batch_json(batch: Batch, session: Session, include_files: bool = True) -> dict:
    sources = session.scalars(
        select(BatchFile)
        .where(BatchFile.batch_id == batch.id)
        .order_by(BatchFile.file_order)
    ).all()
    exceptions_by_source, splits_by_exception = _batch_exception_data(
        session,
        sources,
    )
    overreceipt_binding = session.get(BatchOverreceiptRule, batch.id)
    overreceipt_rule = (
        session.get(OverreceiptRuleVersion, overreceipt_binding.rule_version_id)
        if overreceipt_binding is not None
        else None
    )
    result = {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "created_by": batch.created_by,
        "version_ids": {
            kind: getattr(batch, field)
            for kind, field in VERSION_FIELDS.items()
        },
        "overreceipt_rule": (
            _overreceipt_rule_json(overreceipt_rule)
            if overreceipt_rule is not None
            else None
        ),
        "error_message": batch.error_message,
        "download_ready": bool(batch.zip_path),
        "merged_download_ready": _merged_export_ready(batch, len(sources)),
        "created_at": _utc_isoformat(batch.created_at),
        "updated_at": _utc_isoformat(batch.updated_at),
        "file_count": len(sources),
        "summary": _batch_summary(
            sources,
            exceptions_by_source,
            splits_by_exception,
        ),
    }
    if include_files:
        result["files"] = [
            _file_json(
                source,
                exceptions_by_source.get(source.id, []),
                splits_by_exception,
            )
            for source in sources
        ]
        result["versions"] = {
            kind: _version_json(version)
            for kind, field in VERSION_FIELDS.items()
            if (version := session.get(InputVersion, getattr(batch, field))) is not None
        }
        result["jobs"] = {
            job.kind: _job_json(job)
            for job in session.scalars(
                select(Job).where(Job.batch_id == batch.id).order_by(Job.id)
            ).all()
        }
    return result


def _job_json(job: Job) -> dict:
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "error_message": job.error_message,
        "download_ready": bool(job.output_path),
        "created_at": _utc_isoformat(job.created_at),
        "claimed_at": _utc_isoformat(job.claimed_at) if job.claimed_at else None,
        "heartbeat_at": _utc_isoformat(job.heartbeat_at) if job.heartbeat_at else None,
        "finished_at": _utc_isoformat(job.finished_at) if job.finished_at else None,
    }


def _validate_input_version(kind: str, path: Path) -> None:
    if kind == "purchase":
        read_purchase_workbook(path)
    elif kind == "product":
        read_product_workbook(path)
    elif kind == "supplier":
        read_supplier_workbook(path)
    elif kind == "position":
        read_position_workbook(path)
    else:
        validate_template_workbook(path)


def _exception_position_values(
    exceptions: list[ExceptionRecord],
    batch: Batch,
    session: Session,
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
        enriched = enrich_pending_import_rows(
            pending_rows,
            read_position_workbook(Path(version.storage_path)),
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
            ("scale_position", "stocking_position", "ordered_days"),
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
) -> dict:
    position_values = position_values or {}
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
        "status": exception.status,
        "scale_position": position_values.get("scale_position", ""),
        "stocking_position": position_values.get("stocking_position", ""),
        "ordered_days": position_values.get("ordered_days", ""),
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


def _safe_filename(filename: str) -> str:
    safe = Path(filename).name
    safe = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", safe).strip(" .")
    if not safe:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    return safe


async def _save_upload(
    upload: UploadFile,
    destination: Path,
    max_bytes: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    bytes_written = 0
    try:
        with temporary.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"上传文件不能超过 {max_bytes} 字节",
                    )
                output.write(chunk)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
        await upload.close()


def create_app(
    database_url: str | None = None,
    storage_root: Path | str | None = None,
    bootstrap_admin: tuple[str, str] | None = None,
    max_upload_bytes: int | None = None,
    import_candidate_ttl_seconds: int | None = None,
) -> FastAPI:
    database = Database(
        database_url
        or os.getenv("DATABASE_URL", "sqlite+pysqlite:///delivery_note.db")
    )
    database.create_schema()
    storage = Path(storage_root or os.getenv("STORAGE_ROOT", "storage")).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    configured_max_upload_bytes = (
        max_upload_bytes
        if max_upload_bytes is not None
        else int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    )
    if configured_max_upload_bytes <= 0:
        raise ValueError("MAX_UPLOAD_BYTES 必须大于 0")
    configured_import_candidate_ttl = (
        import_candidate_ttl_seconds
        if import_candidate_ttl_seconds is not None
        else int(os.getenv("IMPORT_CANDIDATE_TTL_SECONDS", "900"))
    )
    if configured_import_candidate_ttl <= 0:
        raise ValueError("IMPORT_CANDIDATE_TTL_SECONDS 必须大于 0")
    import_candidate_root = storage / "temporary" / "position-imports"
    import_candidate_root.mkdir(parents=True, exist_ok=True)
    startup_expiry_cutoff = (
        datetime.now().timestamp() - configured_import_candidate_ttl
    )
    for stale_candidate in import_candidate_root.iterdir():
        if (
            stale_candidate.is_file()
            and stale_candidate.stat().st_mtime <= startup_expiry_cutoff
        ):
            stale_candidate.unlink(missing_ok=True)
    # Tokens are intentionally process-local while Compose runs one API process.
    # A multi-process deployment must move this registry to shared database state.
    import_candidates: dict[str, dict] = {}
    import_candidates_lock = Lock()
    batch_file_upload_lock = Lock()
    overreceipt_rule_lock = Lock()

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

    app = FastAPI(title="供应链交货处理系统", version="1.0.0")
    app.state.database = database
    app.state.storage_root = storage
    app.state.max_upload_bytes = configured_max_upload_bytes
    app.state.import_candidate_ttl_seconds = configured_import_candidate_ttl
    app.state.position_import_candidates = import_candidates
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

    bearer = HTTPBearer(auto_error=False)

    def get_session():
        session = database.SessionLocal()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def current_user(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer),
        ],
        session: Annotated[Session, Depends(get_session)],
    ) -> User:
        if credentials is None:
            raise HTTPException(status_code=401, detail="未登录")
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_token(credentials.credentials)
            )
        )
        if auth_session is None or auth_session.expires_at <= datetime.utcnow():
            raise HTTPException(status_code=401, detail="登录已失效")
        user = session.get(User, auth_session.user_id)
        if user is None or not user.active:
            raise HTTPException(status_code=401, detail="用户不可用")
        return user

    def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user

    def get_batch_or_404(batch_id: int, session: Session) -> Batch:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        return batch

    def get_draft_or_404(draft_id: int, session: Session) -> InputDraft:
        draft = session.get(InputDraft, draft_id)
        if draft is None or draft.kind != "position":
            raise HTTPException(status_code=404, detail="库位草稿不存在")
        return draft

    def commit_once(session: Session) -> None:
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise

    def rollback_draft_conflict(session: Session, error: Exception) -> None:
        if session.in_transaction():
            session.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(error).strip() or "草稿已被其他管理员更新，请刷新后重试",
        ) from error

    def ensure_position_bootstrap_upload_allowed(session: Session) -> None:
        position_version_id = session.scalar(
            select(InputVersion.id).where(InputVersion.kind == "position")
        )
        if position_version_id is not None:
            raise HTTPException(
                status_code=409,
                detail=POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL,
            )

    def rollback_integrity_conflict(session: Session, error: Exception) -> None:
        if session.in_transaction():
            session.rollback()
        raise HTTPException(
            status_code=409,
            detail="草稿写入发生并发冲突，请刷新后重试",
        ) from error

    def remove_import_candidate(token: str) -> dict | None:
        with import_candidates_lock:
            candidate = import_candidates.pop(token, None)
        if candidate is not None:
            Path(candidate["path"]).unlink(missing_ok=True)
        return candidate

    def remove_draft_import_candidates(draft_id: int) -> None:
        with import_candidates_lock:
            tokens = [
                token
                for token, candidate in import_candidates.items()
                if candidate["draft_id"] == draft_id
            ]
        for token in tokens:
            remove_import_candidate(token)

    def remove_expired_import_candidates() -> None:
        now = datetime.utcnow()
        with import_candidates_lock:
            expired = [
                (token, import_candidates.pop(token))
                for token in list(import_candidates)
                if import_candidates[token]["expires_at"] <= now
            ]
        for _token, candidate in expired:
            Path(candidate["path"]).unlink(missing_ok=True)
        expiry_cutoff = (
            datetime.now().timestamp() - app.state.import_candidate_ttl_seconds
        )
        with import_candidates_lock:
            registered_paths = {
                Path(candidate["path"]).resolve()
                for candidate in import_candidates.values()
            }
        for candidate_path in import_candidate_root.iterdir():
            if (
                candidate_path.is_file()
                and candidate_path.resolve() not in registered_paths
                and candidate_path.stat().st_mtime <= expiry_cutoff
            ):
                candidate_path.unlink(missing_ok=True)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, session: Annotated[Session, Depends(get_session)]):
        user = session.scalar(select(User).where(User.username == payload.username))
        if user is None or not user.active or not verify_password(
            payload.password, user.password_hash
        ):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token, token_hash, expires_at = new_session_token()
        session.add(
            AuthSession(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=expires_at,
            )
        )
        _audit(session, user.id, "login", "user", user.id)
        session.commit()
        return {"token": token, "expires_at": _utc_isoformat(expires_at), "user": _user_json(user)}

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        session.execute(
            delete(AuthSession).where(
                AuthSession.token_hash == hash_token(credentials.credentials)
            )
        )
        _audit(session, user.id, "logout", "user", user.id)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/auth/me")
    def me(user: Annotated[User, Depends(current_user)]):
        return _user_json(user)

    @app.post("/api/users", status_code=status.HTTP_201_CREATED)
    def create_user(
        payload: UserPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        if payload.role not in ROLES:
            raise HTTPException(status_code=400, detail="角色无效")
        if session.scalar(select(User).where(User.username == payload.username)):
            raise HTTPException(status_code=409, detail="用户名已存在")
        user = User(
            username=payload.username,
            password_hash=hash_password(payload.password),
            role=payload.role,
        )
        session.add(user)
        session.flush()
        _audit(session, admin.id, "create_user", "user", user.id)
        session.commit()
        return _user_json(user)

    @app.get("/api/users")
    def list_users(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return [_user_json(user) for user in session.scalars(select(User).order_by(User.id))]

    @app.put("/api/users/{user_id}/status")
    def update_user_status(
        user_id: int,
        payload: UserStatusPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user.id == admin.id and not payload.active:
            raise HTTPException(status_code=409, detail="不能停用当前登录账号")
        user.active = payload.active
        if not payload.active:
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        _audit(
            session,
            admin.id,
            "update_user_status",
            "user",
            user.id,
            {"active": payload.active},
        )
        session.commit()
        return _user_json(user)

    @app.put(
        "/api/users/{user_id}/password",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def reset_user_password(
        user_id: int,
        payload: PasswordResetPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.password_hash = hash_password(payload.password)
        session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        _audit(session, admin.id, "reset_user_password", "user", user.id)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/input-versions/{kind}",
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_input_version(
        kind: str,
        name: Annotated[str, Form()],
        activate: Annotated[bool, Form()] = False,
        file: UploadFile = File(...),
        admin: User = Depends(admin_user),
        session: Session = Depends(get_session),
    ):
        if kind not in INPUT_KINDS:
            raise HTTPException(status_code=404, detail="输入类型不存在")
        original_name = _safe_filename(file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        if session.scalar(
            select(InputVersion).where(
                InputVersion.kind == kind,
                InputVersion.name == name,
            )
        ):
            raise HTTPException(status_code=409, detail="版本名称已存在")
        if kind == "position":
            ensure_position_bootstrap_upload_allowed(session)
        destination = storage / "master" / kind / f"{uuid4().hex}_{original_name}"
        await _save_upload(file, destination, app.state.max_upload_bytes)
        try:
            _validate_input_version(kind, destination)
        except Exception as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"输入版本校验失败：{error}",
            ) from error
        version = InputVersion(
            kind=kind,
            name=name,
            original_name=original_name,
            storage_path=str(destination),
            active=activate,
            created_by=admin.id,
        )
        try:
            if activate:
                current_versions = list(
                    session.scalars(
                        select(InputVersion)
                        .where(InputVersion.kind == kind)
                        .order_by(InputVersion.id)
                        .with_for_update()
                    )
                )
                if kind == "position" and current_versions:
                    raise HTTPException(
                        status_code=409,
                        detail=POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL,
                    )
                for current in current_versions:
                    current.active = False
                session.flush()
            session.add(version)
            session.flush()
            _audit(
                session,
                admin.id,
                "upload_input_version",
                "input_version",
                version.id,
                {"kind": kind},
            )
            session.commit()
        except HTTPException:
            session.rollback()
            destination.unlink(missing_ok=True)
            raise
        except IntegrityError as error:
            session.rollback()
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="输入版本发生并发冲突，请刷新后重试",
            ) from error
        return _version_json(version)

    @app.get("/api/input-versions")
    def list_input_versions(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        versions = session.scalars(
            select(InputVersion).order_by(InputVersion.kind, InputVersion.created_at.desc())
        ).all()
        return [_version_json(version) for version in versions]

    @app.get("/api/overreceipt-rule-versions/warehouses")
    def list_overreceipt_warehouses(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        purchase_version = session.scalar(
            select(InputVersion).where(
                InputVersion.kind == "purchase",
                InputVersion.active.is_(True),
            )
        )
        if purchase_version is None:
            return []
        try:
            purchases = read_purchase_workbook(Path(purchase_version.storage_path))
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=409,
                detail=f"启用的采购需求版本无法读取：{error}",
            ) from error
        active = purchases[purchases["单据状态"].isin(PURCHASE_STATUSES)]
        warehouses = {
            str(value).strip()
            for value in active["目的仓"]
            if not pd.isna(value) and str(value).strip()
        }
        return sorted(warehouses, key=warehouse_sort_key)

    @app.get("/api/overreceipt-rule-versions")
    def list_overreceipt_rule_versions(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        versions = session.scalars(
            select(OverreceiptRuleVersion).order_by(
                OverreceiptRuleVersion.created_at.desc(),
                OverreceiptRuleVersion.id.desc(),
            )
        ).all()
        return [_overreceipt_rule_json(version) for version in versions]

    @app.post(
        "/api/overreceipt-rule-versions",
        status_code=status.HTTP_201_CREATED,
    )
    def publish_overreceipt_rule(
        payload: OverreceiptRulePayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        name = payload.name.strip()
        warehouses = [warehouse.strip() for warehouse in payload.allowed_warehouses]
        if not name:
            raise HTTPException(status_code=400, detail="规则版本名称不能为空")
        if any(not warehouse for warehouse in warehouses):
            raise HTTPException(status_code=400, detail="允许超收仓库不能为空")
        if len(set(warehouses)) != len(warehouses):
            raise HTTPException(status_code=400, detail="允许超收仓库不能重复")
        warehouses = sorted(warehouses, key=warehouse_sort_key)

        with overreceipt_rule_lock:
            current_versions = list(
                session.scalars(
                    select(OverreceiptRuleVersion)
                    .order_by(OverreceiptRuleVersion.id)
                    .with_for_update()
                )
            )
            if any(version.name == name for version in current_versions):
                raise HTTPException(status_code=409, detail="规则版本名称已存在")
            for current in current_versions:
                current.active = False
            session.flush()
            version = OverreceiptRuleVersion(
                name=name,
                short_tail_limit=payload.short_tail_limit,
                medium_tail_limit=payload.medium_tail_limit,
                long_tail_limit=payload.long_tail_limit,
                allowed_warehouses=warehouses,
                active=True,
                created_by=user.id,
            )
            session.add(version)
            try:
                session.flush()
                _audit(
                    session,
                    user.id,
                    "publish_overreceipt_rule",
                    "overreceipt_rule",
                    version.id,
                    {
                        "short_tail_limit": version.short_tail_limit,
                        "medium_tail_limit": version.medium_tail_limit,
                        "long_tail_limit": version.long_tail_limit,
                        "allowed_warehouses": version.allowed_warehouses,
                    },
                )
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="超收规则发布发生并发冲突，请刷新后重试",
                ) from error
        return _overreceipt_rule_json(version)

    @app.post("/api/overreceipt-rule-versions/{version_id}/activate")
    def activate_overreceipt_rule(
        version_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        with overreceipt_rule_lock:
            versions = list(
                session.scalars(
                    select(OverreceiptRuleVersion)
                    .order_by(OverreceiptRuleVersion.id)
                    .with_for_update()
                )
            )
            target = next(
                (version for version in versions if version.id == version_id),
                None,
            )
            if target is None:
                raise HTTPException(status_code=404, detail="超收规则版本不存在")
            if target.active:
                return _overreceipt_rule_json(target)
            for version in versions:
                version.active = False
            session.flush()
            target.active = True
            _audit(
                session,
                user.id,
                "activate_overreceipt_rule",
                "overreceipt_rule",
                target.id,
            )
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="超收规则启用发生并发冲突，请刷新后重试",
                ) from error
        return _overreceipt_rule_json(target)

    @app.get("/api/input-versions/{version_id}/summary")
    def input_version_summary(
        version_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        version = session.get(InputVersion, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="输入版本不存在")
        try:
            return inspect_input_version(version.kind, Path(version.storage_path))
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail=f"输入版本读取失败：{error}",
            ) from error

    @app.get("/api/input-versions/{version_id}/preview")
    def input_version_preview(
        version_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        version = session.get(InputVersion, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="输入版本不存在")
        try:
            return preview_input_version(
                version.kind,
                Path(version.storage_path),
                offset,
                limit,
            )
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail=f"输入版本读取失败：{error}",
            ) from error

    @app.get("/api/input-versions/{version_id}/download")
    def download_input_version(
        version_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        version = session.get(InputVersion, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="输入版本不存在")
        path = Path(version.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="输入版本文件不存在")
        return FileResponse(path, filename=version.original_name)

    @app.post("/api/input-versions/{version_id}/activate")
    def activate_input_version(
        version_id: int,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        version = session.get(InputVersion, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="输入版本不存在")
        try:
            current_versions = list(
                session.scalars(
                    select(InputVersion)
                    .where(InputVersion.kind == version.kind)
                    .order_by(InputVersion.id)
                    .with_for_update()
                )
            )
            if version.kind == "position" and any(
                current.active and current.id != version.id
                for current in current_versions
            ):
                raise HTTPException(
                    status_code=409,
                    detail=POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL,
                )
            for current in current_versions:
                current.active = False
            session.flush()
            version.active = True
            _audit(
                session,
                admin.id,
                "activate_input_version",
                "input_version",
                version.id,
            )
            session.commit()
        except HTTPException:
            session.rollback()
            raise
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="输入版本发生并发冲突，请刷新后重试",
            ) from error
        return _version_json(version)

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
        except DraftConflict as error:
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
        return _draft_json(session, draft)

    @app.get("/api/input-drafts/position")
    def get_position_draft(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = session.scalar(
            select(InputDraft).where(
                InputDraft.kind == "position",
                InputDraft.status == "editing",
            )
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="当前没有进行中的库位草稿")
        return _draft_json(session, draft)

    @app.get("/api/input-drafts/{draft_id}/rows")
    def get_position_draft_rows(
        draft_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        search: str = "",
        site: str = "",
        scale_position: str = "",
        only_errors: bool = False,
        only_modified: bool = False,
    ):
        get_draft_or_404(draft_id, session)
        rows = [row for row in list_draft_rows(session, draft_id) if not row.deleted]
        _issues, issues_by_row = _position_issue_map(rows)
        search_value = search.strip().casefold()
        site_value = site.strip().casefold()
        scale_value = scale_position.strip().casefold()
        filtered = []
        for row in rows:
            values = [str(getattr(row, field) or "") for field in ROW_FIELDS]
            if search_value and not any(
                search_value in value.casefold() for value in values
            ):
                continue
            if site_value and row.store_site.strip().casefold() != site_value:
                continue
            if scale_value and row.scale_position.strip().casefold() != scale_value:
                continue
            if only_modified and row.change_type == "unchanged":
                continue
            if only_errors and not any(
                issue["severity"] == "error"
                for issue in issues_by_row.get(row.id, [])
            ):
                continue
            filtered.append(row)
        page = filtered[offset : offset + limit]
        return {
            "rows": [
                _position_row_json(row, issues_by_row.get(row.id))
                for row in page
            ],
            "total": len(filtered),
            "offset": offset,
            "limit": limit,
        }

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
        except DraftConflict as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        session.refresh(row)
        remove_draft_import_candidates(draft.id)
        return {"row": _position_row_json(row), "revision": draft.revision}

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
        except DraftConflict as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        session.refresh(row)
        remove_draft_import_candidates(draft.id)
        return {"row": _position_row_json(row), "revision": draft.revision}

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
        except DraftConflict as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        remove_draft_import_candidates(draft.id)
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
        except DraftConflict as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        session.refresh(draft)
        remove_draft_import_candidates(draft.id)
        return {"deleted_ids": payload.row_ids, "revision": draft.revision}

    @app.post("/api/input-drafts/{draft_id}/import-preview")
    async def preview_position_draft_import(
        draft_id: int,
        revision: Annotated[int, Form(ge=1)],
        file: UploadFile = File(...),
        _admin: User = Depends(admin_user),
        session: Session = Depends(get_session),
    ):
        remove_expired_import_candidates()
        draft = get_draft_or_404(draft_id, session)
        try:
            require_revision(draft, revision)
        except DraftConflict as error:
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
            candidate_frame = read_position_workbook(destination)
            current_frame = _position_frame(list_draft_rows(session, draft.id))
            issues = [
                *validate_position_frame(candidate_frame),
                *position_change_warnings(current_frame, candidate_frame),
            ]
            diff = position_diff(current_frame, candidate_frame)
        except Exception as error:
            destination.unlink(missing_ok=True)
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"导入文件校验失败：{error}",
            ) from error
        remove_draft_import_candidates(draft.id)
        with import_candidates_lock:
            import_candidates[token] = {
                "draft_id": draft.id,
                "revision": revision,
                "path": str(destination),
                "created_by": _admin.id,
                "expires_at": datetime.utcnow()
                + timedelta(seconds=app.state.import_candidate_ttl_seconds),
            }
        return {
            "token": token,
            "draft_id": draft.id,
            "revision": revision,
            "row_count": len(candidate_frame),
            "diff": diff,
            **_issue_summary(issues),
        }

    @app.post("/api/input-drafts/{draft_id}/import-apply")
    def apply_position_draft_import(
        draft_id: int,
        payload: ImportApplyPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        remove_expired_import_candidates()
        draft = get_draft_or_404(draft_id, session)
        with import_candidates_lock:
            candidate = import_candidates.get(payload.token)
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
            remove_import_candidate(payload.token)
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=409, detail="导入预览已失效，请重新预览")
        try:
            require_revision(draft, payload.revision)
        except DraftConflict as error:
            remove_import_candidate(payload.token)
            rollback_draft_conflict(session, error)
        with import_candidates_lock:
            candidate = import_candidates.pop(payload.token, None)
        if candidate is None:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=409, detail="导入预览已失效，请重新预览")
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
        except DraftConflict as error:
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
        remove_draft_import_candidates(draft.id)
        return {"diff": diff, "revision": draft.revision}

    @app.get("/api/input-drafts/{draft_id}/download")
    def download_position_draft(
        draft_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        download_root = storage / "temporary" / "draft-downloads"
        download_path = download_root / f"{uuid4().hex}.xlsx"
        try:
            write_position_workbook(
                download_path,
                _position_frame(list_draft_rows(session, draft.id)),
            )
        except Exception as error:
            download_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"草稿下载文件生成失败：{error}",
            ) from error
        return FileResponse(
            download_path,
            filename=f"position-draft-{draft.id}-r{draft.revision}.xlsx",
            background=BackgroundTask(download_path.unlink, missing_ok=True),
        )

    @app.post("/api/input-drafts/{draft_id}/validate")
    def validate_position_draft(
        draft_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        _rows, diff, issues = _draft_analysis(session, draft)
        return {
            "draft_id": draft.id,
            "revision": draft.revision,
            "diff": diff,
            **_issue_summary(issues),
        }

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
        except DraftConflict as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            if "版本名称已存在" in str(error):
                raise HTTPException(status_code=409, detail=str(error)) from error
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
        remove_draft_import_candidates(draft.id)
        return {
            **_version_json(version),
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
        except DraftConflict as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        session.refresh(draft)
        remove_draft_import_candidates(draft.id)
        return _draft_json(session, draft)

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
            **{
                VERSION_FIELDS[kind]: active_versions[kind].id
                for kind in INPUT_KINDS
            },
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
        return _batch_json(batch, session)

    @app.get("/api/batches")
    def list_batches(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batches = session.scalars(select(Batch).order_by(Batch.id.desc())).all()
        return [_batch_json(batch, session, include_files=False) for batch in batches]

    @app.get("/api/batches/{batch_id}")
    def get_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return _batch_json(get_batch_or_404(batch_id, session), session)

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
        destination = storage / "batches" / str(batch.id) / "inputs" / f"{uuid4().hex}_{original_name}"
        await _save_upload(file, destination, app.state.max_upload_bytes)
        try:
            with batch_file_upload_lock:
                batch = session.scalar(
                    select(Batch)
                    .where(Batch.id == batch_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if batch is None:
                    raise HTTPException(status_code=404, detail="批次不存在")
                if batch.status not in {"draft", "preflight_ready", "failed"}:
                    raise HTTPException(
                        status_code=409,
                        detail="当前批次状态不可修改文件",
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
                current_max = session.scalar(
                    select(func.max(BatchFile.file_order)).where(
                        BatchFile.batch_id == batch.id
                    )
                ) or 0
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
            destination.unlink(missing_ok=True)
            raise
        except IntegrityError as error:
            session.rollback()
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="文件上传发生并发冲突，请刷新后重试",
            ) from error
        return _file_json(source)

    @app.delete("/api/batches/{batch_id}/files/{file_id}")
    def delete_batch_file(
        batch_id: int,
        file_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
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
            select(ExceptionRecord.id).where(
                ExceptionRecord.batch_file_id == source.id
            )
        ).all()
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(
                    SplitRecord.exception_id.in_(exception_ids)
                )
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
        storage_path.unlink(missing_ok=True)
        return _batch_json(batch, session)

    @app.put("/api/batches/{batch_id}/files/order")
    def reorder_batch_files(
        batch_id: int,
        payload: FileOrderPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        if batch.status not in {"draft", "preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可调整顺序")
        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id == batch.id)
        ).all()
        by_id = {source.id: source for source in sources}
        if len(payload.file_ids) != len(set(payload.file_ids)) or set(payload.file_ids) != set(by_id):
            raise HTTPException(status_code=400, detail="文件顺序必须完整且不可重复")
        for source in sources:
            source.file_order = -source.id
        session.flush()
        for file_order, source_id in enumerate(payload.file_ids, start=1):
            by_id[source_id].file_order = file_order
        batch.status = "draft"
        _audit(session, user.id, "reorder_batch_files", "batch", batch.id, {"file_ids": payload.file_ids})
        session.commit()
        return _batch_json(batch, session)

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
        versions = {}
        for kind, field in VERSION_FIELDS.items():
            version = session.get(InputVersion, getattr(batch, field))
            if version is None or not Path(version.storage_path).is_file():
                raise HTTPException(status_code=400, detail="批次锁定的输入文件不完整")
            versions[kind] = Path(version.storage_path)
        if any(not Path(source.storage_path).is_file() for source in sources):
            raise HTTPException(status_code=400, detail="批次锁定的输入文件不完整")

        try:
            supplier_rows = read_supplier_workbook(versions["supplier"])
            read_product_workbook(versions["product"])
            read_purchase_workbook(versions["purchase"])
            read_position_workbook(versions["position"])
            validate_template_workbook(versions["template"])
            for source in sources:
                read_delivery_workbook(Path(source.storage_path))
                resolve_supplier(Path(source.original_name), supplier_rows)
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail=f"预检失败：{error}",
            ) from error
        batch.status = "preflight_ready"
        batch.error_message = None
        _audit(session, user.id, "preflight_batch", "batch", batch.id)
        session.commit()
        return _batch_json(batch, session)

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
        _audit(session, user.id, f"queue_{kind}", "job", existing.id, {"batch_id": batch.id})
        return existing

    @app.post("/api/batches/{batch_id}/compute", status_code=status.HTTP_202_ACCEPTED)
    def start_compute(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "compute")
        )
        if existing and existing.status in {"queued", "running", "succeeded"}:
            return _job_json(existing)
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
        return _job_json(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _job_json(job)

    @app.get("/api/batches/{batch_id}/exceptions")
    def list_exceptions(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        exceptions = session.scalars(
            select(ExceptionRecord)
            .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
            .where(BatchFile.batch_id == batch_id)
            .order_by(BatchFile.file_order, ExceptionRecord.id)
        ).all()
        position_values = _exception_position_values(exceptions, batch, session)
        splits_by_exception = _split_records_by_exception(
            session,
            exceptions,
        )
        return [
            _exception_json(
                exception,
                splits_by_exception.get(exception.id, []),
                position_values.get(exception.id),
            )
            for exception in exceptions
        ]

    @app.put("/api/exceptions/{exception_id}/split")
    def save_split(
        exception_id: int,
        payload: SplitPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        exception = session.scalar(
            select(ExceptionRecord)
            .where(ExceptionRecord.id == exception_id)
            .with_for_update()
        )
        if exception is None:
            raise HTTPException(status_code=404, detail="待处理记录不存在")
        source = session.get(BatchFile, exception.batch_file_id)
        batch = (
            session.scalar(
                select(Batch)
                .where(Batch.id == source.batch_id)
                .with_for_update()
            )
            if source
            else None
        )
        if batch is None or batch.status != "succeeded":
            raise HTTPException(status_code=409, detail="批次尚未计算成功")
        export_job = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
        )
        if export_job and export_job.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="导出任务运行期间不可修改拆分")
        position_values = _exception_position_values([exception], batch, session)
        previous_parts = session.scalars(
            select(SplitRecord)
            .where(SplitRecord.exception_id == exception.id)
            .order_by(SplitRecord.id)
        ).all()
        before_snapshot = [
            {
                "quantity": part.quantity,
                "destination": part.destination,
                "site": part.site,
                "supplier_code": part.supplier_code,
                "sku": part.sku,
                "delivery_note": part.delivery_note,
                "resolved": part.resolved,
            }
            for part in previous_parts
        ]
        parts = [SplitPart(**part.model_dump()) for part in payload.parts]
        exception_row = pd.Series(
            {
                "SKU": exception.sku,
                "原始站点": exception.original_site,
                "完整站点": exception.full_site,
                "目的仓": exception.destination,
                "交货量": exception.delivery_quantity,
                "已自动分配量": exception.allocated_quantity,
                "人工处理量": exception.manual_quantity,
                "异常原因": exception.reason,
            }
        )
        supplier_code = next(
            (part.supplier_code for part in parts if part.supplier_code),
            "",
        )
        if not supplier_code:
            supplier_code = source.supplier_code
        if not supplier_code:
            import_rows = source.import_rows or []
            supplier_code = (
                str(import_rows[0].get("*供应商编码", ""))
                if import_rows
                else ""
            )
        try:
            project_split(
                exception_row,
                parts,
                supplier_code=supplier_code,
                document_note=source.document_note,
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        session.execute(
            delete(SplitRecord).where(SplitRecord.exception_id == exception.id)
        )
        for part in parts:
            session.add(
                SplitRecord(
                    exception_id=exception.id,
                    quantity=part.quantity,
                    destination=part.destination,
                    site=part.site,
                    supplier_code=part.supplier_code,
                    sku=part.sku,
                    delivery_note=part.delivery_note,
                    resolved=part.resolved,
                )
            )
        resolved_count = sum(part.resolved for part in parts)
        exception.status = (
            "resolved"
            if resolved_count == len(parts)
            else "partial"
            if resolved_count
            else "pending"
        )
        if export_job:
            export_job.status = "stale"
            export_job.output_path = None
        batch.zip_path = None
        source.result_path = None
        _audit(
            session,
            user.id,
            "save_split",
            "exception",
            exception.id,
            {
                "before": before_snapshot,
                "after": [part.model_dump() for part in payload.parts],
            },
        )
        session.commit()
        splits = _split_records_by_exception(session, [exception])
        return _exception_json(
            exception,
            splits.get(exception.id, []),
            position_values.get(exception.id),
        )

    @app.post("/api/batches/{batch_id}/export", status_code=status.HTTP_202_ACCEPTED)
    def start_export(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = session.scalar(
            select(Batch).where(Batch.id == batch_id).with_for_update()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        if batch.status != "succeeded":
            raise HTTPException(status_code=409, detail="批次尚未计算成功")
        source_count = session.scalar(
            select(func.count())
            .select_from(BatchFile)
            .where(BatchFile.batch_id == batch.id)
        )
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
        )
        if (
            existing is not None
            and existing.status == "succeeded"
            and source_count > 1
            and not _merged_export_ready(batch, source_count)
        ):
            existing.status = "stale"
        try:
            job = queue_job(batch, "export", user, session)
            session.commit()
        except IntegrityError:
            session.rollback()
            job = session.scalar(
                select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
            )
            if job is None:
                raise
        return _job_json(job)

    @app.get("/api/batches/{batch_id}/download")
    def download_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        if not batch.zip_path or not Path(batch.zip_path).is_file():
            raise HTTPException(status_code=404, detail="批次导出尚未生成")
        return FileResponse(batch.zip_path, filename=Path(batch.zip_path).name)

    @app.get("/api/batches/{batch_id}/download-merged")
    def download_merged_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        source_count = session.scalar(
            select(func.count())
            .select_from(BatchFile)
            .where(BatchFile.batch_id == batch.id)
        )
        merged_path = _merged_export_path(batch)
        if (
            source_count <= 1
            or merged_path is None
            or not merged_path.is_file()
        ):
            raise HTTPException(status_code=404, detail="批次合并导出尚未生成")
        return FileResponse(merged_path, filename=merged_path.name)

    @app.get("/api/batch-files/{file_id}/download")
    def download_batch_file(
        file_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        source = session.get(BatchFile, file_id)
        if source is None or not source.result_path or not Path(source.result_path).is_file():
            raise HTTPException(status_code=404, detail="来源文件导出尚未生成")
        return FileResponse(source.result_path, filename=Path(source.result_path).name)

    @app.get("/api/audit-logs")
    def list_audit_logs(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        logs = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
        return [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": _utc_isoformat(log.created_at),
            }
            for log in logs
        ]

    return app
