from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ..excel_io import read_purchase_workbook
from ..purchase_sync import (
    compare_purchase_frames,
    map_purchase_orders,
    purchase_frame,
    write_purchase_workbook,
)
from ..web.models import PurchaseSyncJob
from ..workers.leases import JobContext, _purchase_sync_heartbeat
from .purchase_collection import (
    _collect_purchase_details,
    _purchase_audit_details,
    _write_collection_cache,
)
from .sync_results import (
    SyncCandidate,
    _block_sync,
    _load_sync_base_path,
    _publish_sync_candidate,
)

PURCHASE_SYNC_MODES = {"full", "shadow", "incremental"}


def _execute_purchase_sync(
    context: JobContext,
    storage_root: Path,
) -> None:
    database, job_id, claim_token = (
        context.database,
        context.job_id,
        context.claim_token,
    )
    sync_mode = os.getenv("PURCHASE_SYNC_MODE", "incremental").strip().lower()
    if sync_mode not in PURCHASE_SYNC_MODES:
        raise RuntimeError(f"未知采购同步模式：{sync_mode}")

    base_path = _load_sync_base_path(database, PurchaseSyncJob, job_id)

    collection = _collect_purchase_details(context, storage_root, sync_mode)
    order_details = collection.order_details

    mapped = map_purchase_orders(order_details)
    findings = [*mapped.issues, *mapped.warnings]
    _purchase_sync_heartbeat(
        database,
        job_id,
        claim_token,
        raw_detail_count=mapped.raw_count,
        eligible_detail_count=mapped.eligible_count,
        filtered_detail_count=mapped.filtered_count,
        issues=findings,
        current_order=None,
    )
    if mapped.issues:
        _block_sync(context, PurchaseSyncJob, len(mapped.issues))
        return

    candidate = purchase_frame(mapped.rows)
    current = (
        read_purchase_workbook(base_path)
        if base_path is not None and base_path.is_file()
        else None
    )
    difference = compare_purchase_frames(current, candidate)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    original_name = f"积加采购数据_{timestamp}.xlsx"
    candidate_path = (
        storage_root / "master" / "purchase" / f"purchase_sync_{job_id}_{original_name}"
    )
    write_purchase_workbook(candidate_path, candidate)
    read_purchase_workbook(candidate_path)
    try:
        _publish_sync_candidate(
            context,
            PurchaseSyncJob,
            SyncCandidate(
                "purchase",
                f"积加同步-{timestamp}-#{job_id}",
                original_name,
                candidate_path,
                difference,
            ),
            _purchase_audit_details(collection, len(mapped.warnings)),
        )
    except Exception:
        candidate_path.unlink(missing_ok=True)
        raise
    _write_collection_cache(collection)
