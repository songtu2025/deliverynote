from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .exception_transfer_files import transfer_sites
from .exception_transfers import ExceptionTransferService, TransferItem
from .inbound_exception_routes import _load_source, load_purchase_options
from .models import User


class TransferItemPayload(BaseModel):
    exception_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, gt=0)
    full_site: str = Field(min_length=1)


class TransferPayload(BaseModel):
    name: str | None = None
    items: list[TransferItemPayload] = Field(min_length=1)


def register_exception_transfer_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    service: ExceptionTransferService,
) -> None:
    @app.get("/api/exceptions/{exception_id}/transfer-options", response_model=None)
    def options(
        exception_id: int,
        _user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, object]:
        exception, source, batch, _ = _load_source(session, exception_id)
        sites = transfer_sites(session, batch, exception.sku)
        try:
            purchases = load_purchase_options(
                session, exception, source, batch, service.creator.storage
            )
        except HTTPException as error:
            if error.status_code != 409:
                raise
            return {
                "sites": sites,
                "purchases": [],
                "queried_at": None,
                "purchase_error": error.detail,
            }
        return {
            "sites": sites,
            "purchases": purchases["items"],
            "queried_at": purchases["queried_at"],
            "purchase_error": None,
        }

    @app.post(
        "/api/batches/{batch_id}/exceptions/transfer-to-delivery",
        status_code=201,
        response_model=None,
    )
    def transfer(
        batch_id: int,
        payload: TransferPayload,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, int]:
        return {
            "id": service.transfer(
                session,
                batch_id,
                user.id,
                name=payload.name,
                items=[TransferItem(**item.model_dump()) for item in payload.items],
            )
        }
