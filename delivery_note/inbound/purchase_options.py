"""只读查询当前供应商与 SKU 的逐 PO 未交采购明细。"""

from decimal import Decimal, InvalidOperation
from typing import Any

from ..gerpgo import GerpgoClient, GerpgoError
from ..processing.keys import _normalize_position_text as key
from ..purchase_sync import purchase_order_items
from ..sync_mapping import normalize_sync_site, sync_text
from .history import receipt_quantity


def collect_purchase_options(
    client: GerpgoClient, targets: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """按供应商采集一次，整批共用去重后的 PO 明细。"""
    orders: dict[str, dict[str, Any]] = {}
    for supplier in sorted({supplier for supplier, _ in targets}):
        seen: set[str] = set()
        for order in client.list_purchase_orders(supplier_code=supplier):
            code = sync_text(order.get("code") or order.get("poCode"))
            if not code or code in seen:
                raise GerpgoError("采购单号缺失或重复，无法核对完整采购明细")
            seen.add(code)
            orders.setdefault(code, order)
    rows: list[dict[str, Any]] = []
    for code, order in orders.items():
        detail = client.purchase_order_detail(code)
        for index, item in enumerate(purchase_order_items({**order, **detail})):
            identity = key(item.get("supplierCode")), key(item.get("product"))
            if identity not in targets:
                continue
            try:
                balance = Decimal(str(item.get("balanceQuantity")))
                if balance.is_finite() and balance <= 0:
                    continue
                quantity = receipt_quantity(balance)
            except (ValueError, InvalidOperation) as error:
                raise GerpgoError("采购未交数量异常，请重新查询") from error
            source_site = sync_text(item.get("arrivalMarketName"))
            site, _ = normalize_sync_site(source_site)
            rows.append(
                {
                    "id": f"{code}:{index}",
                    "supplier_code": identity[0],
                    "sku": identity[1],
                    "po_code": code,
                    "site": site or source_site,
                    "warehouse": sync_text(item.get("arrivalWarehouseName")),
                    "remaining_quantity": quantity,
                }
            )
    return rows
