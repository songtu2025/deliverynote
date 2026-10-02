from __future__ import annotations

from typing import Any, cast

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..web.models import ExceptionRecord, SplitRecord


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {cast(str, column): _json_value(value) for column, value in record.items()}
        for record in frame.to_dict("records")
    ]


def clear_compute_results(session: Session, payloads: list[dict[str, Any]]) -> None:
    source_ids = [payload["source_id"] for payload in payloads]
    exception_ids = session.scalars(
        select(ExceptionRecord.id).where(ExceptionRecord.batch_file_id.in_(source_ids))
    ).all()
    if exception_ids:
        session.execute(
            delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
        )
        session.execute(
            delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
        )
