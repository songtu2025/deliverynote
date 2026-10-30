"""批次采购快照的加载、刷新与固定版本分页读取。"""

from typing import Annotated, Any
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Query, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .job_routes import JobQueue
from .models import User
from .purchase_snapshot import (
    PURCHASE_SNAPSHOT_KIND,
    SNAPSHOT_PAGE_SIZE,
    require_snapshot_batch,
    snapshot_job,
    snapshot_view,
)


class SnapshotRequest(BaseModel):
    refresh: bool = False


def register_purchase_snapshot_routes(
    app: FastAPI, dependencies: RequestDependencies, storage: Path, queue_job: JobQueue
) -> None:
    path = "/api/self-operated-batches/{batch_id}/purchase-snapshot"

    @app.get(path, response_model=None)
    def read_snapshot(
        batch_id: int,
        _user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=SNAPSHOT_PAGE_SIZE)] = SNAPSHOT_PAGE_SIZE,
        snapshot_id: str = "",
    ) -> dict[str, Any]:
        batch = dependencies.get_batch_or_404(batch_id, session)
        require_snapshot_batch(session, batch)
        return snapshot_view(
            session, batch, storage, page=(offset, limit), snapshot_id=snapshot_id
        )

    @app.post(path, response_model=None)
    def load_snapshot(
        batch_id: int,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
        response: Response,
        body: Annotated[SnapshotRequest | None, Body()] = None,
    ) -> dict[str, Any]:
        batch = dependencies.get_batch_or_404(batch_id, session, for_update=True)
        require_snapshot_batch(session, batch)
        try:
            job = queue_job(
                batch,
                PURCHASE_SNAPSHOT_KIND,
                user,
                session,
                refresh=bool(body and body.refresh),
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            recovered = snapshot_job(session, batch_id)
            if recovered is None:
                raise
            job = recovered
        response.status_code = 202 if job.status in {"queued", "running"} else 200
        return snapshot_view(session, batch, storage)
