"""读取交货批次的转交来源，不影响批次列表查询。"""

from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Batch, BatchFile, ExceptionRecord, ExceptionTransfer


class TransferSource(TypedDict):
    batch_id: int
    batch_name: str
    record_count: int
    quantity: int
    file_ids: list[int]


def batch_transfer_sources(session: Session, batch_id: int) -> list[TransferSource]:
    query = (
        select(Batch.id, Batch.name, ExceptionTransfer)
        .join(BatchFile, BatchFile.batch_id == Batch.id)
        .join(ExceptionRecord, ExceptionRecord.batch_file_id == BatchFile.id)
        .join(ExceptionTransfer, ExceptionTransfer.exception_id == ExceptionRecord.id)
        .where(ExceptionTransfer.target_batch_id == batch_id)
        .order_by(Batch.id, ExceptionTransfer.id)
    )
    sources: dict[int, TransferSource] = {}
    for source_id, name, transfer in session.execute(query):
        source = sources.setdefault(
            source_id,
            {
                "batch_id": source_id,
                "batch_name": name,
                "record_count": 0,
                "quantity": 0,
                "file_ids": [],
            },
        )
        source["record_count"] += 1
        source["quantity"] += transfer.quantity
        if transfer.target_file_id not in source["file_ids"]:
            source["file_ids"].append(transfer.target_file_id)
    return list(sources.values())
