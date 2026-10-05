"""库位草稿创建、发布和丢弃的 HTTP 入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .models import User
from .position_draft_lifecycle import PositionDraftLifecycle
from .schemas import DraftMutationPayload, PublishDraftPayload


def register_position_draft_lifecycle_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    lifecycle: PositionDraftLifecycle,
) -> None:
    get_session = dependencies.get_session
    admin_user = dependencies.admin_user
    get_draft_or_404 = dependencies.get_draft_or_404

    @app.post(
        "/api/input-drafts/position",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def create_position_draft(
        response: Response,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        result, resuming = lifecycle.create(session, admin.id)
        if resuming:
            response.status_code = status.HTTP_200_OK
        return result

    @app.post(
        "/api/input-drafts/{draft_id}/publish",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def publish_position_draft(
        draft_id: int,
        payload: PublishDraftPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        draft = get_draft_or_404(draft_id, session)
        return lifecycle.publish(session, draft, payload, admin.id)

    @app.post("/api/input-drafts/{draft_id}/discard", response_model=None)
    def discard_position_draft(
        draft_id: int,
        payload: DraftMutationPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        draft = get_draft_or_404(draft_id, session)
        return lifecycle.discard(session, draft, payload, admin.id)
