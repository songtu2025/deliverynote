from typing import MutableMapping

import pandas as pd

from .processing.allocation import DeliveryAllocator
from .processing.delivery_sites import resolve_delivery_sites


from .processing.models import (
    IMPORT_COLUMNS,
    RESULT_EXCEPTION_COLUMNS,
    BatchResult,
    OverreceiptAllowance,
    OverreceiptKey,
    _require_columns,
)
from .processing.purchase_balances import (
    PurchaseBalanceLedger,
    build_purchase_balance_ledger,
)


def process_data(
    delivery_lines: pd.DataFrame,
    product_info: pd.DataFrame,
    purchase_rows: pd.DataFrame,
    supplier_name: str,
    supplier_code: str | None = None,
    overreceipt_allowances: MutableMapping[OverreceiptKey, OverreceiptAllowance]
    | None = None,
    *,
    _purchase_ledger: PurchaseBalanceLedger | None = None,
) -> BatchResult:
    """完成产品映射、采购需求汇总和交货数量分配。"""
    supplier_code = supplier_code or supplier_name
    _require_columns(delivery_lines, {"SKU", "原始站点", "交货量"}, "交货明细")
    _require_columns(
        product_info, {"SKU", "店铺/站点", "品类A", "锁仓MKSU"}, "产品信息"
    )
    _require_columns(
        purchase_rows,
        {"单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"},
        "采购需求",
    )

    delivery = resolve_delivery_sites(delivery_lines, product_info)

    purchase_ledger = _purchase_ledger
    if purchase_ledger is None:
        purchase_ledger = build_purchase_balance_ledger(purchase_rows)

    allocator = DeliveryAllocator(
        supplier_name, supplier_code, purchase_ledger, overreceipt_allowances
    )
    for _, delivery_row in delivery.iterrows():
        allocator.allocate(delivery_row)

    import_frame = pd.DataFrame(allocator.import_rows, columns=IMPORT_COLUMNS)
    exception_frame = pd.DataFrame(
        allocator.exceptions, columns=RESULT_EXCEPTION_COLUMNS
    )
    delivery_total = int(delivery["交货量"].sum())
    import_total = (
        int(import_frame["*本次交货量"].sum()) if not import_frame.empty else 0
    )
    manual_total = (
        int(exception_frame["人工处理量"].sum()) if not exception_frame.empty else 0
    )
    if delivery_total != import_total + manual_total:
        raise RuntimeError("数量守恒校验失败")

    return BatchResult(
        import_rows=import_frame,
        exception_rows=exception_frame,
        delivery_total=delivery_total,
        import_total=import_total,
        manual_total=manual_total,
    )
