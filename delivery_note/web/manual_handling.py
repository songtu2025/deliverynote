"""保存自营仓人工输入，计算重排保留累计实收核对依据。"""

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .exception_transfer_state import (
    remaining_quantity_expression,
    require_no_transfer_links,
)
from .models import Batch, BatchFile, ExceptionRecord, Job, SelfOperatedBatch
from .receipt_state import require_receipts
from .compute_state import clear_compute_results


def replace_input(
    profile: SelfOperatedBatch,
    section: str,
    identity: dict[str, Any],
    values: dict[str, Any],
    user_id: int,
) -> None:
    entries = [
        entry
        for entry in (profile.manual_handling or {}).get(section, [])
        if any(entry[key] != value for key, value in identity.items())
    ]
    if values["quantity"]:
        entries.append(
            {
                **identity,
                **values,
                "created_by": user_id,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
        )
    profile.manual_handling = {**(profile.manual_handling or {}), section: entries}


def recompute_disabled_reason(session: Session, batch: Batch) -> str | None:
    if batch.status not in {"succeeded", "failed"}:
        return "批次尚未计算成功或当前状态不可重算"
    if session.scalar(
        select(Job.id).where(
            Job.batch_id == batch.id, Job.status.in_(("queued", "running"))
        )
    ):
        return "后台任务进行中，请完成后再修改输入"
    try:
        require_no_transfer_links(session, [batch.id])
    except HTTPException:
        return "批次已有转交记录，请先处理超收再转交"
    return None


def prepare_recompute(session: Session, batch: Batch) -> None:
    """只清计算和导出，不修改实收快照、站点选择或核对结果。"""
    reason = recompute_disabled_reason(session, batch)
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    require_receipts(session, batch)
    sources = session.scalars(
        select(BatchFile).where(BatchFile.batch_id == batch.id)
    ).all()
    clear_compute_results(session, [source.id for source in sources])
    for source in sources:
        source.import_rows = []
        source.result_path = None
        source.delivery_total = source.import_total = source.manual_total = 0
    for job in session.scalars(select(Job).where(Job.batch_id == batch.id)):
        if job.kind in {"compute", "export"}:
            job.status = "stale"
            job.output_path = None
            job.attempts = 0
    batch.zip_path = None
    batch.error_message = None


def save_offline(
    session: Session, batch: Batch, record: ExceptionRecord, quantity: int, note: str
) -> None:
    if batch.status != "succeeded":
        raise HTTPException(status_code=409, detail="批次尚未计算成功")
    export = session.scalar(
        select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
    )
    if export and export.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="导出任务运行期间不可修改线下处理")
    # 替换已有处理量时，当前线下处理量先释放；条件更新同时防止并发超量。
    capacity = remaining_quantity_expression() + ExceptionRecord.offline_quantity
    changed = session.execute(
        update(ExceptionRecord)
        .where(ExceptionRecord.id == record.id, capacity >= quantity)
        .values(offline_quantity=quantity, offline_note=note if quantity else "")
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise HTTPException(
            status_code=400, detail="线下处理数量超过剩余可处理量，请刷新后重试"
        )
    session.refresh(record)
    remaining = session.scalar(
        select(remaining_quantity_expression()).where(ExceptionRecord.id == record.id)
    )
    record.status = "resolved" if remaining == 0 else "pending"


def apply_offline_inputs(
    record: ExceptionRecord, entries: list[dict[str, Any]]
) -> None:
    """重算按来源、SKU 和完整站点套用，旧输入保留且不扩大新待处理量。"""
    entry = next(
        (
            item
            for item in entries
            if (item["batch_file_id"], item["sku"], item["full_site"])
            == (record.batch_file_id, record.sku, record.full_site)
        ),
        None,
    )
    if entry is not None:
        record.offline_quantity = min(entry["quantity"], record.manual_quantity)
        record.offline_note = entry["note"]
        record.status = (
            "resolved"
            if record.offline_quantity == record.manual_quantity
            else "pending"
        )
