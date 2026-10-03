import json
from typing import Any

import pandas as pd

from ..exception_reasons import ExceptionReason
from .models import (
    EXCEPTION_COLUMNS,
    IMPORT_COLUMNS,
    PENDING_COLUMNS,
    POSITION_VALUE_COLUMNS,
    POSITION_SOURCE_COLUMNS,
    _require_columns,
)
from .keys import _normalize_position_text, _normalize_pending_site


def build_manual_import_rows(
    exception_rows: pd.DataFrame,
    supplier_code: str,
) -> pd.DataFrame:
    """把异常数量转换为可补录后再次导入的官方模板字段。"""
    _require_columns(exception_rows, set(EXCEPTION_COLUMNS), "异常明细")
    rows: list[dict] = []

    for _, exception in exception_rows.iterrows():
        reason = str(exception["异常原因"])
        full_site = "" if pd.isna(exception["完整站点"]) else str(exception["完整站点"])
        original_site = (
            "" if pd.isna(exception["原始站点"]) else str(exception["原始站点"])
        )
        destination_warehouse = (
            "" if pd.isna(exception["目的仓"]) else exception["目的仓"]
        )
        manual_quantity = int(exception["人工处理量"])
        site = "" if reason == ExceptionReason.AMBIGUOUS_PRODUCT_SITE else full_site
        note = reason
        if reason in {
            ExceptionReason.PURCHASE_BALANCE_EXCEEDED,
            ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED,
        }:
            note = f"{reason}：{manual_quantity}"
        elif reason == ExceptionReason.PRODUCT_NOT_FOUND and original_site:
            note = f"{reason}；原始站点：{original_site}"
        elif reason == ExceptionReason.AMBIGUOUS_PRODUCT_SITE and full_site:
            note = f"{reason}：{full_site}"

        rows.append(
            {
                "*目的仓": destination_warehouse,
                "*供应商编码": supplier_code,
                "*SKU": exception["SKU"],
                "*本次交货量": manual_quantity,
                "*站点": site,
                "单据备注": "",
                "交货备注": note,
            }
        )

    return pd.DataFrame(rows, columns=IMPORT_COLUMNS)


def _position_value(value: Any) -> Any:
    if pd.isna(value):
        return ""
    if isinstance(value, str):
        return value.strip()
    value = value.item() if hasattr(value, "item") else value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def enrich_pending_import_rows(
    pending_rows: pd.DataFrame,
    position_rows: pd.DataFrame,
) -> pd.DataFrame:
    """按店铺站点和积加 SKU 为待处理数据补充定位信息。"""
    _require_columns(pending_rows, set(IMPORT_COLUMNS), "待处理导入")
    _require_columns(position_rows, set(POSITION_SOURCE_COLUMNS), "排查表")

    result = pending_rows[IMPORT_COLUMNS].copy()
    for column in POSITION_VALUE_COLUMNS:
        result[column] = pd.Series("", index=result.index, dtype=object)
    if result.empty:
        return result[PENDING_COLUMNS]

    positions = position_rows[POSITION_SOURCE_COLUMNS].copy()
    positions["_site_key"] = positions["店铺-站点"].map(_normalize_position_text)
    positions["_sku_key"] = positions["积加SKU"].map(_normalize_position_text)
    positions = positions[positions["_site_key"].ne("") & positions["_sku_key"].ne("")]
    pending_keys = {
        (
            _normalize_pending_site(site),
            _normalize_position_text(sku),
        )
        for site, sku in zip(result["*站点"], result["*SKU"])
    }
    positions = positions[
        [
            (site_key, sku_key) in pending_keys
            for site_key, sku_key in zip(
                positions["_site_key"],
                positions["_sku_key"],
            )
        ]
    ]
    groups = {
        key: group.copy()
        for key, group in positions.groupby(["_site_key", "_sku_key"], sort=False)
    }
    scale_order = {"短尾": 0, "中尾": 1, "长尾": 2}

    for index, pending in result.iterrows():
        key = (
            _normalize_pending_site(pending["*站点"]),
            _normalize_position_text(pending["*SKU"]),
        )
        matches = groups.get(key)
        if matches is None or matches.empty:
            continue
        if len(matches) == 1:
            for column in POSITION_VALUE_COLUMNS:
                result.at[index, column] = _position_value(matches.iloc[0][column])
            continue

        matches["_msku"] = matches["MSKU"].map(_normalize_position_text)
        if matches["_msku"].eq("").any() or matches["_msku"].duplicated().any():
            raise ValueError("排查表重复键内的 MSKU 必须非空且唯一")
        matches["_scale_order"] = matches["规模定位"].map(
            lambda value: scale_order.get(str(value).strip(), 3)
        )
        matches = matches.sort_values(["_scale_order", "_msku"], kind="stable")
        for column in POSITION_VALUE_COLUMNS:
            mapping = {
                str(row["MSKU"]).strip(): _position_value(row[column])
                for _, row in matches.iterrows()
            }
            result.at[index, column] = json.dumps(
                mapping, ensure_ascii=False, separators=(",", ":")
            )

    return result[PENDING_COLUMNS]
