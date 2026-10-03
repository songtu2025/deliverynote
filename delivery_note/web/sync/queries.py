from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import InputVersion, PurchaseSyncJob, SelfOperatedInboundSyncJob
from .views import _sync_preview_json

SyncJob = TypeVar("SyncJob", PurchaseSyncJob, SelfOperatedInboundSyncJob)


def get_sync_job(session: Session, model: type[SyncJob], job_id: int) -> SyncJob:
    job = session.get(model, job_id)
    if job is None:
        title = "采购同步" if model is PurchaseSyncJob else "待入库同步"
        raise HTTPException(status_code=404, detail=f"{title}任务不存在")
    return job


def candidate_preview(
    session: Session,
    job: PurchaseSyncJob | SelfOperatedInboundSyncJob,
    limit: int,
    reader: Callable[[Path], pd.DataFrame],
) -> dict:
    version = (
        session.get(InputVersion, job.candidate_version_id)
        if job.candidate_version_id is not None
        else None
    )
    if version is None:
        raise HTTPException(status_code=409, detail="候选版本尚未生成")
    try:
        frame = reader(Path(version.storage_path))
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=409, detail=f"候选版本无法读取：{error}"
        ) from error
    return _sync_preview_json(frame, limit)
