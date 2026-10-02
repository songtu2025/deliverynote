"""计算任务、任务查询和审计记录的 HTTP 入口。"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .batch_preflight import preflight_batch_record
from .dependencies import RequestDependencies
from .models import AuditLog, Batch, Job, User
from .serializers import job_json, utc_isoformat


def build_job_queue(audit: Callable) -> Callable[[Batch, str, User, Session], Job]:
    def queue_job(batch: Batch, kind: str, user: User, session: Session) -> Job:
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == kind)
        )
        if existing and existing.status in {"queued", "running", "succeeded"}:
            return existing
        if existing is None:
            existing = Job(batch_id=batch.id, kind=kind, status="queued")
            session.add(existing)
        else:
            existing.status = "queued"
            existing.error_message = None
            existing.output_path = None
            existing.claim_token = None
            existing.claimed_at = None
            existing.heartbeat_at = None
            existing.finished_at = None
        session.flush()
        audit(
            session,
            user.id,
            f"queue_{kind}",
            "job",
            existing.id,
            {"batch_id": batch.id},
        )
        return existing

    return queue_job


def register_job_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    queue_job: Callable[[Batch, str, User, Session], Job],
    audit: Callable,
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user
    admin_user = dependencies.admin_user
    get_batch_or_404 = dependencies.get_batch_or_404

    @app.post("/api/batches/{batch_id}/preflight")
    def preflight_batch(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return preflight_batch_record(
            session, batch_id, user.id, get_batch_or_404, audit
        )

    @app.post("/api/batches/{batch_id}/compute", status_code=status.HTTP_202_ACCEPTED)
    def start_compute(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session, for_update=True)
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "compute")
        )
        if existing and existing.status in {"queued", "running", "succeeded"}:
            return job_json(existing)
        if batch.status not in {"preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="批次尚未通过预检")
        try:
            job = queue_job(batch, "compute", user, session)
            batch.status = "queued"
            batch.error_message = None
            session.commit()
        except IntegrityError:
            session.rollback()
            recovered_job = session.scalar(
                select(Job).where(Job.batch_id == batch.id, Job.kind == "compute")
            )
            if recovered_job is None:
                raise
            job = recovered_job
        return job_json(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job_json(job)

    @app.get("/api/audit-logs")
    def list_audit_logs(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        logs = session.scalars(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(200)
        ).all()
        return [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": utc_isoformat(log.created_at),
            }
            for log in logs
        ]
