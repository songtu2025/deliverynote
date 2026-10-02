from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from ..excel_io import read_position_workbook, write_delivery_workbook
from ..pipeline import EXCEPTION_COLUMNS, BatchResult
from ..web.models import SelfOperatedBatch
from ..workers.export_files import _cleanup_previous_export_directories
from ..workers.export_inputs import _load_export_inputs
from ..workers.export_rows import _prepare_export_result
from ..workers.leases import _heartbeat
from .export_files import (
    ExportPublication,
    _discard_failed_export,
    _export_workspace,
    _register_export,
    _write_export_archive,
)
from .export_inbound import _execute_self_operated_export
from .leases import JobContext


def _write_delivery_sources(
    context: JobContext,
    sources: list[dict[str, Any]],
    version_paths: dict[str, Path],
    position_rows: pd.DataFrame,
    temporary: Path,
) -> tuple[dict[int, str], list[pd.DataFrame], list[pd.DataFrame]]:
    database, job_id, claim_token = (
        context.database,
        context.job_id,
        context.claim_token,
    )
    output_names: dict[int, str] = {}
    used_names: set[str] = set()
    merged_import_frames: list[pd.DataFrame] = []
    merged_pending_frames: list[pd.DataFrame] = []
    for source in sources:
        _heartbeat(database, job_id, claim_token)
        result, import_rows, pending_rows = _prepare_export_result(
            source, position_rows
        )
        merged_import_frames.append(import_rows)
        merged_pending_frames.append(pending_rows)
        output_name = f"{Path(source['original_name']).stem}_交货处理.xlsx"
        if output_name in used_names:
            raise RuntimeError(f"导出文件名重复：{output_name}")
        used_names.add(output_name)
        output_path = temporary / output_name
        write_delivery_workbook(
            version_paths["template"],
            output_path,
            result,
            import_rows,
            pending_rows,
        )
        output_names[source["id"]] = output_name
    return output_names, merged_import_frames, merged_pending_frames


def _write_merged_delivery(
    template_path: Path,
    temporary: Path,
    batch_id: int,
    sources: list[dict[str, Any]],
    frames: tuple[list[pd.DataFrame], list[pd.DataFrame]],
) -> None:
    merged_import_frames, merged_pending_frames = frames
    merged_import_rows = pd.concat(
        merged_import_frames,
        ignore_index=True,
    )
    merged_pending_rows = pd.concat(
        merged_pending_frames,
        ignore_index=True,
    )
    delivery_total = sum(source["delivery_total"] for source in sources)
    import_total = int(merged_import_rows["*本次交货量"].sum())
    pending_total = int(merged_pending_rows["*本次交货量"].sum())
    if delivery_total != import_total + pending_total:
        raise RuntimeError("合并导出数量不守恒")
    merged_result = BatchResult(
        import_rows=merged_import_rows,
        exception_rows=pd.DataFrame(columns=EXCEPTION_COLUMNS),
        delivery_total=delivery_total,
        import_total=import_total,
        manual_total=pending_total,
    )
    write_delivery_workbook(
        template_path,
        temporary / f"batch-{batch_id}-merged.xlsx",
        merged_result,
        merged_import_rows,
        merged_pending_rows,
    )


def _execute_export(
    context: JobContext,
    batch_id: int,
    storage_root: Path,
) -> None:
    database = context.database
    job_id = context.job_id
    claim_token = context.claim_token
    with database.session() as session:
        self_operated = session.get(SelfOperatedBatch, batch_id)
    if self_operated is not None:
        _execute_self_operated_export(
            context,
            batch_id,
            storage_root,
        )
        return
    _heartbeat(database, job_id, claim_token)
    version_paths, sources, previous_export_paths = _load_export_inputs(
        database,
        batch_id,
    )
    position_rows = read_position_workbook(version_paths["position"])
    _heartbeat(database, job_id, claim_token)
    export_root, temporary, published = _export_workspace(storage_root, batch_id)
    registered_path = published / f"batch-{batch_id}.zip"
    try:
        output_names, merged_import_frames, merged_pending_frames = (
            _write_delivery_sources(
                context, sources, version_paths, position_rows, temporary
            )
        )

        if len(sources) > 1:
            _write_merged_delivery(
                version_paths["template"],
                temporary,
                batch_id,
                sources,
                (merged_import_frames, merged_pending_frames),
            )

        _write_export_archive(temporary, f"batch-{batch_id}.zip", sources, output_names)
        _heartbeat(database, job_id, claim_token)
        context.before_finalize()
        os.replace(temporary, published)

        _register_export(
            context,
            batch_id,
            ExportPublication(published, output_names, registered_path, False),
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
