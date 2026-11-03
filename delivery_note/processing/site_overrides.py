from collections.abc import Mapping

import pandas as pd

from ..exception_reasons import ExceptionReason
from .keys import _normalize_position_text


def _apply_site_overrides(
    resolved: pd.DataFrame,
    site_overrides: Mapping[tuple[str, str], str] | None,
    *,
    allow_site_change: bool = False,
) -> pd.DataFrame:
    """应用操作员对仍有歧义的完整站点选择。"""
    if not site_overrides:
        return resolved

    normalized_overrides = {
        (_normalize_position_text(sku), _normalize_position_text(site)): ""
        if pd.isna(full_site)
        else str(full_site).strip()
        for (sku, site), full_site in site_overrides.items()
    }
    result = resolved.copy()
    ambiguous = result["异常原因"].eq(ExceptionReason.AMBIGUOUS_PRODUCT_SITE)
    candidates_to_override = result if allow_site_change else result[ambiguous]
    for index, row in candidates_to_override.iterrows():
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
        if (
            not allow_site_change
            and _normalize_position_text(selected) not in candidates
        ):
            raise ValueError(
                f"人工选择站点不在候选范围：{row['SKU']} / {row['原始站点']}"
            )
        result.at[index, "完整站点"] = selected
        result.at[index, "异常原因"] = ""
    return result
