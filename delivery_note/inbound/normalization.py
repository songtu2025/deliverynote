import re
from typing import Any

import pandas as pd

from ..processing.models import _require_columns
from .models import SOURCE_COLUMNS, SelfOperatedDeliverySource


def _text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_self_operated_delivery_sheet(
    sheet: pd.DataFrame,
) -> SelfOperatedDeliverySource:
    """读取明细表，独立提取交货单号并汇总质检合格数量。"""
    _require_columns(sheet, SOURCE_COLUMNS, "自营仓交货单明细")

    data = sheet.copy()
    data["积加SKU"] = data["积加SKU"].map(_text)
    data["站点"] = data["站点"].map(_text)
    data = data[data["积加SKU"].ne("") & data["站点"].ne("")].copy()
    data = data[
        ~data["积加SKU"].str.fullmatch(r"合计|总计|Grand Total", case=False)
    ].copy()
    if data.empty:
        raise ValueError("自营仓交货单明细没有有效商品数据")

    raw_quantities = data["实收数量"]
    quantities = pd.to_numeric(raw_quantities, errors="coerce")
    blank_quantities = raw_quantities.map(_text).eq("")
    if (blank_quantities | quantities.isna()).any():
        raise ValueError("自营仓交货单实收数量存在空值或无效值")
    if ((quantities < 0) | (quantities % 1 != 0)).any():
        raise ValueError("自营仓交货单实收数量必须为非负整数")

    valid_numbers: set[str] = set()
    invalid_values: list[str] = []
    for value in data["交货单号"]:
        delivery_number = _text(value)
        if not delivery_number:
            continue
        if re.fullmatch(r"LN\d+", delivery_number, flags=re.IGNORECASE):
            valid_numbers.add(delivery_number.upper())
        elif delivery_number not in invalid_values:
            invalid_values.append(delivery_number)
    if not valid_numbers:
        raise ValueError("自营仓交货单未提取到有效交货单号")

    data["交货量"] = quantities.astype(int)
    data["SKU"] = data["积加SKU"]
    data["原始站点"] = data["站点"].str.removesuffix("站")
    delivery_lines = (
        data.groupby(["SKU", "原始站点"], as_index=False, sort=True)[["交货量"]]
        .sum()
        .sort_values(["SKU", "原始站点"], kind="stable")
        .reset_index(drop=True)
    )
    return SelfOperatedDeliverySource(
        delivery_lines=delivery_lines,
        delivery_numbers=tuple(sorted(valid_numbers)),
        invalid_delivery_values=tuple(invalid_values),
    )
