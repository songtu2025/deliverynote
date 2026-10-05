"""库位草稿行的增删改入口。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .errors import commit_draft_changes
from .models import PositionDraftRow, User
from .position_draft_read import position_row_json
from .position_drafts import delete_draft_rows, mutate_draft_row
from .position_import_candidates import PositionImportCandidates
from .schemas import BulkDeletePayload, DraftMutationPayload, PositionRowPayload


def register_position_draft_row_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    import_candidates_state: PositionImportCandidates,
) -> None:
    get_session = dependencies.get_session
    admin_user = dependencies.admin_user
    get_draft_or_404 = dependencies.get_draft_or_404

    @app.post(
        "/api/input-drafts/{draft_id}/rows",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def create_position_draft_row(
        draft_id: int,
        payload: PositionRowPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        draft = get_draft_or_404(draft_id, session)
        with commit_draft_changes(session):
            row = mutate_draft_row(
                session,
                draft,
                payload.revision,
                admin.id,
                payload.model_dump(exclude={"revision"}),
            )
        session.refresh(draft)
        session.refresh(row)
        import_candidates_state.remove_draft(draft.id)
        return {"row": position_row_json(row), "revision": draft.revision}

    @app.put("/api/input-drafts/{draft_id}/rows/{row_id}", response_model=None)
    def update_position_draft_row(
        draft_id: int,
        row_id: int,
        payload: PositionRowPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        draft = get_draft_or_404(draft_id, session)
        existing_row = session.get(PositionDraftRow, row_id)
        if existing_row is None or existing_row.draft_id != draft.id:
            raise HTTPException(status_code=404, detail="草稿行不存在")
        with commit_draft_changes(session):
            row = mutate_draft_row(
                session,
                draft,
                payload.revision,
                admin.id,
                payload.model_dump(exclude={"revision"}),
                row_id=row_id,
            )
        session.refresh(draft)
        session.refresh(row)
        import_candidates_state.remove_draft(draft.id)
        return {"row": position_row_json(row), "revision": draft.revision}

    @app.delete("/api/input-drafts/{draft_id}/rows/{row_id}", response_model=None)
    def delete_position_draft_row(
        draft_id: int,
        row_id: int,
        payload: DraftMutationPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        draft = get_draft_or_404(draft_id, session)
        existing_row = session.get(PositionDraftRow, row_id)
        if existing_row is None or existing_row.draft_id != draft.id:
            raise HTTPException(status_code=404, detail="草稿行不存在")
        with commit_draft_changes(session):
            mutate_draft_row(
                session,
                draft,
                payload.revision,
                admin.id,
                {},
                row_id=row_id,
                delete=True,
            )
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return {"row_id": row_id, "revision": draft.revision}

    @app.post("/api/input-drafts/{draft_id}/rows/bulk-delete", response_model=None)
    def bulk_delete_position_draft_rows(
        draft_id: int,
        payload: BulkDeletePayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        draft = get_draft_or_404(draft_id, session)
        if len(payload.row_ids) != len(set(payload.row_ids)):
            raise HTTPException(status_code=400, detail="批量删除行不可重复")
        rows = list(
            session.scalars(
                select(PositionDraftRow).where(
                    PositionDraftRow.draft_id == draft.id,
                    PositionDraftRow.id.in_(payload.row_ids),
                )
            )
        )
        if len(rows) != len(payload.row_ids):
            raise HTTPException(status_code=404, detail="草稿行不存在")
        with commit_draft_changes(session):
            delete_draft_rows(
                session,
                draft,
                payload.revision,
                admin.id,
                rows,
            )
        session.refresh(draft)
        import_candidates_state.remove_draft(draft.id)
        return {"deleted_ids": payload.row_ids, "revision": draft.revision}
