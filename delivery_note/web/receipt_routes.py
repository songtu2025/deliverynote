"""累计实收核对明细、文件级站点选择和显式重新取数。"""

from typing import Annotated, Any
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .batch_views import batch_json
from .models import Batch, BatchFile, SelfOperatedBatch, User
from .dependencies import RequestDependencies
from .receipt_state import invalidate_receipts


class ReceiptSitePayload(BaseModel):
    sku: str
    original_site: str
    full_site: str


def queue_receipt_preflight(
    session: Session, batch: Batch, user: User, queue_job: Callable[..., Any]
) -> dict[str, object]:
    if batch.status not in {"draft", "preflight_ready", "failed"}:
        raise HTTPException(status_code=409, detail="当前批次状态不可预检")
    count = session.scalar(
        select(BatchFile.id).where(BatchFile.batch_id == batch.id).limit(1)
    )
    if count is None:
        raise HTTPException(status_code=400, detail="批次至少需要一个交货文件")
    invalidate_receipts(session, batch)
    queue_job(batch, "prepare", user, session)
    batch.status = "queued"
    session.commit()
    return batch_json(batch, session)


def register_receipt_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    queue_job: Callable[..., Any],
    audit: Callable[..., Any],
) -> None:
    @app.get("/api/batches/{batch_id}/receipts", response_model=None)
    def receipt_rows(
        batch_id: int,
        _user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        issues_only: bool = False,
    ) -> dict[str, Any]:
        dependencies.get_batch_or_404(batch_id, session)
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch_id)
            .order_by(BatchFile.file_order)
        ).all()
        rows = [
            {
                **row,
                "file_id": source.id,
                "filename": source.original_name,
                "supplier": source.supplier_name,
                "delivery_numbers": source.receipt_context["delivery_numbers"],
            }
            for source in sources
            if source.receipt_context
            for row in source.receipt_context["rows"]
            if not issues_only or row["issue"]
        ]
        offset = (page - 1) * page_size
        return {"items": rows[offset : offset + page_size], "total": len(rows)}

    @app.put(
        "/api/batches/{batch_id}/files/{file_id}/receipt-site", response_model=None
    )
    def choose_site(
        batch_id: int,
        file_id: int,
        payload: ReceiptSitePayload,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, object]:
        batch = dependencies.get_editable_batch(batch_id, session, for_update=True)
        source = session.get(BatchFile, file_id)
        if source is None or source.batch_id != batch.id:
            raise HTTPException(status_code=404, detail="质检文件不存在")
        rows = (source.receipt_context or {}).get("rows", [])
        match = next(
            (
                row
                for row in rows
                if row["sku"] == payload.sku
                and row["original_site"] == payload.original_site
            ),
            None,
        )
        if not match or payload.full_site not in match["candidates"]:
            raise HTTPException(status_code=400, detail="所选站点不在该文件候选范围")
        source.receipt_sites = {
            **(source.receipt_sites or {}),
            f"{payload.sku}\t{payload.original_site}": payload.full_site,
        }
        audit(
            session,
            user.id,
            "choose_receipt_site",
            "batch_file",
            file_id,
            payload.model_dump(),
        )
        return queue_receipt_preflight(session, batch, user, queue_job)

    @app.post("/api/batches/{batch_id}/receipts/refresh", response_model=None)
    def refresh_history(
        batch_id: int,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, object]:
        batch = dependencies.get_batch_or_404(batch_id, session, for_update=True)
        if session.get(SelfOperatedBatch, batch.id) is None:
            raise HTTPException(status_code=404, detail="自营仓入库批次不存在")
        invalidate_receipts(session, batch, refresh=True)
        audit(session, user.id, "refresh_receipt_history", "batch", batch.id)
        return queue_receipt_preflight(session, batch, user, queue_job)
