from typing import Annotated

from fastapi import Depends, FastAPI, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...excel_io import read_purchase_workbook
from ..dependencies import RequestDependencies
from ..models import PurchaseSyncJob, User
from ..serializers import utc_isoformat
from .queries import candidate_preview, get_sync_job, latest_sync_job
from .commands import SyncCommands
from .issues import download_purchase_sync_issues as purchase_issues_download
from .views import sync_job_json


def register_purchase_routes(
    app: FastAPI, dependencies: RequestDependencies, commands: SyncCommands
) -> None:
    current_user = dependencies.current_user
    get_session = dependencies.get_session

    @app.get("/api/purchase-sync", response_model=None)
    def purchase_sync_status(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        configured = commands.is_configured()
        job = latest_sync_job(session, PurchaseSyncJob)
        return {
            "configured": configured,
            "job": sync_job_json(job, utc_isoformat) if job else None,
        }

    @app.post(
        "/api/purchase-sync",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def start_purchase_sync(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        job = commands.start_purchase_sync(user, session)
        return sync_job_json(job, utc_isoformat)

    @app.get("/api/purchase-sync/{job_id}/issues/download", response_model=None)
    def download_purchase_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StreamingResponse:
        return purchase_issues_download(job_id, session)

    @app.get("/api/purchase-sync/{job_id}/issues", response_model=None)
    def list_purchase_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[dict[str, object]]:
        job = get_sync_job(session, PurchaseSyncJob, job_id)
        return job.issues or []

    @app.get("/api/purchase-sync/{job_id}/preview", response_model=None)
    def preview_purchase_sync(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, object]:
        job = get_sync_job(session, PurchaseSyncJob, job_id)
        return candidate_preview(session, job, limit, read_purchase_workbook)
