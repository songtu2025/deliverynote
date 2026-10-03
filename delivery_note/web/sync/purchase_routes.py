from typing import Annotated

from fastapi import Depends, FastAPI, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...excel_io import read_purchase_workbook
from ...gerpgo import GerpgoClient, GerpgoError
from ..dependencies import RequestDependencies
from ..models import PurchaseSyncJob, User
from ..serializers import utc_isoformat
from .queries import candidate_preview, get_sync_job
from .commands import SyncCommands
from .issues import download_purchase_sync_issues as purchase_issues_download
from .views import sync_job_json


def register_purchase_routes(
    app: FastAPI, dependencies: RequestDependencies, commands: SyncCommands
) -> None:
    current_user = dependencies.current_user
    get_session = dependencies.get_session
    storage = commands.storage

    @app.get("/api/purchase-sync")
    def purchase_sync_status(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        configured = True
        try:
            GerpgoClient.from_config(storage)
        except GerpgoError:
            configured = False
        job = session.scalar(
            select(PurchaseSyncJob).order_by(PurchaseSyncJob.id.desc())
        )
        return {
            "configured": configured,
            "job": sync_job_json(job, utc_isoformat) if job else None,
        }

    @app.post(
        "/api/purchase-sync",
        status_code=status.HTTP_201_CREATED,
    )
    def start_purchase_sync(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = commands.start_purchase_sync(user, session)
        return sync_job_json(job, utc_isoformat)

    @app.get("/api/purchase-sync/{job_id}/issues/download")
    def download_purchase_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return purchase_issues_download(job_id, session)

    @app.get("/api/purchase-sync/{job_id}/issues")
    def list_purchase_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = get_sync_job(session, PurchaseSyncJob, job_id)
        return job.issues or []

    @app.get("/api/purchase-sync/{job_id}/preview")
    def preview_purchase_sync(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        job = get_sync_job(session, PurchaseSyncJob, job_id)
        return candidate_preview(session, job, limit, read_purchase_workbook)
