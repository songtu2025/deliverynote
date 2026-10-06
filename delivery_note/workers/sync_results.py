from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..web.database import Database
from ..web.models import (
    AuditLog,
    InputVersion,
)
from .leases import JobContext, LostJobLeaseError

from .sync_models import SYNC_METADATA, SyncJob, SyncJobModel

LOGGER = logging.getLogger("delivery_note.worker")


def _discard_unregistered_sync_candidate(database: Database, path: Path) -> None:
    """仅清理已确认没有版本引用的当前同步候选文件。"""
    try:
        with database.session() as session:
            registered = session.scalar(
                select(InputVersion.id).where(InputVersion.storage_path == str(path))
            )
    except Exception:
        LOGGER.warning("无法核验同步候选文件引用，已保留文件：%s", path, exc_info=True)
        return
    if registered is None:
        path.unlink(missing_ok=True)


@dataclass(frozen=True)
class SyncCandidate:
    """待登记的未启用候选版本及其差异摘要。"""

    kind: str
    name: str
    original_name: str
    path: Path
    difference: dict[str, Any]


def _load_sync_base_path(
    database: Database, model: SyncJobModel, job_id: int
) -> Path | None:
    with database.session() as session:
        job = cast(SyncJob | None, session.get(model, job_id))
        if job is None:
            raise RuntimeError(f"{SYNC_METADATA[model][0]}任务不存在")
        base_version = (
            session.get(InputVersion, job.base_version_id)
            if job.base_version_id is not None
            else None
        )
        return Path(base_version.storage_path) if base_version else None


def _load_owned_sync_job(
    session: Session, model: SyncJobModel, context: JobContext
) -> SyncJob:
    """在同步结果事务中锁定并核验当前租约所属任务。"""
    job = cast(
        SyncJob | None,
        session.scalar(
            select(model).where(model.id == context.job_id).with_for_update()
        ),
    )
    if job is None or job.status != "running" or job.claim_token != context.claim_token:
        raise LostJobLeaseError(f"{SYNC_METADATA[model][0]}任务租约已失效")
    return job


def _block_sync(context: JobContext, model: SyncJobModel, issue_count: int) -> None:
    context.before_finalize()
    with context.database.session() as session:
        job = _load_owned_sync_job(session, model, context)
        now = datetime.utcnow()
        job.status = "blocked"
        job.active_slot = None
        job.finished_at = now
        job.heartbeat_at = now
        job.claim_token = None
        session.add(
            AuditLog(
                user_id=job.created_by,
                action=f"{SYNC_METADATA[model][2]}_blocked",
                entity_type=SYNC_METADATA[model][1],
                entity_id=str(job.id),
                details={"issue_count": issue_count},
            )
        )
        session.commit()


def _publish_sync_candidate(
    context: JobContext,
    model: SyncJobModel,
    candidate: SyncCandidate,
    audit_details: dict[str, Any],
) -> None:
    context.before_finalize()
    with context.database.session() as session:
        job = _load_owned_sync_job(session, model, context)
        version = InputVersion(
            kind=candidate.kind,
            name=candidate.name,
            original_name=candidate.original_name,
            storage_path=str(candidate.path),
            active=False,
            created_by=job.created_by,
        )
        session.add(version)
        session.flush()
        now = datetime.utcnow()
        job.status = "succeeded"
        job.active_slot = None
        job.candidate_version_id = version.id
        job.diff = candidate.difference
        job.finished_at = now
        job.heartbeat_at = now
        job.claim_token = None
        session.add(
            AuditLog(
                user_id=job.created_by,
                action=f"{SYNC_METADATA[model][2]}_succeeded",
                entity_type=SYNC_METADATA[model][1],
                entity_id=str(job.id),
                details={"candidate_version_id": version.id, **audit_details},
            )
        )
        session.commit()


def _fail_sync_job(
    database: Database, model: SyncJobModel, job_id: int, claim_token: str, message: str
) -> None:
    with database.session() as session:
        job = cast(
            SyncJob | None,
            session.scalar(select(model).where(model.id == job_id).with_for_update()),
        )
        if job is None or job.status != "running" or job.claim_token != claim_token:
            return
        now = datetime.utcnow()
        job.status = "failed"
        job.active_slot = None
        job.error_message = message
        job.finished_at = now
        job.heartbeat_at = now
        job.claim_token = None
        session.add(
            AuditLog(
                user_id=job.created_by,
                action=f"{SYNC_METADATA[model][2]}_failed",
                entity_type=SYNC_METADATA[model][1],
                entity_id=str(job.id),
                details={"error": message},
            )
        )
        session.commit()
