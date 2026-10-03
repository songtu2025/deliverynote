import pandas as pd

from ..config import PURCHASE_STATUSES, warehouse_sort_key
from .models import (
    OverreceiptAllowance,
    OverreceiptKey,
    OverreceiptPolicy,
    POSITION_SOURCE_COLUMNS,
    _require_columns,
)
from .keys import _normalize_position_text, _normalize_pending_site


def build_overreceipt_allowances(
    purchase_rows: pd.DataFrame,
    position_rows: pd.DataFrame,
    policy: OverreceiptPolicy,
) -> dict[OverreceiptKey, OverreceiptAllowance]:
    """按供应商、商品编码和站点生成唯一的绝对超收额度。"""

    _require_columns(
        purchase_rows,
        {"单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"},
        "采购需求",
    )
    _require_columns(position_rows, set(POSITION_SOURCE_COLUMNS), "排查表")

    purchases = purchase_rows[purchase_rows["单据状态"].isin(PURCHASE_STATUSES)].copy()
    purchases["未交量"] = pd.to_numeric(purchases["未交量"], errors="coerce").fillna(0)
    purchases = purchases[purchases["未交量"] > 0]
    if purchases.empty or not policy.allowed_warehouses:
        return {}

    positions = position_rows[POSITION_SOURCE_COLUMNS].copy()
    positions["_site_key"] = positions["店铺-站点"].map(_normalize_position_text)
    positions["_sku_key"] = positions["积加SKU"].map(_normalize_position_text)
    position_groups = {
        key: group
        for key, group in positions.groupby(["_site_key", "_sku_key"], sort=False)
    }

    purchases["_supplier_key"] = purchases["供应商"].map(_normalize_position_text)
    purchases["_sku_key"] = purchases["SKU"].map(_normalize_position_text)
    purchases["_site_key"] = purchases["平台站点"].map(_normalize_position_text)
    allowances: dict[OverreceiptKey, OverreceiptAllowance] = {}
    group_columns = ["_supplier_key", "_sku_key", "_site_key"]
    for key, purchase_group in purchases.groupby(group_columns, sort=False):
        position_key = (_normalize_pending_site(key[2]), key[1])
        position_group = position_groups.get(position_key)
        if position_group is None or position_group.empty:
            continue

        scales = [
            "" if pd.isna(value) else str(value).strip()
            for value in position_group["规模定位"]
        ]
        if any(not scale for scale in scales) or len(set(scales)) != 1:
            continue
        limit = policy.limit_for(scales[0])
        if limit <= 0:
            continue

        eligible_warehouses = sorted(
            {
                str(value).strip()
                for value in purchase_group["目的仓"]
                if not pd.isna(value)
                and str(value).strip() in policy.allowed_warehouses
            },
            key=warehouse_sort_key,
        )
        if not eligible_warehouses:
            continue
        supplier, sku, site = key
        allowances[(str(supplier), str(sku), str(site))] = OverreceiptAllowance(
            remaining=limit,
            destination_warehouse=eligible_warehouses[0],
        )
    return allowances
