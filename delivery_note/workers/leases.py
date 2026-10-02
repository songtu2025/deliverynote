from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from types import TracebackType
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from ..web.database import Database
from ..web.models import Batch, Job
from .sync_models import SYNC_METADATA, SyncJob, SyncJobModel

WORKER_QUEUES = ("all", "batch", "purchase-sync", "inbound-sync")
LEASE_HEARTBEAT_INTERVAL_SECONDS = 30.0
LOGGER = logging.getLogger("delivery_note.worker")


class LostJobLeaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobContext:
    """任务执行和最终保存共用的数据库与租约上下文。"""

    database: Database
    job_id: int
    claim_token: str
    before_finalize: Callable[[], None]


class LeaseKeeper:
    """业务调用阻塞时，使用独立会话周期续租当前任务。"""

    def __init__(
        self,
        heartbeat: Callable[[], None],
        queue: str,
        job_id: int,
        claim_token: str,
    ) -> None:
        self._heartbeat = heartbeat
        self._queue = queue
        self._job_id = job_id
        self._claim_prefix = claim_token[:8]
        self._stop_event = Event()
        self._error: Exception | None = None
        self._stopped = False
        self._thread = Thread(
            target=self._run,
            name=f"delivery-note-lease-{queue}-{job_id}",
            daemon=True,
        )

    def _run(self) -> None:
        while not self._stop_event.wait(LEASE_HEARTBEAT_INTERVAL_SECONDS):
            try:
                self._heartbeat()
            except Exception as error:
                self._error = error
                LOGGER.exception(
                    "Worker 租约续期失败 queue=%s job_id=%s claim=%s",
                    self._queue,
                    self._job_id,
                    self._claim_prefix,
                )
                return

    def __enter__(self) -> LeaseKeeper:
        self._thread.start()
        return self

    def stop(self) -> None:
        if not self._stopped:
            self._stop_event.set()
            self._thread.join()
            self._stopped = True
        if self._error is not None:
            raise self._error

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if exception_type is None:
            self.stop()
            return
        if not self._stopped:
            self._stop_event.set()
            self._thread.join()
            self._stopped = True


def _claim_job(database: Database) -> tuple[int, int, str, str] | None:
    with database.session() as session:
        job = session.scalar(
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        now = datetime.utcnow()
        claim_token = uuid4().hex
        job.status = "running"
        job.claim_token = claim_token
        job.attempts += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.error_message = None
        batch = session.get(Batch, job.batch_id)
        if batch is None:
            raise RuntimeError("任务关联的批次不存在")
        if job.kind == "compute":
            batch.status = "running"
            batch.error_message = None
        session.commit()
        return job.id, job.batch_id, job.kind, claim_token


def _heartbeat(database: Database, job_id: int, claim_token: str) -> None:
    with database.session() as session:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "running",
                    Job.claim_token == claim_token,
                )
                .values(heartbeat_at=datetime.utcnow())
            ),
        )
        session.commit()
        if result.rowcount != 1:
            raise LostJobLeaseError("任务租约已失效")


def _claim_sync_job(database: Database, model: SyncJobModel) -> tuple[int, str] | None:
    with database.session() as session:
        job = cast(
            SyncJob | None,
            session.scalar(
                select(model)
                .where(model.status == "queued")
                .order_by(model.id)
                .with_for_update(skip_locked=True)
            ),
        )
        if job is None:
            return None
        now = datetime.utcnow()
        claim_token = uuid4().hex
        job.status = "running"
        job.claim_token = claim_token
        job.attempts += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.error_message = None
        session.commit()
        return job.id, claim_token


def _sync_heartbeat(
    database: Database,
    model: SyncJobModel,
    job_id: int,
    claim_token: str,
    **values: Any,
) -> None:
    with database.session() as session:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(model)
                .where(
                    model.id == job_id,
                    model.status == "running",
                    model.claim_token == claim_token,
                )
                .values(heartbeat_at=datetime.utcnow(), **values)
            ),
        )
        session.commit()
        if result.rowcount != 1:
            raise LostJobLeaseError(f"{SYNC_METADATA[model][0]}任务租约已失效")
