"""库位草稿的导入预览和应用入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .dependencies import RequestDependencies
from .models import User
from .position_draft_import import PositionDraftImporter
from .schemas import ImportApplyPayload, PositionImportForm


def register_position_draft_import_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    importer: PositionDraftImporter,
) -> None:
    get_session = dependencies.get_session
    admin_user = dependencies.admin_user
    get_draft_or_404 = dependencies.get_draft_or_404

    @app.post("/api/input-drafts/{draft_id}/import-preview")
    async def preview_position_draft_import(
        draft_id: int,
        form: Annotated[PositionImportForm, Depends()],
        _admin: User = Depends(admin_user),
        session: Session = Depends(get_session),
    ):
        await run_in_threadpool(
            importer.candidates.remove_expired,
            app.state.import_candidate_ttl_seconds,
        )
        draft = get_draft_or_404(draft_id, session)
        return await importer.preview(session, draft, form, _admin.id)

    @app.post("/api/input-drafts/{draft_id}/import-apply")
    def apply_position_draft_import(
        draft_id: int,
        payload: ImportApplyPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        importer.candidates.remove_expired(app.state.import_candidate_ttl_seconds)
        draft = get_draft_or_404(draft_id, session)
        return importer.apply(session, draft, payload, admin.id)
