from collections.abc import Hashable
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from ..excel_io import read_position_workbook
from ..processing.models import POSITION_SOURCE_COLUMNS
from ..inspection.positions import (
    PositionIssue,
    position_change_warnings,
    validate_position_frame,
)
from .models import AuditLog, InputDraft, InputVersion, PositionDraftRow, utcnow


ROW_FIELDS = (
    "store_site",
    "jiaji_sku",
    "msku",
    "scale_position",
    "stocking_position",
)
FIELD_TO_COLUMN = dict(zip(ROW_FIELDS, POSITION_SOURCE_COLUMNS))
IDENTITY_FIELDS = ROW_FIELDS[:3]
_PENDING_PUBLISH_KEY = "position_draft_pending_publish"
POSITION_FRAME_CACHE_SESSION_KEY = "position_frame_cache"
BASE_VERSION_CHANGED_DETAIL = "当前启用的库位版本已变化，请放弃当前草稿后重新开始"
DRAFT_REVISION_CONFLICT_CODE = "draft_revision_conflict"
DRAFT_BASE_VERSION_CHANGED_CODE = "draft_base_version_changed"


class DraftConflictError(Exception):
    def __init__(
        self,
        message: str = "",
        *,
        code: str = DRAFT_REVISION_CONFLICT_CODE,
    ) -> None:
        super().__init__(message)
        self.code = code


class DuplicateInputVersionNameError(ValueError):
    pass


def locked_editing_position_draft(session: Session) -> InputDraft | None:
    """按版本 ID 顺序加锁后读取编辑中的库位草稿，不提交事务。"""
    list(
        session.scalars(
            select(InputVersion.id)
            .where(InputVersion.kind == "position")
            .order_by(InputVersion.id)
            .with_for_update()
        )
    )
    return session.scalar(
        select(InputDraft)
        .where(InputDraft.kind == "position", InputDraft.status == "editing")
        .with_for_update()
    )


def require_revision(draft: InputDraft, expected_revision: int) -> None:
    if draft.status != "editing" or draft.revision != expected_revision:
        raise DraftConflictError


def touch_draft(draft: InputDraft, user_id: int) -> None:
    draft.revision += 1
    draft.updated_by = user_id
    draft.updated_at = utcnow()


def _flush_revision(session: Session) -> None:
    try:
        session.flush()
    except StaleDataError as error:
        raise DraftConflictError from error


def _audit(
    session: Session,
    user_id: int,
    action: str,
    draft_id: int,
    details: dict[str, object] | None = None,
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


def _record_values(record: Mapping[Hashable, Any]) -> dict[str, str]:
    return {
        field: _text(record.get(column, ""))
        for field, column in FIELD_TO_COLUMN.items()
    }


def _row_values(row: PositionDraftRow) -> dict[str, str]:
    return {field: _text(getattr(row, field)) for field in ROW_FIELDS}


def _identity(values: Mapping[str, str]) -> tuple[str, str, str]:
    site, sku, msku = (
        _text(values[field]).strip().upper() for field in IDENTITY_FIELDS
    )
    return site, sku, msku


def _signature(values: Mapping[str, str]) -> tuple[str, ...]:
    identity = _identity(values)
    other_values = tuple(_text(values[field]) for field in ROW_FIELDS[3:])
    return (*identity, *other_values)


def _version_frame(session: Session, version: InputVersion) -> pd.DataFrame:
    cache = session.info.get(POSITION_FRAME_CACHE_SESSION_KEY)
    path = Path(version.storage_path)
    if cache is None:
        return read_position_workbook(path)
    return cache.get(version.id, path, loader=read_position_workbook)


def load_base_frame(session: Session, draft: InputDraft) -> pd.DataFrame:
    """读取草稿锁定的不可变基础版本，并复用当前应用的有界缓存。"""

    version = session.get(InputVersion, draft.base_version_id)
    if version is None:
        raise ValueError("草稿的基础版本不存在")
    return _version_frame(session, version)


def position_frame(rows: list[PositionDraftRow]) -> pd.DataFrame:
    """将未删除的草稿行转换为统一的库位资料字段。"""
    records = [
        {FIELD_TO_COLUMN[field]: getattr(row, field) for field in ROW_FIELDS}
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
) -> PositionDraftRow:
    return PositionDraftRow(
        draft_id=draft_id,
        row_order=row_order,
        base_row_number=base_row_number,
        change_type=change_type,
        deleted=change_type == "deleted",
        **{field: _text(values.get(field, "")) for field in ROW_FIELDS},
    )


def list_draft_rows(session: Session, draft_id: int) -> list[PositionDraftRow]:
    return list(
        session.scalars(
            select(PositionDraftRow)
            .where(PositionDraftRow.draft_id == draft_id)
            .order_by(PositionDraftRow.row_order, PositionDraftRow.id)
        )
    )


def validate_draft(session: Session, draft: InputDraft) -> list[PositionIssue]:
    frame = position_frame(list_draft_rows(session, draft.id))
    return [
        *validate_position_frame(frame),
        *position_change_warnings(load_base_frame(session, draft), frame),
    ]
