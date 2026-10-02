"""普通交货批次创建的 HTTP 入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI, status
from sqlalchemy.orm import Session

from .batch_creation import DeliveryBatchCreator
from .dependencies import RequestDependencies
from .models import User
from .schemas import BatchPayload, DeliveryBatchForm


def register_batch_creation_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    creator: DeliveryBatchCreator,
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user

    @app.post("/api/batches", status_code=status.HTTP_201_CREATED)
    def create_batch(
        payload: BatchPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return creator.create(session, payload, user.id)

    @app.post(
        "/api/batches/with-files",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_batch_with_files(
        form: Annotated[DeliveryBatchForm, Depends()],
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return await creator.create_with_files(session, form, user.id)
