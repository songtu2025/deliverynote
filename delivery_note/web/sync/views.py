from datetime import datetime
from typing import Callable

import pandas as pd

from ..models import PurchaseSyncJob, SelfOperatedInboundSyncJob


def sync_job_json(
    job: PurchaseSyncJob | SelfOperatedInboundSyncJob,
    utc_isoformat: Callable[[datetime], str],
) -> dict[str, object]:
    findings = job.issues or []
    warning_count = sum(finding.get("severity") == "warning" for finding in findings)
    result = {
        "id": job.id,
        "status": job.status,
        "base_version_id": job.base_version_id,
        "candidate_version_id": job.candidate_version_id,
        "total_orders": job.total_orders,
        "raw_detail_count": job.raw_detail_count,
        "eligible_detail_count": job.eligible_detail_count,
        "filtered_detail_count": job.filtered_detail_count,
        "issue_count": len(findings) - warning_count,
        "warning_count": warning_count,
        "diff": job.diff or {},
        "error_message": job.error_message,
        "created_at": utc_isoformat(job.created_at),
        "claimed_at": (utc_isoformat(job.claimed_at) if job.claimed_at else None),
        "heartbeat_at": (utc_isoformat(job.heartbeat_at) if job.heartbeat_at else None),
        "finished_at": (utc_isoformat(job.finished_at) if job.finished_at else None),
    }
    if isinstance(job, PurchaseSyncJob):
        result.update(
            product_version_id=job.product_version_id,
            supplier_version_id=job.supplier_version_id,
            processed_orders=job.processed_orders,
            current_order=job.current_order,
        )
    return result


def _sync_preview_json(frame: pd.DataFrame, limit: int) -> dict[str, object]:
    preview = frame.head(limit)
    rows = [
        {
            "_row_number": row_number,
            **{
                column: (
                    None
                    if pd.isna(value)
                    else value.item()
                    if hasattr(value, "item")
                    else value
                )
                for column, value in record.items()
            },
        }
        for row_number, record in enumerate(
            preview.to_dict("records"),
            start=1,
        )
    ]
    return {
        "columns": list(frame.columns),
        "rows": rows,
        "total": len(frame),
    }
