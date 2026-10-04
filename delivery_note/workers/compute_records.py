from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..web.models import Batch, BatchFile, ExceptionRecord, Job, SplitRecord
from .leases import JobContext, LostJobLeaseError


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


def load_owned_compute(
    session: Session, context: JobContext, batch_id: int
) -> tuple[Job, Batch]:
    """在保存计算结果的事务中核验当前任务租约。"""
    job = session.scalar(select(Job).where(Job.id == context.job_id).with_for_update())
    batch = session.get(Batch, batch_id)
    if (
        job is None
        or batch is None
        or job.status != "running"
        or job.claim_token != context.claim_token
    ):
        raise LostJobLeaseError("计算任务租约已失效")
    return job, batch


def mark_compute_succeeded(job: Job, batch: Batch) -> None:
    """更新计算完成状态；调用方负责审计与提交。"""
    batch.status = "succeeded"
    batch.error_message = None
    batch.zip_path = None
    job.status = "succeeded"
    job.finished_at = datetime.utcnow()
    job.heartbeat_at = job.finished_at
    job.error_message = None
    job.claim_token = None
