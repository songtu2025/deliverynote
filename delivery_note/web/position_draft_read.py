"""库位草稿的只读分析、问题映射和响应字段。"""

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..input_inspection import (
    position_change_warnings,
    position_diff,
    validate_position_frame,
)
from ..pipeline import POSITION_SOURCE_COLUMNS
from .caches import DraftAnalysisCache
from .models import InputDraft, InputVersion, PositionDraftRow
from .position_drafts import FIELD_TO_COLUMN, ROW_FIELDS, load_base_frame
from .serializers import utc_isoformat


def position_row_json(
    row: PositionDraftRow,
    issues: list[dict] | None = None,
) -> dict:
    return {
        "id": row.id,
        "draft_id": row.draft_id,
        "row_order": row.row_order,
        "store_site": row.store_site,
        "jiaji_sku": row.jiaji_sku,
        "msku": row.msku,
        "scale_position": row.scale_position,
        "stocking_position": row.stocking_position,
        "change_type": row.change_type,
        "deleted": row.deleted,
        "issues": issues or [],
    }


def _draft_row_snapshots(session: Session, draft_id: int) -> list[dict]:
    """按稳定顺序加载分析所需标量，避免把整表 ORM 实体放入缓存。"""

    columns = [
        PositionDraftRow.id,
        PositionDraftRow.row_order,
        PositionDraftRow.change_type,
        PositionDraftRow.deleted,
        *(getattr(PositionDraftRow, field) for field in ROW_FIELDS),
    ]
    return [
        dict(row)
        for row in session.execute(
            select(*columns)
            .where(PositionDraftRow.draft_id == draft_id)
            .order_by(PositionDraftRow.row_order, PositionDraftRow.id)
        ).mappings()
    ]


def _snapshot_position_frame(rows: list[dict]) -> pd.DataFrame:
    records = [
        {FIELD_TO_COLUMN[field]: row[field] for field in ROW_FIELDS}
        for row in rows
        if not row["deleted"]
    ]
    return pd.DataFrame(records, columns=POSITION_SOURCE_COLUMNS)


def _position_issue_map(
    rows: list[dict],
    issues: list[dict],
) -> dict[int, list[dict]]:
    active_rows = [row for row in rows if not row["deleted"]]
    by_row_id: dict[int, list[dict]] = {}
    for issue in issues:
        for row_number in issue["row_numbers"]:
            offset = row_number - 2
            if 0 <= offset < len(active_rows):
                by_row_id.setdefault(active_rows[offset]["id"], []).append(issue)
    return by_row_id


def summarize_issues(issues: list[dict]) -> dict:
    error_count = sum(
        max(1, len(issue["row_numbers"]))
        for issue in issues
        if issue["severity"] == "error"
    )
    warning_count = sum(
        max(1, len(issue["row_numbers"]))
        for issue in issues
        if issue["severity"] == "warning"
    )
    return {
        "issues": issues,
        "error_count": error_count,
        "warning_count": warning_count,
        "valid": error_count == 0,
    }


def draft_analysis(
    session: Session,
    draft: InputDraft,
    cache: DraftAnalysisCache,
) -> dict:
    """按草稿修订复用摘要、差异和逐行问题分析。"""

    def load() -> dict:
        rows = _draft_row_snapshots(session, draft.id)
        base_frame = load_base_frame(session, draft)
        current_frame = _snapshot_position_frame(rows)
        validation_issues = validate_position_frame(current_frame)
        issues = [
            *validation_issues,
            *position_change_warnings(base_frame, current_frame),
        ]
        issues_by_row = _position_issue_map(rows, validation_issues)
        return {
            "row_count": sum(not row["deleted"] for row in rows),
            "modified_count": sum(row["change_type"] != "unchanged" for row in rows),
            "diff": position_diff(base_frame, current_frame),
            "issues": issues,
            "issues_by_row": issues_by_row,
            "error_row_ids": tuple(
                row_id
                for row_id, row_issues in issues_by_row.items()
                if any(issue["severity"] == "error" for issue in row_issues)
            ),
        }

    return cache.get(draft.id, draft.revision, load)


def draft_json(
    session: Session,
    draft: InputDraft,
    analysis_cache: DraftAnalysisCache,
) -> dict:
    analysis = draft_analysis(session, draft, analysis_cache)
    base_version = session.get(InputVersion, draft.base_version_id)
    active_version = session.scalar(
        select(InputVersion).where(
            InputVersion.kind == "position",
            InputVersion.active.is_(True),
        )
    )
    issue_summary = summarize_issues(analysis["issues"])
    return {
        "id": draft.id,
        "kind": draft.kind,
        "base_version_id": draft.base_version_id,
        "base_version_name": (
            base_version.name
            if base_version is not None
            else f"版本 #{draft.base_version_id}"
        ),
        "active_version_id": active_version.id if active_version is not None else None,
        "active_version_name": active_version.name
        if active_version is not None
        else None,
        "status": draft.status,
        "revision": draft.revision,
        "created_by": draft.created_by,
        "updated_by": draft.updated_by,
        "created_at": utc_isoformat(draft.created_at),
        "updated_at": utc_isoformat(draft.updated_at),
        "row_count": analysis["row_count"],
        "modified_count": analysis["modified_count"],
        "diff": analysis["diff"],
        **issue_summary,
    }
