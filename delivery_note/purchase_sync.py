from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .excel_io import PURCHASE_COLUMNS


PURCHASE_KEY_COLUMNS = ["供应商", "SKU", "平台站点", "目的仓"]


@dataclass(frozen=True)
class PurchaseMappingResult:
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


def _normalize_site(value: Any) -> tuple[str, str]:
    source_site = _text(value)
    if source_site == "共享":
        return source_site, ""
    site = source_site.removeprefix("AMAZON:").strip()
    if ":" not in site:
        return "", "积加接口站点信息不足"
    return f"AMAZON:{site}", ""


def _detail_items(detail: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for warehouse in detail.get("warehouseProcureItemVos") or []:
        for source in warehouse.get("procureItemVos") or []:
            item = dict(source)
            for field in (
                "supplierCode",
                "supplierName",
                "arrivalMarketName",
                "deliveryWarehouseName",
            ):
                if not item.get(field):
                    item[field] = warehouse.get(field) or detail.get(field)
            items.append(item)
    return items


def map_purchase_order(
    order: dict[str, Any],
    detail: dict[str, Any],
) -> PurchaseMappingResult:
    """将一张积加采购单映射为系统采购数据行。"""

    return _map_purchase_order(order, detail)


def _map_purchase_order(
    order: dict[str, Any],
    detail: dict[str, Any],
) -> PurchaseMappingResult:
    po_code = _text(order.get("code") or order.get("poCode") or detail.get("poCode"))
    status = _text(
        order.get("invoicesStatusName")
        or detail.get("invoicesStatusName")
        or order.get("statusName")
    )
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    items = _detail_items(detail)
    filtered_count = 0

    for item in items:
        balance_value = item.get("balanceQuantity")
        try:
            balance = float(balance_value)
        except (TypeError, ValueError):
            balance = 0
        if balance <= 0:
            filtered_count += 1
            continue

        sku = _text(item.get("product"))
        source_site = _text(item.get("arrivalMarketName"))
        destination = _text(item.get("deliveryWarehouseName"))
        supplier = _text(item.get("supplierName"))
        quantity: int | float = int(balance) if balance.is_integer() else balance
        full_site, site_error = _normalize_site(source_site)
        common = {
            "po_code": po_code,
            "sku": sku,
            "source_site": source_site,
            "supplier_code": _text(item.get("supplierCode")),
            "supplier_name": _text(item.get("supplierName")),
            "warehouse": destination,
            "quantity": quantity,
        }
        if source_site == "共享":
            warnings.append(
                {
                    **common,
                    "severity": "warning",
                    "code": "shared_site",
                    "message": "共享站点数据不能参与正常交货匹配",
                }
            )
        if site_error:
            issues.append(
                {
                    **common,
                    "severity": "error",
                    "code": "site_mapping",
                    "message": site_error,
                }
            )
        if not sku:
            issues.append(
                {
                    **common,
                    "severity": "error",
                    "code": "missing_sku",
                    "message": "SKU 为空",
                }
            )
        if not destination:
            issues.append(
                {
                    **common,
                    "severity": "error",
                    "code": "missing_destination",
                    "message": "目的仓为空",
                }
            )
        if site_error or not sku or not destination:
            continue

        rows.append(
            {
                "单据状态": status,
                "供应商": supplier,
                "SKU": sku,
                "平台站点": full_site,
                "目的仓": destination,
                "未交量": quantity,
            }
        )

    return PurchaseMappingResult(
        rows=rows,
        issues=issues,
        warnings=warnings,
        raw_count=len(items),
        eligible_count=len(items) - filtered_count,
        filtered_count=filtered_count,
    )


def map_purchase_orders(
    order_details: list[tuple[dict[str, Any], dict[str, Any]]],
) -> PurchaseMappingResult:
    """批量映射采购单。"""

    results = [_map_purchase_order(order, detail) for order, detail in order_details]
    return PurchaseMappingResult(
        rows=[row for result in results for row in result.rows],
        issues=[issue for result in results for issue in result.issues],
        warnings=[warning for result in results for warning in result.warnings],
        raw_count=sum(result.raw_count for result in results),
        eligible_count=sum(result.eligible_count for result in results),
        filtered_count=sum(result.filtered_count for result in results),
    )


def purchase_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=PURCHASE_COLUMNS)


def compare_purchase_frames(
    current: pd.DataFrame | None,
    candidate: pd.DataFrame,
) -> dict[str, int | float]:
    """按采购匹配键汇总并比较当前版本与候选版本。"""

    def aggregate(frame: pd.DataFrame | None) -> dict[tuple[str, ...], float]:
        if frame is None or frame.empty:
            return {}
        grouped = frame.groupby(PURCHASE_KEY_COLUMNS, dropna=False)["未交量"].sum()
        return {
            tuple(_text(part) for part in key): float(value)
            for key, value in grouped.items()
        }

    before = aggregate(current)
    after = aggregate(candidate)
    added = after.keys() - before.keys()
    removed = before.keys() - after.keys()
    changed = {key for key in before.keys() & after.keys() if before[key] != after[key]}
    return {
        "before_lines": len(before),
        "after_lines": len(after),
        "added_lines": len(added),
        "removed_lines": len(removed),
        "changed_lines": len(changed),
        "before_quantity": sum(before.values()),
        "after_quantity": sum(after.values()),
    }


def write_purchase_workbook(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False)
