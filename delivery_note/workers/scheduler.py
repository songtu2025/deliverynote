from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..web.database import Database
from ..web.models import (
    AuditLog,
    Batch,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)
from .compute_delivery import _execute_compute
from .export_delivery import _execute_export
from .leases import (
    WORKER_QUEUES,
    JobContext,
    LeaseKeeper,
    _claim_job,
    _claim_sync_job,
    _heartbeat,
    _sync_heartbeat,
)
from .sync_inbound import _execute_self_operated_inbound_sync
from .sync_purchase import _execute_purchase_sync
from .sync_results import _fail_sync_job

LOGGER = logging.getLogger("delivery_note.worker")


def _fail_job(
    database: Database,
    job_id: int,
    claim_token: str,
    message: str,
) -> None:
    with database.session() as session:
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.claim_token != claim_token:
            return
        job.status = "failed"
        job.error_message = message
        job.finished_at = datetime.utcnow()
        job.heartbeat_at = job.finished_at
        job.claim_token = None
        batch = session.get(Batch, job.batch_id)
        if batch is not None:
            batch.error_message = message
            if job.kind == "compute":
                batch.status = "failed"
        session.add(
            AuditLog(
                user_id=None,
                action=f"worker_{job.kind}_failed",
                entity_type="job",
                entity_id=str(job.id),
                details={"error": message},
            )
        )
        session.commit()


def _run_batch_job(
    database: Database,
    claimed: tuple[int, int, str, str],
    storage_root: Path | str,
) -> int:
    job_id, batch_id, kind, claim_token = claimed
    try:
        with LeaseKeeper(
            lambda: _heartbeat(database, job_id, claim_token),
            "batch",
            job_id,
            claim_token,
        ) as lease_keeper:
            if kind == "compute":
                _execute_compute(
                    database,
                    job_id,
                    batch_id,
                    claim_token,
                    lease_keeper.stop,
                )
            elif kind == "export":
                _execute_export(
                    JobContext(database, job_id, claim_token, lease_keeper.stop),
                    batch_id,
                    Path(storage_root),
                )
            else:
                raise RuntimeError(f"未知任务类型：{kind}")
    except Exception as error:
        LOGGER.exception(
            "Worker 任务执行失败 queue=batch job_id=%s claim=%s",
            job_id,
            claim_token[:8],
        )
        _fail_job(database, job_id, claim_token, str(error))
    return job_id


def _run_purchase_job(
    database: Database,
    sync_claimed: tuple[int, str],
    storage_root: Path | str,
) -> int:
    job_id, claim_token = sync_claimed
    try:
        with LeaseKeeper(
            lambda: _sync_heartbeat(
                database,
                PurchaseSyncJob,
                job_id,
                claim_token,
            ),
            "purchase-sync",
            job_id,
            claim_token,
        ) as lease_keeper:
            _execute_purchase_sync(
                JobContext(database, job_id, claim_token, lease_keeper.stop),
                Path(storage_root),
            )
    except Exception as error:
        LOGGER.exception(
            "Worker 任务执行失败 queue=purchase-sync job_id=%s claim=%s",
            job_id,
            claim_token[:8],
        )
        _fail_sync_job(database, PurchaseSyncJob, job_id, claim_token, str(error))
    return job_id


def _run_inbound_job(
    database: Database,
    inbound_sync_claimed: tuple[int, str],
    storage_root: Path | str,
) -> int:
    job_id, claim_token = inbound_sync_claimed
    try:
        with LeaseKeeper(
            lambda: _sync_heartbeat(
                database,
                SelfOperatedInboundSyncJob,
                job_id,
                claim_token,
            ),
            "inbound-sync",
            job_id,
            claim_token,
        ) as lease_keeper:
            _execute_self_operated_inbound_sync(
                JobContext(database, job_id, claim_token, lease_keeper.stop),
                Path(storage_root),
            )
    except Exception as error:
        LOGGER.exception(
            "Worker 任务执行失败 queue=inbound-sync job_id=%s claim=%s",
            job_id,
            claim_token[:8],
        )
        _fail_sync_job(
            database,
            SelfOperatedInboundSyncJob,
            job_id,
            claim_token,
            str(error),
        )
    return job_id


def _run_once(
    database: Database,
    storage_root: Path | str,
    queue: str = "all",
) -> int | None:
    if queue not in WORKER_QUEUES:
        raise ValueError(f"未知 Worker 队列：{queue}")
    claimed = _claim_job(database) if queue in {"all", "batch"} else None
    if claimed is not None:
        return _run_batch_job(database, claimed, storage_root)
    if queue == "batch":
        return None
    sync_claimed = (
        _claim_sync_job(database, PurchaseSyncJob)
        if queue in {"all", "purchase-sync"}
        else None
    )
    if sync_claimed is not None:
        return _run_purchase_job(database, sync_claimed, storage_root)
    if queue == "purchase-sync":
        return None
    inbound_sync_claimed = _claim_sync_job(database, SelfOperatedInboundSyncJob)
    if inbound_sync_claimed is None:
        return None
    return _run_inbound_job(database, inbound_sync_claimed, storage_root)


def run_once(
    database_url: str,
    storage_root: Path | str,
    queue: str = "all",
) -> int | None:
    if queue not in WORKER_QUEUES:
        raise ValueError(f"未知 Worker 队列：{queue}")
    database = Database(database_url)
    try:
        return _run_once(database, storage_root, queue)
    finally:
        database.dispose()
