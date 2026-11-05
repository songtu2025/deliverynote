"""Web 和 Worker 共用的批次任务排队与自营仓接续规则。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, Batch, Job
from .purchase_snapshot import PURCHASE_SNAPSHOT_KIND


def reset_batch_job(
    session: Session, batch: Batch, kind: str, *, refresh: bool = False
) -> tuple[Job, bool]:
    existing = session.scalar(
        select(Job).where(Job.batch_id == batch.id, Job.kind == kind)
    )
    retained_snapshot = kind == PURCHASE_SNAPSHOT_KIND and not refresh
    if existing and (
        existing.status in {"queued", "running"}
        or retained_snapshot
        or (existing.status == "succeeded" and not refresh)
    ):
        return existing, False
    if existing is None:
        existing = Job(batch_id=batch.id, kind=kind, status="queued")
        session.add(existing)
    else:
        existing.status = "queued"
        existing.error_message = None
        if kind != PURCHASE_SNAPSHOT_KIND:
            existing.output_path = None
        else:
            existing.attempts = 0
        existing.claim_token = None
        existing.claimed_at = None
        existing.heartbeat_at = None
        existing.finished_at = None
    session.flush()
    return existing, True


def queue_followup_job(session: Session, batch: Batch, kind: str) -> Job:
    job, queued = reset_batch_job(session, batch, kind)
    if queued:
        session.add(
            AuditLog(
                user_id=None,
                action=f"queue_{kind}",
                entity_type="job",
                entity_id=str(job.id),
                details={"batch_id": batch.id},
            )
        )
    return job
