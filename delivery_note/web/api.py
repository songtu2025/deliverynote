from datetime import datetime
import os
from pathlib import Path
import re
from typing import Annotated
from uuid import uuid4

import pandas as pd
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
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

from ..application import SplitPart, project_split
from ..config import resolve_supplier
from ..excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_supplier_workbook,
    validate_template_workbook,
)
from .auth import hash_password, hash_token, new_session_token, verify_password
from .database import Database
from .models import (
    AuditLog,
    AuthSession,
    Batch,
    BatchFile,
    ExceptionRecord,
    InputVersion,
    Job,
    SplitRecord,
    User,
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


class LoginPayload(BaseModel):
    username: str
    password: str


class UserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: str = "operator"


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
        "created_at": version.created_at.isoformat(),
    }


def _file_json(source: BatchFile) -> dict:
    return {
        "id": source.id,
        "batch_id": source.batch_id,
        "original_name": source.original_name,
        "file_order": source.file_order,
        "supplier_name": source.supplier_name,
        "supplier_code": source.supplier_code,
        "document_note": source.document_note,
        "delivery_total": source.delivery_total,
        "import_total": source.import_total,
        "manual_total": source.manual_total,
        "download_ready": bool(source.result_path),
    }


def _batch_summary(batch: Batch, session: Session, sources: list[BatchFile]) -> dict:
    delivery_total = sum(source.delivery_total for source in sources)
    import_total = sum(source.import_total for source in sources)
    manual_total = 0
    exceptions = session.scalars(
        select(ExceptionRecord)
        .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
        .where(BatchFile.batch_id == batch.id)
    ).all()
    for exception in exceptions:
        parts = session.scalars(
            select(SplitRecord).where(SplitRecord.exception_id == exception.id)
        ).all()
        if not parts:
            manual_total += exception.manual_quantity
            continue
        import_total += sum(part.quantity for part in parts if part.resolved)
        manual_total += sum(part.quantity for part in parts if not part.resolved)
    return {
        "delivery_total": delivery_total,
        "import_total": import_total,
        "manual_total": manual_total,
        "conserved": delivery_total == import_total + manual_total,
    }


def _batch_json(batch: Batch, session: Session, include_files: bool = True) -> dict:
    result = {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "created_by": batch.created_by,
        "version_ids": {
            kind: getattr(batch, field)
            for kind, field in VERSION_FIELDS.items()
        },
        "error_message": batch.error_message,
        "download_ready": bool(batch.zip_path),
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
    }
    if include_files:
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        result["files"] = [_file_json(source) for source in sources]
        result["summary"] = _batch_summary(batch, session, sources)
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
    }


def _exception_json(exception: ExceptionRecord, session: Session) -> dict:
    parts = session.scalars(
        select(SplitRecord)
        .where(SplitRecord.exception_id == exception.id)
        .order_by(SplitRecord.id)
    ).all()
    return {
        "id": exception.id,
        "batch_file_id": exception.batch_file_id,
        "sku": exception.sku,
        "original_site": exception.original_site,
        "full_site": exception.full_site,
        "destination": exception.destination,
        "delivery_quantity": exception.delivery_quantity,
        "allocated_quantity": exception.allocated_quantity,
        "manual_quantity": exception.manual_quantity,
        "reason": exception.reason,
        "status": exception.status,
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


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
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
) -> FastAPI:
    database = Database(
        database_url
        or os.getenv("DATABASE_URL", "sqlite+pysqlite:///delivery_note.db")
    )
    database.create_schema()
    storage = Path(storage_root or os.getenv("STORAGE_ROOT", "storage")).resolve()
    storage.mkdir(parents=True, exist_ok=True)

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
        return {"token": token, "expires_at": expires_at.isoformat(), "user": _user_json(user)}

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
        destination = storage / "master" / kind / f"{uuid4().hex}_{original_name}"
        await _save_upload(file, destination)
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
                for current in session.scalars(
                    select(InputVersion)
                    .where(InputVersion.kind == kind)
                    .with_for_update()
                ):
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
            for current in session.scalars(
                select(InputVersion)
                .where(InputVersion.kind == version.kind)
                .with_for_update()
            ):
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
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="输入版本发生并发冲突，请刷新后重试",
            ) from error
        return _version_json(version)

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
        _audit(session, user.id, "create_batch", "batch", batch.id)
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
        current_max = session.scalar(
            select(func.max(BatchFile.file_order)).where(BatchFile.batch_id == batch.id)
        ) or 0
        destination = storage / "batches" / str(batch.id) / "inputs" / f"{uuid4().hex}_{original_name}"
        await _save_upload(file, destination)
        source = BatchFile(
            batch_id=batch.id,
            original_name=original_name,
            storage_path=str(destination),
            file_order=current_max + 1,
        )
        session.add(source)
        batch.status = "draft"
        batch.error_message = None
        try:
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
        except IntegrityError as error:
            session.rollback()
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="文件上传发生并发冲突，请刷新后重试",
            ) from error
        return _file_json(source)

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
        get_batch_or_404(batch_id, session)
        exceptions = session.scalars(
            select(ExceptionRecord)
            .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
            .where(BatchFile.batch_id == batch_id)
            .order_by(BatchFile.file_order, ExceptionRecord.id)
        ).all()
        return [_exception_json(exception, session) for exception in exceptions]

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
        return _exception_json(exception, session)

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
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]

    return app
