import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from ..gerpgo import (
    GerpgoClient,
    GerpgoError,
    GerpgoSettings,
    load_gerpgo_settings,
    save_gerpgo_settings,
)
from .dependencies import RequestDependencies
from .models import User
from .schemas import GerpgoConfigPayload
from .serializers import gerpgo_config_json


def register_gerpgo_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    storage: Path,
    _audit: Callable[..., None],
) -> None:
    get_session = dependencies.get_session
    admin_user = dependencies.admin_user

    @app.get("/api/admin/integrations/gerpgo")
    def get_gerpgo_config(
        _admin: Annotated[User, Depends(admin_user)],
    ):
        try:
            return gerpgo_config_json(load_gerpgo_settings(storage))
        except GerpgoError:
            return {
                "configured": False,
                "base_url": os.getenv(
                    "GERPGO_API_BASE_URL",
                    "https://open.gerpgo.com/api/open",
                ).strip(),
                "app_id_hint": "",
                "has_app_id": False,
                "has_app_key": False,
                "source": "environment",
            }

    @app.put("/api/admin/integrations/gerpgo")
    def update_gerpgo_config(
        payload: GerpgoConfigPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        try:
            current = load_gerpgo_settings(storage)
        except GerpgoError:
            current = None

        base_url = payload.base_url.strip().rstrip("/")
        app_id = payload.app_id.strip() or (current.app_id if current else "")
        app_key = payload.app_key.strip() or (current.app_key if current else "")
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail="API 地址必须使用 HTTP 或 HTTPS"
            )
        if not app_id or not app_key:
            raise HTTPException(status_code=400, detail="请填写 App ID 和 App Key")

        settings = GerpgoSettings(
            base_url=base_url,
            app_id=app_id,
            app_key=app_key,
            source="managed",
        )
        try:
            GerpgoClient(base_url, app_id, app_key).authenticate()
        except GerpgoError as error:
            raise HTTPException(
                status_code=400,
                detail=f"积加连接验证失败：{error}",
            ) from error
        try:
            save_gerpgo_settings(storage, settings)
        except OSError as error:
            raise HTTPException(status_code=500, detail="积加配置保存失败") from error

        _audit(
            session,
            admin.id,
            "update_gerpgo_config",
            "integration_config",
            "gerpgo",
            details={
                "base_url": base_url,
                "app_id_changed": bool(payload.app_id.strip()),
                "app_key_changed": bool(payload.app_key.strip()),
            },
        )
        session.commit()
        return gerpgo_config_json(settings)
