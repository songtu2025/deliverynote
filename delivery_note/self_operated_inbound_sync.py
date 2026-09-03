from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .self_operated_inbound import INBOUND_TEMPLATE_COLUMNS


INBOUND_SYNC_COLUMNS = [
    *INBOUND_TEMPLATE_COLUMNS,
    "原始应收货",
    "供应商",
    "入库状态",
    "接口站点",
    "供应商编号",
]

INBOUND_SYNC_STATUSES = {"WAIT_INBOUND", "PART_INBOUND"}
INBOUND_SYNC_ORDER_TYPES = {"purchase", "transfer"}
INBOUND_SYNC_KEY_COLUMNS = [
    "入库单号",
    "SKU",
    "平台站点",
    "关联采购单",
    "关联交货单/调拨单",
]


@dataclass(frozen=True)
class SelfOperatedInboundMappingResult:
    rows: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    raw_count: int
    eligible_count: int
    filtered_count: int


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number


def _quantity(value: Any) -> int | float:
    number = _number(value)
    return int(number) if number.is_integer() else number


def _normalize_site(value: Any) -> tuple[str, str]:
    source_site = _text(value)
    if source_site == "共享":
        return source_site, ""
    site = source_site.removeprefix("AMAZON:").strip()
    if ":" not in site:
        return "", "积加接口站点信息不足"
    return f"AMAZON:{site}", ""


def map_self_operated_inbound_orders(
    orders: list[dict[str, Any]],
) -> SelfOperatedInboundMappingResult:
    """将积加待入库单映射为系统可读取的自营仓数据。"""

    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    raw_count = 0
    filtered_count = 0

    for order in orders:
        items = order.get("orderItemResultList") or []
        raw_count += len(items)
        status = _text(order.get("orderStatus"))
        order_type = _text(order.get("orderType"))
        if (
            status not in INBOUND_SYNC_STATUSES
            or order_type not in INBOUND_SYNC_ORDER_TYPES
        ):
            filtered_count += len(items)
            continue

        order_no = _text(order.get("orderNo"))
        warehouse = _text(order.get("warehouseName"))
        purchase_code = _text(order.get("purchaseCode"))
        related_code = _text(order.get("releatedCode"))
        supplier_code = _text(order.get("supplierCode"))
        supplier_name = _text(order.get("supplierName"))

        for item in items:
            original_expected = _number(item.get("arriveNum"))
            on_shelf = _number(item.get("onShelfNum"))
            remaining_expected = max(original_expected - on_shelf, 0)
            if remaining_expected <= 0:
                filtered_count += 1
                continue
            sku = _text(item.get("sku"))
            source_site = _text(item.get("marketName"))
            full_site, site_error = _normalize_site(source_site)
            common = {
                "order_no": order_no,
                "sku": sku,
                "source_site": source_site,
                "supplier_code": supplier_code,
                "supplier_name": supplier_name,
                "warehouse": warehouse,
                "remaining_quantity": _quantity(remaining_expected),
                "purchase_code": purchase_code,
                "related_code": related_code,
            }
            row_issues: list[tuple[str, str]] = []
            if not order_no:
                row_issues.append(("missing_order_no", "入库单号为空"))
            if not sku:
                row_issues.append(("missing_sku", "SKU 为空"))
            if not warehouse:
                row_issues.append(("missing_warehouse", "入库仓为空"))
            if not purchase_code and source_site != "共享":
                row_issues.append(("missing_purchase_code", "关联采购单为空"))
            if not related_code:
                row_issues.append(("missing_related_code", "关联交货单/调拨单为空"))
            if site_error:
                row_issues.append(("site_mapping", site_error))
            for code, message in row_issues:
                issues.append(
                    {
                        **common,
                        "severity": "error",
                        "code": code,
                        "message": message,
                    }
                )
            if source_site == "共享":
                warnings.append(
                    {
                        **common,
                        "severity": "warning",
                        "code": "shared_site",
                        "message": "共享站点数据不能参与正常入库匹配",
                    }
                )
            if row_issues:
                continue

            row = {column: "" for column in INBOUND_SYNC_COLUMNS}
            row.update(
                {
                    "入库单号": order_no,
                    "发货单号": _text(order.get("shipmentNo")),
                    "入库仓": warehouse,
                    "产品名称": _text(item.get("productName")),
                    "SKU": sku,
                    "MSKU": _text(item.get("msku")),
                    "FNSKU": _text(item.get("fnsku")),
                    "平台站点": full_site,
                    "关联采购单": purchase_code,
                    "关联交货单/调拨单": related_code,
                    "关联质检单": _text(order.get("qualityCode")),
                    "应收货": _quantity(remaining_expected),
                    "最大可收货": _quantity(item.get("maxReceiveNum")),
                    "已收货": _quantity(item.get("receiveNum")),
                    "已入库": _quantity(on_shelf),
                    "已退货": _quantity(item.get("returnedNum")),
                    "原始应收货": _quantity(original_expected),
                    "供应商": supplier_name,
                    "入库状态": status,
                    "接口站点": source_site,
                    "供应商编号": supplier_code,
                }
            )
            rows.append(row)

    return SelfOperatedInboundMappingResult(
        rows=rows,
        issues=issues,
        warnings=warnings,
        raw_count=raw_count,
        eligible_count=len(rows),
        filtered_count=filtered_count,
    )


def self_operated_inbound_frame(
    rows: list[dict[str, Any]],
) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=INBOUND_SYNC_COLUMNS)


def compare_self_operated_inbound_frames(
    current: pd.DataFrame | None,
    candidate: pd.DataFrame,
) -> dict[str, int | float]:
    """按入库匹配键比较当前启用版本与候选版本。"""

    def aggregate(frame: pd.DataFrame | None) -> dict[tuple[str, ...], float]:
        if frame is None or frame.empty:
            return {}
        grouped = frame.groupby(
            INBOUND_SYNC_KEY_COLUMNS,
            dropna=False,
        )["应收货"].sum()
        return {
            tuple(_text(part) for part in key): float(value)
            for key, value in grouped.items()
        }

    before = aggregate(current)
    after = aggregate(candidate)
    changed = {key for key in before.keys() & after.keys() if before[key] != after[key]}
    return {
        "before_lines": len(before),
        "after_lines": len(after),
        "added_lines": len(after.keys() - before.keys()),
        "removed_lines": len(before.keys() - after.keys()),
        "changed_lines": len(changed),
        "before_quantity": sum(before.values()),
        "after_quantity": sum(after.values()),
    }


def write_self_operated_inbound_source(
    path: Path,
    frame: pd.DataFrame,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False)
