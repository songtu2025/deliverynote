"""提供自营仓异常的采购依据与本次分配明细，不修改批次结果。"""

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from ..processing.keys import _normalize_position_text as key
from .dependencies import RequestDependencies
from .models import Batch, BatchFile, ExceptionRecord, SelfOperatedBatch, User
from .purchase_snapshot import snapshot_document


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

    @app.get("/api/exceptions/{exception_id}/inbound-allocation", response_model=None)
    def inbound_allocation(
        exception_id: int,
        _user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, Any]:
        exception, source, batch, profile = _load_source(session, exception_id)
        items = [
            {
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
            }
            for index, row in enumerate(source.import_rows or [])
            if key(row.get("SKU")) == key(exception.sku)
            and key(row.get("平台站点")) == key(exception.full_site)
        ]
        return {
            "supplier_name": source.supplier_name,
            "supplier_code": source.supplier_code,
            "batch_updated_at": batch.updated_at.isoformat(),
            "history_captured_at": (profile.receipt_snapshot or {}).get("captured_at"),
            "items": items,
        }
