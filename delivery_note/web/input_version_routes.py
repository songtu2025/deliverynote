from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .dependencies import RequestDependencies
from .input_versions import (
    UPLOAD_INPUT_KINDS,
    _validate_input_version,
    activate_input_version_record,
    register_uploaded_input_version,
    validate_new_input_version,
)
from .models import InputVersion, User
from .serializers import version_json
from .uploads import UploadParser, _safe_filename, _save_upload


@dataclass
class InputUploadForm:
    """上传输入版本所需的表单字段。"""

    name: Annotated[str, Form()]
    activate: Annotated[bool, Form()] = False
    file: UploadFile = File(...)


def register_input_version_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    storage: Path,
    parse_uploaded_workbook: UploadParser,
    _audit: Callable[..., None],
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user
    admin_user = dependencies.admin_user

    @app.post(
        "/api/input-versions/{kind}",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    async def upload_input_version(
        kind: str,
        form: Annotated[InputUploadForm, Depends()],
        admin: User = Depends(admin_user),
        session: Session = Depends(get_session),
    ) -> dict[str, object]:
        name, activate, file = form.name, form.activate, form.file
        if kind not in UPLOAD_INPUT_KINDS:
            raise HTTPException(status_code=404, detail="输入类型不存在")
        original_name = _safe_filename(file.filename or "")
        suffix = Path(original_name).suffix.lower()
        template_label = {
            "template": "导出模板",
            "inbound_template": "积加入库模板",
        }.get(kind)
        if template_label is not None and suffix != ".xlsx":
            raise HTTPException(
                status_code=400, detail=f"{template_label}仅支持 .xlsx 文件"
            )
        if suffix not in {".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail="仅支持 .xls、.xlsx 文件")
        validate_new_input_version(session, kind, name)
        destination = storage / "master" / kind / f"{uuid4().hex}_{original_name}"
        await _save_upload(file, destination, app.state.max_upload_bytes)
        try:
            await parse_uploaded_workbook(_validate_input_version, kind, destination)
        except Exception as error:
            await run_in_threadpool(destination.unlink, missing_ok=True)
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
        register_uploaded_input_version(session, version, _audit)
        return version_json(version)

    @app.get("/api/input-versions", response_model=None)
    def list_input_versions(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[dict[str, object]]:
        versions = session.scalars(
            select(InputVersion).order_by(
                InputVersion.kind, InputVersion.created_at.desc()
            )
        ).all()
        return [version_json(version) for version in versions]

    @app.post("/api/input-versions/{version_id}/activate", response_model=None)
    def activate_input_version(
        version_id: int,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        version = activate_input_version_record(session, version_id, admin.id, _audit)
        return version_json(version)
