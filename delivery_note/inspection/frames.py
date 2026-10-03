"""资料预览字段序列化与采购共享站点告警。"""

from datetime import date, datetime
from typing import Any

import pandas as pd


def _json_safe(value: Any) -> Any:
    """将工作簿单元格转换为可序列化值。"""

    if value is None or bool(pd.isna(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _stream_json_safe(value: Any) -> Any:
    """流式预览额外将空字符串转换为空值。"""

    if value == "":
        return None
    return _json_safe(value)


def _preview_frame(
    kind: str,
    frame: pd.DataFrame,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """按原列顺序生成数据表的一页预览。"""

    page = frame.iloc[offset : offset + limit]
    columns = [str(column) for column in frame.columns]
    rows = [
        {str(column): _json_safe(value) for column, value in zip(frame.columns, values)}
        for values in page.itertuples(index=False, name=None)
    ]
    return {
        "kind": kind,
        "columns": columns,
        "rows": rows,
        "total": len(frame),
        "offset": offset,
        "limit": limit,
    }


def _text_values(frame: pd.DataFrame, column: str) -> pd.Series:
    """统一空值和字符串两端空白。"""

    return frame[column].fillna("").astype(str).str.strip()


def _row_numbers(mask: pd.Series) -> list[int]:
    """将选中位置转换为工作簿行号。"""

    return [position + 2 for position, selected in enumerate(mask) if bool(selected)]


def shared_site_warning(row_numbers: list[int]) -> list[dict[str, Any]]:
    """生成普通读取与流式读取共用的共享站点告警。"""

    if not row_numbers:
        return []
    return [
        {
            "severity": "warning",
            "code": "shared_site",
            "message": "共享站点数据不能参与正常交货匹配",
            "row_numbers": row_numbers,
        }
    ]


def validate_purchase_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """报告不能参与正常交货匹配的采购共享站点。"""

    return shared_site_warning(_row_numbers(_text_values(frame, "平台站点").eq("共享")))
