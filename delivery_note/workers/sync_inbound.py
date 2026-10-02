from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..excel_io import read_self_operated_inbound_workbook
from ..gerpgo import GerpgoClient
from ..self_operated_inbound_sync import (
    compare_self_operated_inbound_frames,
    map_self_operated_inbound_orders,
    self_operated_inbound_frame,
    write_self_operated_inbound_source,
)
from ..web.models import SelfOperatedInboundSyncJob
from ..workers.leases import JobContext, _self_operated_inbound_sync_heartbeat
from .sync_results import (
    SyncCandidate,
    _block_sync,
    _load_sync_base_path,
    _publish_sync_candidate,
)


def _execute_self_operated_inbound_sync(
    context: JobContext,
    storage_root: Path,
) -> None:
    database, job_id, claim_token = (
        context.database,
        context.job_id,
        context.claim_token,
    )
    base_path = _load_sync_base_path(database, SelfOperatedInboundSyncJob, job_id)

    client = GerpgoClient.from_config(storage_root)
    orders = client.list_self_operated_inbound_orders()
    mapped = map_self_operated_inbound_orders(orders)
    findings = [*mapped.issues, *mapped.warnings]
    _self_operated_inbound_sync_heartbeat(
        database,
        job_id,
        claim_token,
        total_orders=len(orders),
        raw_detail_count=mapped.raw_count,
        eligible_detail_count=mapped.eligible_count,
        filtered_detail_count=mapped.filtered_count,
        issues=findings,
    )
    if mapped.issues:
        _block_sync(context, SelfOperatedInboundSyncJob, len(mapped.issues))
        return

    candidate = self_operated_inbound_frame(mapped.rows)
    current = (
        read_self_operated_inbound_workbook(base_path)
        if base_path is not None and base_path.is_file()
        else None
    )
    difference = compare_self_operated_inbound_frames(current, candidate)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    original_name = f"积加待入库数据_{timestamp}.xlsx"
    candidate_path = (
        storage_root
        / "master"
        / "self_operated_inbound"
        / f"self_operated_inbound_sync_{job_id}_{original_name}"
    )
    write_self_operated_inbound_source(candidate_path, candidate)
    read_self_operated_inbound_workbook(candidate_path)
    try:
        _publish_sync_candidate(
            context,
            SelfOperatedInboundSyncJob,
            SyncCandidate(
                "self_operated_inbound",
                f"积加待入库-{timestamp}-#{job_id}",
                original_name,
                candidate_path,
                difference,
            ),
            {"warning_count": len(mapped.warnings)},
        )
    except Exception:
        candidate_path.unlink(missing_ok=True)
        raise
