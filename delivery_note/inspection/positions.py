"""库位质量检查、复合标识差异与变化幅度告警。"""

from typing import Any

import pandas as pd

from ..processing.models import POSITION_SOURCE_COLUMNS
from . import frames

POSITION_KEY = ["店铺-站点", "积加SKU", "MSKU"]
_POSITION_VALUES = [
    column for column in POSITION_SOURCE_COLUMNS if column not in POSITION_KEY
]
_KNOWN_SCALES = {"短尾", "中尾", "长尾"}


def _identity_values(frame: pd.DataFrame, column: str) -> pd.Series:
    """统一复合标识的大小写和两端空白。"""

    return frames._text_values(frame, column).str.upper()


def _append_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    mask: pd.Series,
) -> None:
    """在存在问题行时追加带工作簿行号的告警。"""

    row_numbers = frames._row_numbers(mask)
    if row_numbers:
        issues.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "row_numbers": row_numbers,
            }
        )


def validate_position_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """按既有顺序报告库位标识错误和定位告警。"""

    site = _identity_values(frame, "店铺-站点")
    sku = _identity_values(frame, "积加SKU")
    msku = _identity_values(frame, "MSKU")
    empty_site = site.eq("")
    empty_sku = sku.eq("")

    keys = pd.DataFrame({"site": site, "sku": sku, "msku": msku})
    valid_group = site.ne("") & sku.ne("")
    multiple_rows = valid_group & keys.duplicated(["site", "sku"], keep=False)
    duplicate_full_key = (
        valid_group & msku.ne("") & keys.duplicated(["site", "sku", "msku"], keep=False)
    )
    duplicate_msku = duplicate_full_key | (multiple_rows & msku.eq(""))

    scale = frames._text_values(frame, "规模定位")
    stocking = frames._text_values(frame, "备货定位")
    unknown_scale = ~scale.isin(_KNOWN_SCALES)

    issues: list[dict[str, Any]] = []
    _append_issue(
        issues,
        severity="error",
        code="empty_site",
        message="店铺-站点不能为空",
        mask=empty_site,
    )
    _append_issue(
        issues,
        severity="error",
        code="empty_sku",
        message="积加SKU不能为空",
        mask=empty_sku,
    )
    _append_issue(
        issues,
        severity="error",
        code="duplicate_msku",
        message="同一店铺-站点和积加SKU下的 MSKU 必须非空且唯一",
        mask=duplicate_msku,
    )
    _append_issue(
        issues,
        severity="warning",
        code="unknown_scale",
        message="规模定位必须为短尾、中尾或长尾",
        mask=unknown_scale,
    )
    _append_issue(
        issues,
        severity="warning",
        code="empty_stocking",
        message="备货定位不能为空",
        mask=stocking.eq(""),
    )
    return issues


def _position_records(
    frame: pd.DataFrame,
) -> dict[tuple[str, str, str], list[tuple[Any, ...]]]:
    """按复合标识保存有序记录，保留重复标识的多行值。"""

    records: dict[tuple[str, str, str], list[tuple[Any, ...]]] = {}
    normalized_keys = pd.DataFrame(
        {column: _identity_values(frame, column) for column in POSITION_KEY}
    )
    for key_values, source_values in zip(
        normalized_keys.itertuples(index=False, name=None),
        frame[_POSITION_VALUES].itertuples(index=False, name=None),
    ):
        site, sku, msku = key_values
        key = (site, sku, msku)
        values = tuple(_position_comparison_text(value) for value in source_values)
        records.setdefault(key, []).append(values)
    return records


def _position_comparison_text(value: Any) -> str:
    """统一库位值比较中的空值和整数表示。"""

    safe_value = frames._json_safe(value)
    if safe_value is None:
        return ""
    if isinstance(safe_value, float) and safe_value.is_integer():
        return str(int(safe_value))
    return str(safe_value)


def position_diff(base: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, int]:
    """先匹配未变行，再稳定配对同标识的剩余行。"""

    base_records = _position_records(base)
    candidate_records = _position_records(candidate)
    added = 0
    modified = 0
    deleted = 0
    unchanged = 0
    for key in base_records.keys() | candidate_records.keys():
        base_remaining = list(base_records.get(key, []))
        candidate_unmatched = []
        for candidate_values in candidate_records.get(key, []):
            try:
                match_index = base_remaining.index(candidate_values)
            except ValueError:
                candidate_unmatched.append(candidate_values)
            else:
                unchanged += 1
                base_remaining.pop(match_index)
        paired = min(len(base_remaining), len(candidate_unmatched))
        modified += paired
        deleted += len(base_remaining) - paired
        added += len(candidate_unmatched) - paired
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "unchanged": unchanged,
    }


def position_change_warnings(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
) -> list[dict[str, Any]]:
    """报告资料清空或变化达到百分之五十的指标。"""

    metrics = (
        ("row_count", "行数", len(reference), len(candidate)),
        (
            "sites",
            "站点数",
            int(_identity_values(reference, "店铺-站点").replace("", pd.NA).nunique()),
            int(_identity_values(candidate, "店铺-站点").replace("", pd.NA).nunique()),
        ),
        (
            "skus",
            "积加 SKU 数",
            int(_identity_values(reference, "积加SKU").replace("", pd.NA).nunique()),
            int(_identity_values(candidate, "积加SKU").replace("", pd.NA).nunique()),
        ),
    )
    warnings = []
    for code, label, before, after in metrics:
        if before == after:
            continue
        if before > 0 and after == 0:
            issue_code = f"{code}_cleared"
            message = f"{label}从 {before} 清空为 0"
        elif before == 0 or abs(after - before) / before >= 0.5:
            issue_code = f"{code}_changed"
            message = f"{label}从 {before} 变为 {after}，变化达到或超过 50%"
        else:
            continue
        warnings.append(
            {
                "severity": "warning",
                "code": issue_code,
                "message": message,
                "row_numbers": [],
                "before": before,
                "after": after,
            }
        )
    return warnings
