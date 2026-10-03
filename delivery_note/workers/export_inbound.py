from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from ..excel_io import write_self_operated_inbound_workbook
from ..inbound.models import (
    INBOUND_TEMPLATE_COLUMNS,
)
from ..workers.export_files import _cleanup_previous_export_directories
from ..workers.export_rows import _consolidate_self_operated_rows
from ..workers.leases import _heartbeat
from .export_files import (
    ExportPublication,
    _discard_failed_export,
    _export_workspace,
    _register_export,
    _write_export_archive,
)
from .export_inputs import _load_inbound_export_inputs
from .leases import JobContext


def _write_inbound_sources(
    context: JobContext,
    template_path: Path,
    source_data: list[dict[str, Any]],
    temporary: Path,
) -> tuple[dict[int, str], list[pd.DataFrame]]:
    database, job_id, claim_token = (
        context.database,
        context.job_id,
        context.claim_token,
    )
    output_names: dict[int, str] = {}
    used_names: set[str] = set()
    merged_frames: list[pd.DataFrame] = []
    for source in source_data:
        _heartbeat(database, job_id, claim_token)
        output_name = f"{Path(source['original_name']).stem}_积加入库.xlsx"
        if output_name in used_names:
            raise RuntimeError(f"导出文件名重复：{output_name}")
        used_names.add(output_name)
        allocation_rows = (
            pd.DataFrame(source["import_rows"])
            if source["import_rows"]
            else pd.DataFrame(columns=INBOUND_TEMPLATE_COLUMNS)
        )
        if "最大可收货" not in allocation_rows.columns:
            allocation_rows["最大可收货"] = pd.NA
        exported_total = (
            int(allocation_rows["本次入库"].sum()) if not allocation_rows.empty else 0
        )
        if exported_total != source["import_total"]:
            raise RuntimeError("自营仓单文件导出数量不守恒")
        write_self_operated_inbound_workbook(
            template_path,
            temporary / output_name,
            allocation_rows,
        )
        output_names[source["id"]] = output_name
        merged_frames.append(allocation_rows)
    return output_names, merged_frames


def _write_merged_inbound(
    template_path: Path,
    temporary: Path,
    batch_id: int,
    source_data: list[dict[str, Any]],
    merged_frames: list[pd.DataFrame],
) -> None:
    merged_name = f"batch-{batch_id}-merged.xlsx"
    merged_rows = pd.concat(merged_frames, ignore_index=True)
    merged_rows = _consolidate_self_operated_rows(merged_rows)
    merged_total = int(merged_rows["本次入库"].sum()) if not merged_rows.empty else 0
    if merged_total != sum(source["import_total"] for source in source_data):
        raise RuntimeError("自营仓合并导出数量不守恒")
    write_self_operated_inbound_workbook(
        template_path,
        temporary / merged_name,
        merged_rows,
    )


def _execute_self_operated_export(
    context: JobContext,
    batch_id: int,
    storage_root: Path,
) -> None:
    database = context.database
    job_id = context.job_id
    claim_token = context.claim_token
    template_path, source_data, previous_export_paths = _load_inbound_export_inputs(
        database, batch_id
    )

    _heartbeat(database, job_id, claim_token)
    export_root, temporary, published = _export_workspace(storage_root, batch_id)
    archive_name = f"batch-{batch_id}.zip"
    registered_path = published / (
        archive_name
        if len(source_data) > 1
        else f"{Path(source_data[0]['original_name']).stem}_积加入库.xlsx"
    )
    try:
        output_names, merged_frames = _write_inbound_sources(
            context, template_path, source_data, temporary
        )

        if len(source_data) > 1:
            _write_merged_inbound(
                template_path, temporary, batch_id, source_data, merged_frames
            )
            _write_export_archive(temporary, archive_name, source_data, output_names)

        _heartbeat(database, job_id, claim_token)
        context.before_finalize()
        os.replace(temporary, published)

        _register_export(
            context,
            batch_id,
            ExportPublication(published, output_names, registered_path, True),
        )
        _cleanup_previous_export_directories(
            database,
            export_root,
            published,
            previous_export_paths,
        )
    except Exception:
        _discard_failed_export(database, job_id, temporary, published, registered_path)
        raise
