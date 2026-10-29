"""累计实收的输入指纹、失效处理与计算门禁。"""

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Batch, BatchFile, Job, SelfOperatedBatch


def receipt_signature(
    batch: Batch, profile: SelfOperatedBatch, sources: Sequence[BatchFile]
) -> str:
    payload = [
        batch.product_version_id,
        batch.supplier_version_id,
        profile.inbound_storage_path,
        sorted(
            (source.id, source.storage_path, source.original_name) for source in sources
        ),
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def invalidate_receipts(
    session: Session, batch: Batch, *, refresh: bool = False
) -> None:
    from fastapi import HTTPException

    profile = session.get(SelfOperatedBatch, batch.id)
    if profile is None:
        return
    if refresh:
        profile.receipt_snapshot = None
    elif profile.receipt_snapshot:
        profile.receipt_snapshot = {
            key: value
            for key, value in profile.receipt_snapshot.items()
            if key != "summary"
        }
    for source in session.scalars(
        select(BatchFile).where(BatchFile.batch_id == batch.id)
    ):
        source.receipt_context = None
        source.import_rows = []
        source.result_path = None
        source.delivery_total = source.import_total = source.manual_total = 0
    batch.zip_path = None
    batch.error_message = None
    batch.status = "draft"
    for job in session.scalars(select(Job).where(Job.batch_id == batch.id)):
        if job.status in {"queued", "running"}:
            raise HTTPException(
                status_code=409, detail="后台任务进行中，请完成后再修改输入"
            )
        job.status = "stale"


def require_receipts(session: Session, batch: Batch) -> None:
    from fastapi import HTTPException

    profile = session.get(SelfOperatedBatch, batch.id)
    if profile is None:
        return
    sources = session.scalars(
        select(BatchFile).where(BatchFile.batch_id == batch.id)
    ).all()
    snapshot = profile.receipt_snapshot
    if not snapshot or snapshot.get("signature") != receipt_signature(
        batch, profile, sources
    ):
        raise HTTPException(status_code=409, detail="请先预检并获取完整入库历史")
    if any(
        not source.receipt_context or source.receipt_context.get("issue_count")
        for source in sources
    ):
        raise HTTPException(
            status_code=409, detail="累计实收尚有待核对记录，请先解决并重新预检"
        )
