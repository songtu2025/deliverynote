from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .models import InputVersion, User


def register_input_version_read_routes(
    app: FastAPI,
    *,
    get_session: Callable,
    admin_user: Callable,
    inspect_version: Callable[[InputVersion, int, int], dict],
) -> None:
    def get_version_or_404(version_id: int, session: Session) -> InputVersion:
        version = session.get(InputVersion, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="输入版本不存在")
        return version

    @app.get("/api/input-versions/{version_id}/summary")
    def input_version_summary(
        version_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        version = get_version_or_404(version_id, session)
        try:
            return inspect_version(version, 0, 20)["summary"]
        except Exception as error:
            raise HTTPException(
                status_code=400,
                detail=f"输入版本读取失败：{error}",
            ) from error

    @app.get("/api/input-versions/{version_id}/inspection")
    def input_version_inspection(
        version_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        version = get_version_or_404(version_id, session)
        try:
            return inspect_version(version, offset, limit)
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
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        version = get_version_or_404(version_id, session)
        try:
            return inspect_version(version, offset, limit)["preview"]
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
        version = get_version_or_404(version_id, session)
        path = Path(version.storage_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="输入版本文件不存在")
        return FileResponse(path, filename=version.original_name)
