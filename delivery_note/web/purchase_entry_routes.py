"""采购单预览和 Excel、ZIP 下载接口。"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .dependencies import RequestDependencies
from .models import User
from .purchase_entry_service import PurchaseEntryService, purchase_versions

EXPORT_MEDIA_TYPES = {
    "merged": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "split": ("application/zip", "zip"),
}


def register_purchase_entry_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    service: PurchaseEntryService,
    audit: Callable[..., None],
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user

    @app.post("/api/purchase-entry/preview", response_model=None)
    async def preview_purchase_entry(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        versions = await run_in_threadpool(purchase_versions, session)
        result, _ = await service.process(file, versions)
        return {
            **result.to_preview(),
            "versions": {kind: version.id for kind, version in versions.items()},
        }

    @app.post(
        "/api/purchase-entry/export",
        response_class=Response,
        responses={
            200: {
                "description": "采购导出文件",
                "content": {
                    mime: {"schema": {"type": "string", "format": "binary"}}
                    for mime, _ in EXPORT_MEDIA_TYPES.values()
                },
            }
        },
    )
    async def export_purchase_entry(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        version_ids: Annotated[str, Form()],
        mode: Annotated[str, Form()] = "merged",
        file: UploadFile = File(...),
    ) -> Response:
        if mode not in EXPORT_MEDIA_TYPES:
            raise HTTPException(400, "导出方式仅支持 merged 或 split")
        versions = await run_in_threadpool(purchase_versions, session, version_ids)
        result, output = await service.process(file, versions, mode)
        audit(
            session,
            user.id,
            "export_purchase_entry",
            "purchase_entry",
            "conversion",
            {
                "mode": mode,
                "row_count": result.row_count,
                "batch_count": result.batch_count,
                "total_quantity": result.total_quantity,
                "versions": {kind: version.id for kind, version in versions.items()},
            },
        )
        await run_in_threadpool(session.commit)
        mime, suffix = EXPORT_MEDIA_TYPES[mode]
        return Response(
            content=output,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="purchase-entry.{suffix}"'
            },
        )
