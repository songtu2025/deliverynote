from typing import MutableMapping

import pandas as pd

from .exception_reasons import ExceptionReason
from .processing.delivery_sites import resolve_delivery_sites
from .processing.keys import make_overreceipt_key


from .processing.models import (
    IMPORT_COLUMNS,
    RESULT_EXCEPTION_COLUMNS,
    OVERRECEIPT_NOTE_PREFIX,
    BatchResult,
    OverreceiptAllowance,
    OverreceiptKey,
    _require_columns,
)
from .processing.purchase_balances import (
    _PurchaseBalance,
    PurchaseBalanceLedger,
    build_purchase_balance_ledger,
)


def _append_exception(
    exceptions: list[dict],
    delivery_row: pd.Series,
    full_site: str | None,
    destination_warehouse: str | None,
    allocated: int,
    manual: int,
    reason: str,
    *,
    purchase_allocated: int = 0,
    overreceipt_allocated: int = 0,
    overreceipt_remaining: int | None = None,
) -> None:
    exceptions.append(
        {
            "SKU": delivery_row["SKU"],
            "原始站点": delivery_row["原始站点"],
            "完整站点": full_site or "",
            "目的仓": destination_warehouse or "",
            "交货量": int(delivery_row["交货量"]),
            "已自动分配量": allocated,
            "人工处理量": manual,
            "异常原因": reason,
            "正常采购分配量": purchase_allocated,
            "超收规则分配量": overreceipt_allocated,
            "超收剩余额度": overreceipt_remaining,
        }
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

    import_rows: list[dict] = []
    exceptions: list[dict] = []
    candidates_by_key: dict[
        tuple[object, object],
        tuple[_PurchaseBalance, ...],
    ] = {}

    for _, delivery_row in delivery.iterrows():
        delivery_quantity = int(delivery_row["交货量"])
        if delivery_row["异常原因"]:
            _append_exception(
                exceptions,
                delivery_row,
                delivery_row["完整站点"],
                None,
                0,
                delivery_quantity,
                delivery_row["异常原因"],
            )
            continue

        full_site = delivery_row["完整站点"]
        candidate_key = (delivery_row["SKU"], full_site)
        if candidate_key not in candidates_by_key:
            candidates_by_key[candidate_key] = purchase_ledger.active_candidates(
                supplier_name,
                delivery_row["SKU"],
                full_site,
            )
        candidate_balances = candidates_by_key[candidate_key]

        remaining = delivery_quantity
        allocated = 0
        purchase_allocated = 0
        overreceipt_allocated = 0
        last_destination_warehouse = ""
        for balance in candidate_balances:
            available = int(balance.remaining)
            quantity = min(remaining, available)
            if quantity <= 0:
                continue
            destination_warehouse = balance.destination_warehouse
            import_rows.append(
                {
                    "*目的仓": destination_warehouse,
                    "*供应商编码": supplier_code,
                    "*SKU": delivery_row["SKU"],
                    "*本次交货量": quantity,
                    "*站点": full_site,
                    "单据备注": "",
                    "交货备注": "",
                }
            )
            balance.remaining -= quantity
            remaining -= quantity
            allocated += quantity
            purchase_allocated += quantity
            last_destination_warehouse = destination_warehouse
            if remaining == 0:
                break

        allowance_key = make_overreceipt_key(
            supplier_name,
            delivery_row["SKU"],
            full_site,
        )
        allowance = (
            overreceipt_allowances.get(allowance_key)
            if overreceipt_allowances is not None
            else None
        )
        if remaining > 0 and allowance is not None and allowance.remaining > 0:
            quantity = min(remaining, allowance.remaining)
            import_rows.append(
                {
                    "*目的仓": allowance.destination_warehouse,
                    "*供应商编码": supplier_code,
                    "*SKU": delivery_row["SKU"],
                    "*本次交货量": quantity,
                    "*站点": full_site,
                    "单据备注": "",
                    "交货备注": f"{OVERRECEIPT_NOTE_PREFIX}：{quantity}",
                }
            )
            allowance.remaining -= quantity
            remaining -= quantity
            allocated += quantity
            overreceipt_allocated += quantity
            last_destination_warehouse = allowance.destination_warehouse

        if remaining > 0:
            if allowance is not None:
                reason = ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED
            else:
                reason = (
                    ExceptionReason.PURCHASE_BALANCE_EXCEEDED
                    if candidate_balances
                    else ExceptionReason.PURCHASE_NOT_FOUND
                )
            if allocated > 0 and allowance is None:
                import_rows[-1]["交货备注"] = f"{reason}：{remaining}"
            _append_exception(
                exceptions,
                delivery_row,
                full_site,
                last_destination_warehouse,
                allocated,
                remaining,
                reason,
                purchase_allocated=purchase_allocated,
                overreceipt_allocated=overreceipt_allocated,
                overreceipt_remaining=(
                    allowance.remaining if allowance is not None else None
                ),
            )

    import_frame = pd.DataFrame(import_rows, columns=IMPORT_COLUMNS)
    exception_frame = pd.DataFrame(exceptions, columns=RESULT_EXCEPTION_COLUMNS)
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
