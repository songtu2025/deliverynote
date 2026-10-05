"""自营批次创建的 HTTP 入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .models import User
from .schemas import SelfOperatedBatchForm
from .self_operated_creation import SelfOperatedBatchCreator


def register_self_operated_creation_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    creator: SelfOperatedBatchCreator,
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user

    @app.post(
        "/api/self-operated-batches",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    async def create_self_operated_batch(
        request: Request,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        form: Annotated[SelfOperatedBatchForm, Depends()],
    ) -> dict[str, object]:
        return await creator.create(session, request, form, user.id)
