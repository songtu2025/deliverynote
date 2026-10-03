from __future__ import annotations

from typing import Any

import pandas as pd

from ..application import project_split
from ..processing.models import (EXCEPTION_COLUMNS, IMPORT_COLUMNS, BatchResult)
from ..processing.pending import (build_manual_import_rows, enrich_pending_import_rows)
from ..self_operated_inbound import INBOUND_TEMPLATE_COLUMNS
from ..web.models import ExceptionRecord


def _exception_dict(exception: ExceptionRecord) -> dict[str, Any]:
    return {
        "SKU": exception.sku,
        "原始站点": exception.original_site,
        "完整站点": exception.full_site,
        "目的仓": exception.destination,
        "交货量": exception.delivery_quantity,
        "已自动分配量": exception.allocated_quantity,
        "人工处理量": exception.manual_quantity,
        "异常原因": exception.reason,
    }


def _merge_delivery_notes(values: pd.Series[Any]) -> str:
    """按原顺序合并有效备注，并保留带数量的详细版本。"""

    notes: list[str] = []
    for value in values:
        if pd.isna(value):
            continue
        note = str(value)
        if note.strip() and note not in notes:
            notes.append(note)
    detailed_notes = [
        note
        for note in notes
        if not any(other.startswith(f"{note}：") for other in notes)
    ]
    return "；".join(detailed_notes)


def _consolidate_import_rows(import_rows: pd.DataFrame) -> pd.DataFrame:
    """合并业务身份相同的导入行，避免积加忽略后续记录。"""

    group_columns = [
        column for column in IMPORT_COLUMNS if column not in {"*本次交货量", "交货备注"}
    ]
    consolidated = import_rows.groupby(
        group_columns,
        as_index=False,
        sort=False,
        dropna=False,
    ).agg(
        {
            "*本次交货量": "sum",
            "交货备注": _merge_delivery_notes,
        }
    )
    return consolidated[IMPORT_COLUMNS]


def _consolidate_self_operated_rows(import_rows: pd.DataFrame) -> pd.DataFrame:
    """合并指向同一入库记录的跨文件数量，避免后续记录被忽略。"""

    if import_rows.empty:
        return import_rows[INBOUND_TEMPLATE_COLUMNS]
    group_columns = [
        column
        for column in INBOUND_TEMPLATE_COLUMNS
        if column not in {"本次入库", "超收原因"}
    ]
    consolidated = import_rows.groupby(
        group_columns,
        as_index=False,
        sort=False,
        dropna=False,
    ).agg(
        {
            "本次入库": "sum",
            "超收原因": _merge_delivery_notes,
        }
    )
    return consolidated[INBOUND_TEMPLATE_COLUMNS]


def _prepare_export_result(
    source: dict[str, Any], position_rows: pd.DataFrame
) -> tuple[BatchResult, pd.DataFrame, pd.DataFrame]:
    import_frames = [pd.DataFrame(source["import_rows"], columns=IMPORT_COLUMNS)]
    pending_frames = []
    exception_rows = []
    for exception_payload in source["exceptions"]:
        row = exception_payload["row"]
        exception_rows.append(row)
        exception_frame = pd.DataFrame([row], columns=EXCEPTION_COLUMNS)
        parts = exception_payload["parts"]
        if parts:
            projection = project_split(
                exception_frame.iloc[0],
                parts,
                supplier_code=source["supplier_code"],
                document_note=source["document_note"],
            )
            import_frames.append(projection.import_rows)
            pending_frames.append(projection.pending_rows)
        else:
            pending = build_manual_import_rows(
                exception_frame,
                source["supplier_code"],
            )
            pending["单据备注"] = source["document_note"]
            pending_frames.append(pending)

    import_rows = pd.concat(import_frames, ignore_index=True)
    import_rows = _consolidate_import_rows(import_rows)
    pending_rows = (
        pd.concat(pending_frames, ignore_index=True)
        if pending_frames
        else pd.DataFrame(columns=IMPORT_COLUMNS)
    )
    pending_rows = enrich_pending_import_rows(pending_rows, position_rows)
    import_total = int(import_rows["*本次交货量"].sum()) if not import_rows.empty else 0
    pending_total = (
        int(pending_rows["*本次交货量"].sum()) if not pending_rows.empty else 0
    )
    if source["delivery_total"] != import_total + pending_total:
        raise RuntimeError("导出数量不守恒")
    result = BatchResult(
        import_rows=import_rows,
        exception_rows=pd.DataFrame(exception_rows, columns=EXCEPTION_COLUMNS),
        delivery_total=source["delivery_total"],
        import_total=import_total,
        manual_total=pending_total,
    )
    return result, import_rows, pending_rows
