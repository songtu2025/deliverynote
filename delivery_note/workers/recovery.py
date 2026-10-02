import logging
from datetime import datetime, timedelta
from threading import Event
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..web.database import Database
from ..web.models import Batch, Job, PurchaseSyncJob, SelfOperatedInboundSyncJob
from .leases import WORKER_QUEUES
from .sync_models import SYNC_METADATA, SyncJob, SyncJobModel

LOGGER = logging.getLogger("delivery_note.worker")


def _recover_batch_jobs(session: Session, cutoff: datetime, max_attempts: int) -> int:
    recovered = 0
    jobs = session.scalars(
        select(Job).where(Job.status == "running").with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        marker = job.heartbeat_at or job.claimed_at
        if marker is None or marker >= cutoff:
            continue
        batch = session.get(Batch, job.batch_id)
        if job.attempts >= max_attempts:
            now = datetime.utcnow()
            job.status = "failed"
            job.finished_at = now
            job.heartbeat_at = now
            job.error_message = (
                f"任务运行超时，已达到最大自动尝试次数（{max_attempts}）"
            )
            if batch is not None:
                batch.error_message = job.error_message
                if job.kind == "compute":
                    batch.status = "failed"
        else:
            job.status = "queued"
            job.claimed_at = None
            job.heartbeat_at = None
            job.finished_at = None
            job.error_message = "任务运行超时，已自动重试"
            if batch is not None and job.kind == "compute":
                batch.status = "queued"
                batch.error_message = job.error_message
        job.claim_token = None
        recovered += 1
    return recovered


def _recover_sync_jobs(
    session: Session, model: SyncJobModel, cutoff: datetime, max_attempts: int
) -> int:
    recovered = 0
    sync_jobs = session.scalars(
        select(model).where(model.status == "running").with_for_update(skip_locked=True)
    ).all()
    for item in sync_jobs:
        job = cast(SyncJob, item)
        marker = job.heartbeat_at or job.claimed_at
        if marker is None or marker >= cutoff:
            continue
        if job.attempts >= max_attempts:
            now = datetime.utcnow()
            job.status = "failed"
            job.active_slot = None
            job.finished_at = now
            job.heartbeat_at = now
            job.error_message = (
                f"{SYNC_METADATA[model][0]}运行超时，"
                f"已达到最大自动尝试次数（{max_attempts}）"
            )
        else:
            job.status = "queued"
            job.claimed_at = None
            job.heartbeat_at = None
            job.finished_at = None
            job.error_message = f"{SYNC_METADATA[model][0]}运行超时，已自动重试"
        job.claim_token = None
        recovered += 1
    return recovered


def _recover_stale_jobs(
    database: Database,
    stale_after: timedelta = timedelta(minutes=30),
    queue: str = "all",
    max_attempts: int = 3,
) -> int:
    cutoff = datetime.utcnow() - stale_after
    recovered = 0
    with database.session() as session:
        if queue in {"all", "batch"}:
            recovered += _recover_batch_jobs(session, cutoff, max_attempts)
        if queue in {"all", "purchase-sync"}:
            recovered += _recover_sync_jobs(
                session, PurchaseSyncJob, cutoff, max_attempts
            )
        if queue in {"all", "inbound-sync"}:
            recovered += _recover_sync_jobs(
                session, SelfOperatedInboundSyncJob, cutoff, max_attempts
            )
        session.commit()
    return recovered


def recover_stale_jobs(
    database_url: str,
    stale_after: timedelta = timedelta(minutes=30),
    queue: str = "all",
    max_attempts: int = 3,
) -> int:
    if queue not in WORKER_QUEUES:
        raise ValueError(f"未知 Worker 队列：{queue}")
    if max_attempts <= 0:
        raise ValueError("最大尝试次数必须大于 0")
    database = Database(database_url)
    try:
        return _recover_stale_jobs(
            database,
            stale_after=stale_after,
            queue=queue,
            max_attempts=max_attempts,
        )
    finally:
        database.dispose()


def _watch_stale_jobs(
    database: Database,
    stale_after: timedelta,
    stop_event: Event,
    queue: str = "all",
    max_attempts: int = 3,
) -> None:
    while not stop_event.wait(60):
        try:
            recovered = _recover_stale_jobs(
                database,
                stale_after=stale_after,
                queue=queue,
                max_attempts=max_attempts,
            )
            if recovered:
                LOGGER.info(
                    "已处理 %s 个超时任务 queue=%s",
                    recovered,
                    queue,
                )
        except Exception:
            LOGGER.exception("任务恢复扫描失败 queue=%s", queue)
