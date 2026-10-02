from __future__ import annotations

from typing import Any, cast

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..web.models import BatchFile, ExceptionRecord, SplitRecord


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


def update_compute_source(
    session: Session,
    batch_id: int,
    payload: dict[str, Any],
    document_note: str,
) -> BatchFile:
    """保存两种计算共有的来源统计，并返回各自待处理记录的关联文件。"""
    source = session.get(BatchFile, payload["source_id"])
    if source is None or source.batch_id != batch_id:
        raise RuntimeError("批次来源文件已变化")
    source.supplier_name = payload["supplier"].name
    source.supplier_code = payload["supplier"].code
    source.document_note = document_note
    source.delivery_total = payload["delivery_total"]
    source.import_total = payload["import_total"]
    source.manual_total = payload["manual_total"]
    source.import_rows = payload["import_rows"]
    source.result_path = None
    return source
