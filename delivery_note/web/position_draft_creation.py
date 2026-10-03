from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import InputDraft, InputVersion, PositionDraftRow
from .position_draft_state import (
    DraftConflictError,
    _audit,
    _record_values,
    _version_frame,
)


def create_or_resume_draft(
    session: Session,
    version: InputVersion,
    user_id: int,
) -> InputDraft:
    if version.kind != "position":
        raise ValueError("只能从当前启用的库位版本创建草稿")
    list(
        session.scalars(
            select(InputVersion.id)
            .where(InputVersion.kind == "position")
            .order_by(InputVersion.id)
            .with_for_update()
        )
    )
    existing = session.scalar(
        select(InputDraft)
        .where(
            InputDraft.kind == "position",
            InputDraft.status == "editing",
        )
        .with_for_update()
    )
    if existing is not None:
        return existing
    active_version_id = session.scalar(
        select(InputVersion.id).where(
            InputVersion.kind == "position",
            InputVersion.active.is_(True),
        )
    )
    if active_version_id is None:
        raise ValueError("只能从当前启用的库位版本创建草稿")
    active_version = session.get(
        InputVersion,
        active_version_id,
        populate_existing=True,
    )
    if active_version is None:
        raise ValueError("只能从当前启用的库位版本创建草稿")

    try:
        with session.begin_nested():
            draft = InputDraft(
                kind="position",
                base_version_id=active_version.id,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(draft)
            session.flush()

            frame = _version_frame(session, active_version)
            row_mappings = []
            for row_order, record in enumerate(frame.to_dict("records"), start=1):
                values = _record_values(record)
                row_mappings.append(
                    {
                        "draft_id": draft.id,
                        "row_order": row_order,
                        "base_row_number": row_order + 1,
                        "change_type": "unchanged",
                        "deleted": False,
                        **values,
                    }
                )
            if row_mappings:
                session.execute(insert(PositionDraftRow), row_mappings)
            _audit(
                session,
                user_id,
                "create_input_draft",
                draft.id,
                {"base_version_id": active_version.id},
            )
            session.flush()
    except IntegrityError as error:
        winner = session.scalar(
            select(InputDraft).where(
                InputDraft.kind == "position",
                InputDraft.status == "editing",
            )
        )
        if winner is None:
            raise DraftConflictError from error
        return winner
    return draft
