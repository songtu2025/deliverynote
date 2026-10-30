"""读取批次采购快照及其输入范围，不触发外部采集。"""

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Batch, BatchFile, Job, SelfOperatedBatch
from .serializers import job_json

PURCHASE_SNAPSHOT_KIND = "purchase_snapshot"
SNAPSHOT_PAGE_SIZE = 200
PURCHASE_SNAPSHOT_ERROR = (
    "整批采购数据加载失败，请重试；持续失败时请联系管理员检查来源文件和积加接口"
)


def require_snapshot_batch(session: Session, batch: Batch) -> None:
    if session.get(SelfOperatedBatch, batch.id) is None:
        raise HTTPException(status_code=404, detail="自营仓批次不存在")
    if batch.status != "succeeded":
        raise HTTPException(status_code=409, detail="请完成批次计算后加载整批采购数据")


def snapshot_sources(session: Session, batch: Batch) -> tuple[list[BatchFile], str]:
    sources = list(
        session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.id)
        )
    )
    identity = [
        batch.supplier_version_id,
        [
            (source.id, source.storage_path, source.original_name, source.supplier_code)
            for source in sources
        ],
    ]
    signature = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False).encode()
    ).hexdigest()
    return sources, signature


def snapshot_job(session: Session, batch_id: int) -> Job | None:
    return session.scalar(
        select(Job).where(Job.batch_id == batch_id, Job.kind == PURCHASE_SNAPSHOT_KIND)
    )


def snapshot_document(
    session: Session, batch: Batch, storage: Path
) -> tuple[str, dict[str, Any]]:
    job = snapshot_job(session, batch.id)
    if job is None or not job.output_path:
        return "missing", {}
    path = Path(job.output_path).resolve()
    directory = (storage / "batches" / str(batch.id) / "purchase-snapshots").resolve()
    if not path.is_relative_to(directory):
        return "unavailable", {}
    try:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unavailable", {}
    if document.get("schema_version") != 1:
        return "unavailable", {}
    _, signature = snapshot_sources(session, batch)
    current = job.status != "stale" and document["source_signature"] == signature
    return "ready" if current else "stale", document


def snapshot_view(
    session: Session,
    batch: Batch,
    storage: Path,
    *,
    page: tuple[int, int] = (0, SNAPSHOT_PAGE_SIZE),
    snapshot_id: str = "",
) -> dict[str, Any]:
    offset, limit = page
    state, document = snapshot_document(session, batch, storage)
    if snapshot_id and snapshot_id != document.get("snapshot_id"):
        raise HTTPException(
            status_code=409, detail="采购快照已更新，请重新读取整批数据"
        )
    job = snapshot_job(session, batch.id)
    items = document.get("items", []) if state == "ready" else []
    return {
        "state": state,
        "job": job_json(job) if job else None,
        "snapshot_id": document.get("snapshot_id"),
        "started_at": document.get("started_at"),
        "completed_at": document.get("completed_at"),
        "supplier_count": document.get("supplier_count", 0),
        "sku_count": document.get("sku_count", 0),
        "total": len(items),
        "items": items[offset : offset + limit],
    }
