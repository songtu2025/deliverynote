"""积加采购与待入库同步共用的文本和站点规范化。"""

from typing import Any

import pandas as pd


def sync_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def normalize_sync_site(value: Any) -> tuple[str, str]:
    source_site = sync_text(value)
    if source_site == "共享":
        return source_site, ""
    site = source_site.removeprefix("AMAZON:").strip()
    if ":" not in site:
        return "", "积加接口站点信息不足"
    return f"AMAZON:{site}", ""
