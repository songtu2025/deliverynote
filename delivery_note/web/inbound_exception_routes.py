"""提供自营仓异常的采购依据与本次分配明细，不修改批次结果。"""

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from ..processing.keys import _normalize_position_text as key
from .dependencies import RequestDependencies
from .models import Batch, BatchFile, ExceptionRecord, SelfOperatedBatch, User
from .purchase_snapshot import snapshot_document
from .manual_handling import recompute_disabled_reason
from .targeted_allowances import (
    allocation_allowances,
    allocation_extra,
    allocation_rows,
    pending_capacity,
)


def _load_source(
    session: Session, exception_id: int
) -> tuple[ExceptionRecord, BatchFile, Batch, SelfOperatedBatch]:
    exception = session.get(ExceptionRecord, exception_id)
    source = session.get(BatchFile, exception.batch_file_id) if exception else None
    batch = session.get(Batch, source.batch_id) if source else None
    profile = session.get(SelfOperatedBatch, batch.id) if batch else None
    if exception is None or source is None or batch is None or profile is None:
        raise HTTPException(status_code=404, detail="自营仓待处理记录不存在")
    if batch.status != "succeeded":
        raise HTTPException(
            status_code=409, detail="批次尚未计算成功，请完成计算后查看"
        )
    return exception, source, batch, profile


def load_purchase_options(
    session: Session,
    exception: ExceptionRecord,
    source: BatchFile,
    batch: Batch,
    storage: Path,
) -> dict[str, Any]:
    """从整批快照提取同一供应商和 SKU 的未交采购。"""
    if not source.supplier_code:
        raise HTTPException(
            status_code=409, detail="来源文件缺少供应商编码，无法精确查询采购数据"
        )
    state, snapshot = snapshot_document(session, batch, storage)
    if state != "ready":
        raise HTTPException(status_code=409, detail="请先加载或刷新整批采购数据")
    rows = [
        row
        for row in snapshot["items"]
        if row["supplier_code"] == key(source.supplier_code)
        and row["sku"] == key(exception.sku)
    ]
    return {"items": rows, "queried_at": snapshot["completed_at"]}


def _load_allocation_source(
    session: Session, exception_id: int, file_id: int | None, sku: str, full_site: str
) -> tuple[ExceptionRecord, BatchFile, Batch, SelfOperatedBatch]:
    if file_id is None:
        return _load_source(session, exception_id)
    source = session.get(BatchFile, file_id)
    batch = session.get(Batch, source.batch_id) if source else None
    profile = session.get(SelfOperatedBatch, batch.id) if batch else None
    if source is None or batch is None or profile is None:
        raise HTTPException(status_code=404, detail="自营仓来源文件不存在")
    if batch.status != "succeeded":
        raise HTTPException(
            status_code=409, detail="批次尚未计算成功，请完成计算后查看"
        )
    return ExceptionRecord(sku=sku, full_site=full_site), source, batch, profile


def register_inbound_exception_routes(
    app: FastAPI, dependencies: RequestDependencies, storage: Path
) -> None:
    @app.get("/api/exceptions/{exception_id}/purchase-options", response_model=None)
    def purchase_options(
        exception_id: int,
        _user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, Any]:
        exception, source, batch, _ = _load_source(session, exception_id)
        return load_purchase_options(session, exception, source, batch, storage)

    @app.get("/api/exceptions/{exception_id}/inbound-allocation", response_model=None)
    def inbound_allocation(
        exception_id: int,
        _user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
        file_id: int | None = None,
        sku: str = "",
        full_site: str = "",
    ) -> dict[str, Any]:
        exception, source, batch, profile = _load_allocation_source(
            session, exception_id, file_id, sku, full_site
        )
        allowances = allocation_allowances(session, profile, source, exception)
        items = [
            {
                **allocation_extra(row, allowances["saved_allowances"]),
                "id": str(index),
                "po_code": row.get("关联采购单"),
                "delivery_no": row.get("关联交货单/调拨单"),
                "inbound_no": row.get("入库单号"),
                "site": row.get("平台站点"),
                "warehouse": row.get("入库仓"),
                "history_quantity": row.get("已入库"),
                "normal_quantity": row.get("正常分配数量"),
                "overreceipt_quantity": row.get("规则内超收数量"),
                "current_quantity": row.get("本次入库"),
                "max_receive_quantity": row.get("最大可收货"),
                "received_quantity": row.get("已收货"),
                "targeted_quantity": row.get("追加超收数量", 0),
            }
            for index, row in enumerate(
                allocation_rows(source, exception.sku, exception.full_site)
            )
        ]
        return {
            **allowances,
            "batch_id": batch.id,
            "remaining_quantity": pending_capacity(
                session, source, exception.sku, exception.full_site
            ),
            "recompute_disabled_reason": recompute_disabled_reason(session, batch),
            "supplier_name": source.supplier_name,
            "supplier_code": source.supplier_code,
            "batch_updated_at": batch.updated_at.isoformat(),
            "history_captured_at": (profile.receipt_snapshot or {}).get("captured_at"),
            "items": items,
        }
