from typing import Mapping, Sequence

import pandas as pd

from ..exception_reasons import ExceptionReason
from ..processing.keys import _normalize_position_text
from ..processing.models import _require_columns
from .models import INBOUND_COLUMNS
from .normalization import _text


def prepare_inbound_candidates(
    inbound_rows: pd.DataFrame,
    delivery_numbers: Sequence[str],
) -> pd.DataFrame:
    """核对交货单号并保留共享余额对应的原始行序号。"""
    _require_columns(inbound_rows, INBOUND_COLUMNS, "自营仓收货入库单")
    numbers = sorted(
        {_normalize_position_text(value) for value in delivery_numbers if _text(value)}
    )
    if not numbers:
        raise ValueError("没有可用于筛选的交货单号")

    inbound = inbound_rows.copy().reset_index(drop=True)
    inbound["_source_order"] = inbound.index
    for source, target in (
        ("SKU", "_sku_key"),
        ("平台站点", "_site_key"),
        ("关联交货单/调拨单", "_delivery_key"),
        ("关联采购单", "_po_key"),
        ("供应商", "_supplier_key"),
    ):
        inbound[target] = inbound[source].map(_normalize_position_text)
    inbound["_receivable"] = pd.to_numeric(inbound["应收货"], errors="coerce")
    missing = sorted(set(numbers) - set(inbound["_delivery_key"]))
    if missing:
        raise ValueError(f"自营仓导出缺少交货单号：{', '.join(missing)}")
    return inbound[inbound["_delivery_key"].isin(numbers)].copy()


def select_inbound_candidates(
    inbound: pd.DataFrame,
    delivery: pd.Series,
    supplier_name: str,
) -> tuple[pd.DataFrame, str]:
    """按原有异常优先级筛选，并按采购单和来源行稳定排序。"""
    candidates = inbound[
        inbound["_sku_key"].eq(_normalize_position_text(delivery["SKU"]))
        & inbound["_site_key"].eq(_normalize_position_text(delivery["完整站点"]))
    ].copy()
    if candidates.empty:
        return candidates, ExceptionReason.INBOUND_ORDER_NOT_FOUND
    candidates = candidates[
        candidates["_supplier_key"].eq(_normalize_position_text(supplier_name))
    ].copy()
    if candidates.empty:
        return candidates, ExceptionReason.SUPPLIER_MISMATCH
    candidates = candidates[candidates["_po_key"].ne("")].copy()
    if candidates.empty:
        return candidates, ExceptionReason.PO_NAME_MISSING
    valid = (
        candidates["_receivable"].notna()
        & candidates["_receivable"].ge(0)
        & candidates["_receivable"].mod(1).eq(0)
    )
    candidates = candidates[valid].copy()
    if candidates.empty:
        return candidates, ExceptionReason.RECEIVABLE_INVALID
    return candidates.sort_values(["_po_key", "_source_order"], kind="stable"), ""


def _resolve_inbound_candidate_sites(
    resolved: pd.DataFrame,
    inbound: pd.DataFrame,
) -> pd.DataFrame:
    """使用已筛选自营仓候选消除产品信息中的站点歧义。"""
    site_candidates: dict[tuple[str, str], set[str]] = {}
    for _, row in inbound[["_sku_key", "_site_key"]].drop_duplicates().iterrows():
        site = row["_site_key"]
        country = site.rsplit(":", 1)[-1]
        site_candidates.setdefault((row["_sku_key"], country), set()).add(site)

    result = resolved.copy()
    ambiguous = result["异常原因"].eq(ExceptionReason.AMBIGUOUS_PRODUCT_SITE)
    for index, row in result[ambiguous].iterrows():
        candidates = site_candidates.get(
            (
                _normalize_position_text(row["SKU"]),
                _normalize_position_text(row["原始站点"]),
            ),
            set(),
        )
        product_sites = [
            site.strip() for site in str(row["完整站点"]).split("、") if site.strip()
        ]
        matches = [
            site
            for site in product_sites
            if _normalize_position_text(site) in candidates
        ]
        if len(matches) == 1:
            result.at[index, "完整站点"] = matches[0]
            result.at[index, "异常原因"] = ""
        elif matches:
            result.at[index, "完整站点"] = "、".join(matches)
        else:
            result.at[index, "完整站点"] = ""
            result.at[index, "异常原因"] = ExceptionReason.INBOUND_ORDER_NOT_FOUND
    return result


def _apply_site_overrides(
    resolved: pd.DataFrame,
    site_overrides: Mapping[tuple[str, str], str] | None,
) -> pd.DataFrame:
    """应用操作员对仍有歧义的完整站点选择。"""
    if not site_overrides:
        return resolved

    normalized_overrides = {
        (_normalize_position_text(sku), _normalize_position_text(site)): _text(
            full_site
        )
        for (sku, site), full_site in site_overrides.items()
    }
    result = resolved.copy()
    ambiguous = result["异常原因"].eq(ExceptionReason.AMBIGUOUS_PRODUCT_SITE)
    for index, row in result[ambiguous].iterrows():
        selected = normalized_overrides.get(
            (
                _normalize_position_text(row["SKU"]),
                _normalize_position_text(row["原始站点"]),
            )
        )
        if not selected:
            continue
        candidates = {
            _normalize_position_text(site)
            for site in str(row["完整站点"]).split("、")
            if site.strip()
        }
        if _normalize_position_text(selected) not in candidates:
            raise ValueError(
                f"人工选择站点不在候选范围：{row['SKU']} / {row['原始站点']}"
            )
        result.at[index, "完整站点"] = selected
        result.at[index, "异常原因"] = ""
    return result
