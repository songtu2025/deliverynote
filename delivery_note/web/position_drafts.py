from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..inspection.workbooks import write_position_workbook
from .models import InputDraft, InputVersion, PositionDraftRow
from .position_draft_files import stage_publication_files, validate_publication_target
from .position_draft_state import (
    list_draft_rows,
    BASE_VERSION_CHANGED_DETAIL,
    DRAFT_BASE_VERSION_CHANGED_CODE,
    DraftConflictError,
    ROW_FIELDS,
    _audit,
    _flush_revision,
    _make_row,
    _record_values,
    _row_values,
    _signature,
    _text,
    load_base_frame,
    position_frame,
    require_revision,
    touch_draft,
)


def _base_values_for_row(
    session: Session,
    draft: InputDraft,
    row: PositionDraftRow,
) -> dict[str, str]:
    if row.base_row_number is None:
        return {}
    frame = load_base_frame(session, draft)
    frame_offset = row.base_row_number - 2
    if frame_offset < 0 or frame_offset >= len(frame):
        raise ValueError("草稿来源行不存在")
    return _record_values(frame.iloc[frame_offset].to_dict())


def mutate_draft_row(
    session: Session,
    draft: InputDraft,
    expected_revision: int,
    user_id: int,
    values: Mapping[str, Any],
    *,
    row_id: int | None = None,
    delete: bool = False,
) -> PositionDraftRow:
    require_revision(draft, expected_revision)

    if row_id is None:
        if delete:
            raise ValueError("新增行不能在创建时删除")
        last_order = session.scalar(
            select(func.max(PositionDraftRow.row_order)).where(
                PositionDraftRow.draft_id == draft.id
            )
        )
        row = _make_row(
            draft_id=draft.id,
            row_order=(last_order or 0) + 1,
            values={field: _text(values.get(field, "")) for field in ROW_FIELDS},
            base_row_number=None,
            change_type="added",
        )
        session.add(row)
        session.flush()
    else:
        existing_row = session.get(PositionDraftRow, row_id)
        if existing_row is None or existing_row.draft_id != draft.id:
            raise ValueError("草稿行不存在")
        row = existing_row
        if delete:
            if row.base_row_number is None:
                session.delete(row)
            else:
                row.deleted = True
                row.change_type = "deleted"
        else:
            for field in ROW_FIELDS:
                if field in values:
                    setattr(row, field, _text(values[field]))
            row.deleted = False
            if row.base_row_number is None:
                row.change_type = "added"
            else:
                base_values = _base_values_for_row(session, draft, row)
                row.change_type = (
                    "unchanged"
                    if _signature(_row_values(row)) == _signature(base_values)
                    else "modified"
                )

    touch_draft(draft, user_id)
    _flush_revision(session)
    return row


def delete_draft_rows(
    session: Session,
    draft: InputDraft,
    expected_revision: int,
    user_id: int,
    rows: list[PositionDraftRow],
) -> None:
    """在一次草稿修订中删除多条记录。"""

    require_revision(draft, expected_revision)
    if any(row.draft_id != draft.id for row in rows):
        raise ValueError("草稿行不存在")
    for row in rows:
        if row.base_row_number is None:
            session.delete(row)
        else:
            row.deleted = True
            row.change_type = "deleted"
    touch_draft(draft, user_id)
    _flush_revision(session)


def publish_draft(
    session: Session,
    draft: InputDraft,
    expected_revision: int,
    user_id: int,
    *,
    name: str,
    storage_path: Path,
    confirm_warnings: bool = False,
    original_name: str | None = None,
) -> InputVersion:
    if session.in_nested_transaction():
        raise ValueError("不能在嵌套事务中发布")
    require_revision(draft, expected_revision)
    path = validate_publication_target(
        session, draft, name, storage_path, confirm_warnings
    )

    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp.xlsx")
    try:
        write_position_workbook(
            temporary_path,
            position_frame(list_draft_rows(session, draft.id)),
        )
        position_versions = list(
            session.scalars(
                select(InputVersion)
                .where(InputVersion.kind == "position")
                .order_by(InputVersion.id)
                .with_for_update()
            )
        )
        active_version_ids = [
            current.id for current in position_versions if current.active
        ]
        if active_version_ids != [draft.base_version_id]:
            raise DraftConflictError(
                BASE_VERSION_CHANGED_DETAIL,
                code=DRAFT_BASE_VERSION_CHANGED_CODE,
            )
        for current in position_versions:
            current.active = False
        session.flush()
        version = InputVersion(
            kind="position",
            name=name,
            original_name=original_name or path.name,
            storage_path=str(path),
            active=True,
            created_by=user_id,
        )
        session.add(version)
        session.flush()
        draft.status = "published"
        touch_draft(draft, user_id)
        _audit(
            session,
            user_id,
            "publish_input_draft",
            draft.id,
            {"version_id": version.id},
        )
        _flush_revision(session)
        stage_publication_files(session, temporary_path, path)
        return version
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def discard_draft(
    session: Session,
    draft: InputDraft,
    expected_revision: int,
    user_id: int,
) -> InputDraft:
    require_revision(draft, expected_revision)
    draft.status = "discarded"
    touch_draft(draft, user_id)
    _audit(session, user_id, "discard_input_draft", draft.id)
    _flush_revision(session)
    return draft
