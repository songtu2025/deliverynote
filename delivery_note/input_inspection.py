from pathlib import Path
from typing import Any

import pandas as pd

from .inspection import frames, streaming, workbooks
from .config import supplier_aliases, validate_supplier_frame
from .processing.models import POSITION_SOURCE_COLUMNS


POSITION_KEY = ["店铺-站点", "积加SKU", "MSKU"]
_POSITION_VALUES = [
    column for column in POSITION_SOURCE_COLUMNS if column not in POSITION_KEY
]
_KNOWN_SCALES = {"短尾", "中尾", "长尾"}


def _inspect_frame(kind: str, frame: pd.DataFrame) -> dict:
    result = {
        "kind": kind,
        "row_count": len(frame),
        "columns": [str(column) for column in frame.columns],
        "metrics": {},
        "issues": [],
    }
    if kind == "position":
        result["metrics"] = {
            "sites": int(frame["店铺-站点"].dropna().astype(str).str.strip().nunique()),
            "skus": int(frame["积加SKU"].dropna().astype(str).str.strip().nunique()),
            "mskus": int(frame["MSKU"].dropna().astype(str).str.strip().nunique()),
        }
        result["issues"] = validate_position_frame(frame)
    elif kind == "purchase":
        result["issues"] = frames.validate_purchase_frame(frame)
    elif kind == "supplier":
        aliases = frame["供应商别名"].map(supplier_aliases)
        result["metrics"] = {
            "aliases": int(aliases.map(len).sum()),
            "suppliers_with_aliases": int(aliases.map(bool).sum()),
        }
        result["issues"] = validate_supplier_frame(frame)
    return result


def inspect_input_version(kind: str, path: Path) -> dict:
    return _inspect_frame(kind, workbooks._read_frame(kind, path))


def inspect_input_version_with_preview(
    kind: str,
    path: Path,
    offset: int,
    limit: int,
) -> dict:
    """一次读取基础资料并生成摘要与分页预览。"""

    path = Path(path)
    if kind in streaming._STREAMING_COLUMNS and path.suffix.lower() in {
        ".xlsx",
        ".xlsm",
    }:
        return streaming._stream_xlsx_inspection(kind, path, offset, limit)
    frame = workbooks._read_frame(kind, path)
    return {
        "summary": _inspect_frame(kind, frame),
        "preview": frames._preview_frame(kind, frame, offset, limit),
    }


def preview_input_version_page(
    kind: str,
    path: Path,
    offset: int,
    limit: int,
    summary: dict,
) -> dict:
    """基于已缓存摘要加载新页面，避免再次完整扫描流式工作簿。"""

    path = Path(path)
    if kind in streaming._STREAMING_COLUMNS and path.suffix.lower() in {
        ".xlsx",
        ".xlsm",
    }:
        return streaming._stream_xlsx_preview(kind, path, offset, limit, summary)
    return frames._preview_frame(kind, workbooks._read_frame(kind, path), offset, limit)


def preview_input_version(
    kind: str,
    path: Path,
    offset: int,
    limit: int,
) -> dict:
    return inspect_input_version_with_preview(
        kind,
        path,
        offset,
        limit,
    )["preview"]


def _identity_values(frame: pd.DataFrame, column: str) -> pd.Series:
    return frames._text_values(frame, column).str.upper()


def _append_issue(
    issues: list[dict],
    *,
    severity: str,
    code: str,
    message: str,
    mask: pd.Series,
) -> None:
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


def validate_position_frame(frame: pd.DataFrame) -> list[dict]:
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

    issues: list[dict] = []
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
    records: dict[tuple[str, str, str], list[tuple[Any, ...]]] = {}
    normalized_keys = pd.DataFrame(
        {column: _identity_values(frame, column) for column in POSITION_KEY}
    )
    for key_values, source_values in zip(
        normalized_keys.itertuples(index=False, name=None),
        frame[_POSITION_VALUES].itertuples(index=False, name=None),
    ):
        key = tuple(key_values)
        values = tuple(_position_comparison_text(value) for value in source_values)
        records.setdefault(key, []).append(values)
    return records


def _position_comparison_text(value: Any) -> str:
    safe_value = frames._json_safe(value)
    if safe_value is None:
        return ""
    if isinstance(safe_value, float) and safe_value.is_integer():
        return str(int(safe_value))
    return str(safe_value)


def position_diff(base: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, int]:
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
) -> list[dict]:
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
