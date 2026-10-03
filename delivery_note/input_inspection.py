"""基础资料摘要和预览的类型调度入口。"""

from pathlib import Path
from typing import Any

import pandas as pd

from .config import supplier_aliases, validate_supplier_frame
from .inspection import frames, positions, streaming, workbooks


def _inspect_frame(kind: str, frame: pd.DataFrame) -> dict[str, Any]:
    """按资料类型汇总行数、业务指标和质量问题。"""

    result: dict[str, Any] = {
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
        result["issues"] = positions.validate_position_frame(frame)
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


def inspect_input_version(kind: str, path: Path) -> dict[str, Any]:
    """读取基础资料并生成摘要。"""

    return _inspect_frame(kind, workbooks._read_frame(kind, path))


def inspect_input_version_with_preview(
    kind: str,
    path: Path,
    offset: int,
    limit: int,
) -> dict[str, Any]:
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
    summary: dict[str, Any],
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """返回基础资料指定页面的预览。"""

    return inspect_input_version_with_preview(
        kind,
        path,
        offset,
        limit,
    )["preview"]
