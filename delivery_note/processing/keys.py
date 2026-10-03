from typing import Any

import pandas as pd

from .models import OverreceiptKey


def _normalize_position_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _normalize_pending_site(value: Any) -> str:
    site = _normalize_position_text(value)
    if site.count(":") >= 2:
        return site.split(":", 1)[1]
    return site


def make_overreceipt_key(supplier: Any, sku: Any, site: Any) -> OverreceiptKey:
    return (
        _normalize_position_text(supplier),
        _normalize_position_text(sku),
        _normalize_position_text(site),
    )
