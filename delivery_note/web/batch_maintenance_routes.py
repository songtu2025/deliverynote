"""批次清理和供应商版本更新的 HTTP 入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from .batch_maintenance import BatchMaintenance
from .dependencies import RequestDependencies
from .models import User
from .schemas import BatchDeletePayload


def register_batch_maintenance_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    maintenance: BatchMaintenance,
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user
    admin_user = dependencies.admin_user

    @app.delete("/api/batches", response_model=None)
    def delete_batches(
        payload: BatchDeletePayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        return maintenance.delete_selected(session, admin.id, payload.batch_ids)

    @app.delete("/api/batches/empty", response_model=None)
    def delete_empty_delivery_batches(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        return maintenance.delete_empty(session, user.id, False)

    @app.delete("/api/self-operated-batches/empty", response_model=None)
    def delete_empty_self_operated_batches(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        return maintenance.delete_empty(session, user.id, True)

    @app.post("/api/batches/{batch_id}/refresh-supplier-version", response_model=None)
    def refresh_batch_supplier_version(
        batch_id: int,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        return maintenance.refresh_supplier(session, batch_id, admin.id)
