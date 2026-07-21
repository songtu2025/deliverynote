from collections import defaultdict, deque
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import pandas as pd
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from delivery_note.excel_io import read_position_workbook
from delivery_note.input_inspection import (
    position_diff,
    validate_position_frame,
    write_position_workbook,
)
from delivery_note.pipeline import POSITION_SOURCE_COLUMNS

from .models import (
    AuditLog,
    InputDraft,
    InputVersion,
    PositionDraftRow,
    utcnow,
)


ROW_FIELDS = (
    "store_site",
    "jiaji_sku",
    "msku",
    "scale_position",
    "stocking_position",
    "ordered_days",
)
FIELD_TO_COLUMN = dict(zip(ROW_FIELDS, POSITION_SOURCE_COLUMNS))
IDENTITY_FIELDS = ROW_FIELDS[:3]
_PENDING_PUBLISH_KEY = "position_draft_pending_publish"


class DraftConflict(Exception):
    pass


def require_revision(draft: InputDraft, expected_revision: int) -> None:
    if draft.status != "editing" or draft.revision != expected_revision:
        raise DraftConflict


def touch_draft(draft: InputDraft, user_id: int) -> None:
    draft.revision += 1
    draft.updated_by = user_id
    draft.updated_at = utcnow()


def _flush_revision(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as error:
        raise DraftConflict from error


def _remove_pending_publish_files(state: dict, *, remove_target: bool) -> None:
    Path(state["temporary_path"]).unlink(missing_ok=True)
    if remove_target and state.get("promoted"):
        Path(state["target_path"]).unlink(missing_ok=True)


@event.listens_for(Session, "before_commit")
def _promote_pending_publish_file(session: Session) -> None:
    state = session.info.get(_PENDING_PUBLISH_KEY)
    if state is None or session.in_nested_transaction():
        return
    state["root_commit_started"] = True
    target_path = Path(state["target_path"])
    if target_path.exists() or target_path.is_symlink():
        raise ValueError("发布目标文件已存在")
    os.link(state["temporary_path"], target_path)
    state["promoted"] = True
    Path(state["temporary_path"]).unlink()


@event.listens_for(Session, "after_commit")
def _mark_root_publish_commit_succeeded(session: Session) -> None:
    state = session.info.get(_PENDING_PUBLISH_KEY)
    if state is not None and state.get("root_commit_started"):
        state["root_commit_succeeded"] = True


@event.listens_for(Session, "after_transaction_end")
def _finish_pending_publish_file(session: Session, transaction) -> None:
    if transaction.parent is not None:
        return
    state = session.info.pop(_PENDING_PUBLISH_KEY, None)
    if state is not None:
        _remove_pending_publish_files(
            state,
            remove_target=not state.get("root_commit_succeeded", False),
        )


def _audit(
    session: Session,
    user_id: int,
    action: str,
    draft_id: int,
    details: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type="input_draft",
            entity_id=str(draft_id),
            details=details or {},
        )
    )


def _text(value: Any) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _record_values(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        field: _text(record.get(column, ""))
        for field, column in FIELD_TO_COLUMN.items()
    }


def _row_values(row: PositionDraftRow) -> dict[str, str]:
    return {field: _text(getattr(row, field)) for field in ROW_FIELDS}


def _identity(values: Mapping[str, str]) -> tuple[str, str, str]:
    return tuple(_text(values[field]).strip().upper() for field in IDENTITY_FIELDS)


def _signature(values: Mapping[str, str]) -> tuple[str, ...]:
    identity = _identity(values)
    other_values = tuple(_text(values[field]) for field in ROW_FIELDS[3:])
    return (*identity, *other_values)


def _base_frame(session: Session, draft: InputDraft) -> pd.DataFrame:
    version = session.get(InputVersion, draft.base_version_id)
    if version is None:
        raise ValueError("草稿的基础版本不存在")
    return read_position_workbook(Path(version.storage_path))


def _frame_from_rows(rows: list[PositionDraftRow]) -> pd.DataFrame:
    records = [
        {
            FIELD_TO_COLUMN[field]: getattr(row, field)
            for field in ROW_FIELDS
        }
        for row in rows
        if not row.deleted
    ]
    return pd.DataFrame(records, columns=POSITION_SOURCE_COLUMNS)


def _make_row(
    *,
    draft_id: int,
    row_order: int,
    values: Mapping[str, str],
    base_row_number: int | None,
    change_type: str,
    deleted: bool = False,
) -> PositionDraftRow:
    return PositionDraftRow(
        draft_id=draft_id,
        row_order=row_order,
        base_row_number=base_row_number,
        change_type=change_type,
        deleted=deleted,
        **{field: _text(values.get(field, "")) for field in ROW_FIELDS},
    )


def create_or_resume_draft(
    session: Session,
    version: InputVersion,
    user_id: int,
) -> InputDraft:
    existing = session.scalar(
        select(InputDraft)
        .where(
            InputDraft.kind == version.kind,
            InputDraft.status == "editing",
        )
        .with_for_update()
    )
    if existing is not None:
        return existing
    if version.kind != "position" or not version.active:
        raise ValueError("只能从当前启用的库位版本创建草稿")

    try:
        with session.begin_nested():
            draft = InputDraft(
                kind="position",
                base_version_id=version.id,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(draft)
            session.flush()

            frame = read_position_workbook(Path(version.storage_path))
            for row_order, record in enumerate(frame.to_dict("records"), start=1):
                session.add(
                    _make_row(
                        draft_id=draft.id,
                        row_order=row_order,
                        values=_record_values(record),
                        base_row_number=row_order + 1,
                        change_type="unchanged",
                    )
                )
            _audit(
                session,
                user_id,
                "create_input_draft",
                draft.id,
                {"base_version_id": version.id},
            )
            session.flush()
    except IntegrityError as error:
        winner = session.scalar(
            select(InputDraft).where(
                InputDraft.kind == version.kind,
                InputDraft.status == "editing",
            )
        )
        if winner is None:
            raise DraftConflict from error
        return winner
    return draft


def list_draft_rows(session: Session, draft_id: int) -> list[PositionDraftRow]:
    return list(
        session.scalars(
            select(PositionDraftRow)
            .where(PositionDraftRow.draft_id == draft_id)
            .order_by(PositionDraftRow.row_order, PositionDraftRow.id)
        )
    )


def _base_values_for_row(
    session: Session,
    draft: InputDraft,
    row: PositionDraftRow,
) -> dict[str, str]:
    if row.base_row_number is None:
        return {}
    frame = _base_frame(session, draft)
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
        row = session.get(PositionDraftRow, row_id)
        if row is None or row.draft_id != draft.id:
            raise ValueError("草稿行不存在")
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


def replace_draft_from_frame(
    session: Session,
    draft: InputDraft,
    expected_revision: int,
    user_id: int,
    frame: pd.DataFrame,
) -> dict[str, int]:
    require_revision(draft, expected_revision)
    candidate = frame[POSITION_SOURCE_COLUMNS].copy()
    current = _frame_from_rows(list_draft_rows(session, draft.id))
    base = _base_frame(session, draft)
    diff = position_diff(current, candidate)

    base_rows: dict[tuple[str, str, str], deque[tuple[int, dict[str, str]]]] = (
        defaultdict(deque)
    )
    for offset, record in enumerate(base.to_dict("records"), start=2):
        values = _record_values(record)
        base_rows[_identity(values)].append((offset, values))

    replacement_rows: list[PositionDraftRow] = []
    for row_order, record in enumerate(candidate.to_dict("records"), start=1):
        values = _record_values(record)
        matches = base_rows[_identity(values)]
        if matches:
            base_row_number, base_values = matches.popleft()
            change_type = (
                "unchanged"
                if _signature(values) == _signature(base_values)
                else "modified"
            )
        else:
            base_row_number = None
            change_type = "added"
        replacement_rows.append(
            _make_row(
                draft_id=draft.id,
                row_order=row_order,
                values=values,
                base_row_number=base_row_number,
                change_type=change_type,
            )
        )

    next_order = len(replacement_rows) + 1
    deleted_base_rows = sorted(
        (item for matches in base_rows.values() for item in matches),
        key=lambda item: item[0],
    )
    for base_row_number, values in deleted_base_rows:
        replacement_rows.append(
            _make_row(
                draft_id=draft.id,
                row_order=next_order,
                values=values,
                base_row_number=base_row_number,
                change_type="deleted",
                deleted=True,
            )
        )
        next_order += 1

    session.execute(
        delete(PositionDraftRow).where(PositionDraftRow.draft_id == draft.id)
    )
    session.add_all(replacement_rows)
    touch_draft(draft, user_id)
    _audit(session, user_id, "import_input_draft", draft.id, {"diff": diff})
    _flush_revision(session)
    return diff


def validate_draft(session: Session, draft: InputDraft) -> list[dict]:
    return validate_position_frame(_frame_from_rows(list_draft_rows(session, draft.id)))


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
    require_revision(draft, expected_revision)
    issues = validate_draft(session, draft)
    if any(issue["severity"] == "error" for issue in issues):
        raise ValueError("草稿仍有错误，不能发布")
    if not confirm_warnings and any(
        issue["severity"] == "warning" for issue in issues
    ):
        raise ValueError("草稿仍有警告，请确认警告后发布")
    if session.scalar(
        select(InputVersion.id).where(
            InputVersion.kind == "position",
            InputVersion.name == name,
        )
    ) is not None:
        raise ValueError("版本名称已存在")

    path = Path(storage_path)
    resolved_path = path.resolve()
    registered_paths = {
        Path(registered_path).resolve()
        for registered_path in session.scalars(select(InputVersion.storage_path))
    }
    if resolved_path in registered_paths:
        raise ValueError("发布目标不能使用已注册的正式版本文件")
    if path.exists() or path.is_symlink():
        raise ValueError("发布目标文件已存在")
    if session.info.get(_PENDING_PUBLISH_KEY) is not None:
        raise ValueError("当前事务已有待提交的发布文件")

    temporary_path = path.with_name(
        f".{path.name}.{uuid4().hex}.tmp.xlsx"
    )
    try:
        write_position_workbook(
            temporary_path,
            _frame_from_rows(list_draft_rows(session, draft.id)),
        )
        for current in session.scalars(
            select(InputVersion)
            .where(InputVersion.kind == "position")
            .with_for_update()
        ):
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
        session.info[_PENDING_PUBLISH_KEY] = {
            "temporary_path": str(temporary_path),
            "target_path": str(path),
            "promoted": False,
            "root_commit_started": False,
            "root_commit_succeeded": False,
        }
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
