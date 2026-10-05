from typing import Annotated

from fastapi import Depends, FastAPI, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...excel_io import read_self_operated_inbound_workbook
from ..dependencies import RequestDependencies
from ..models import InputVersion, SelfOperatedInboundSyncJob, User
from ..serializers import utc_isoformat, version_json
from .queries import candidate_preview, get_sync_job, latest_sync_job
from .commands import SyncCommands
from .issues import (
    download_self_operated_inbound_sync_issues as inbound_issues_download,
    _self_operated_inbound_sync_issues,
)
from .views import sync_job_json


def register_inbound_routes(
    app: FastAPI, dependencies: RequestDependencies, commands: SyncCommands
) -> None:
    current_user = dependencies.current_user
    get_session = dependencies.get_session

    @app.get("/api/self-operated-inbound-sync", response_model=None)
    def self_operated_inbound_sync_status(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        configured = commands.is_configured()
        job = latest_sync_job(session, SelfOperatedInboundSyncJob)
        active_version = session.scalar(
            select(InputVersion).where(
                InputVersion.kind == "self_operated_inbound",
                InputVersion.active.is_(True),
            )
        )
        return {
            "configured": configured,
            "active_version": (
                version_json(active_version) if active_version else None
            ),
            "job": (sync_job_json(job, utc_isoformat) if job else None),
        }

    @app.post(
        "/api/self-operated-inbound-sync",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def start_self_operated_inbound_sync(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        job = commands.start_self_operated_inbound_sync(user, session)
        return sync_job_json(job, utc_isoformat)

    @app.get(
        "/api/self-operated-inbound-sync/{job_id}/issues/download", response_model=None
    )
    def download_self_operated_inbound_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StreamingResponse:
        return inbound_issues_download(job_id, session)

    @app.get("/api/self-operated-inbound-sync/{job_id}/issues", response_model=None)
    def list_self_operated_inbound_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[dict[str, object]]:
        job = get_sync_job(session, SelfOperatedInboundSyncJob, job_id)
        return _self_operated_inbound_sync_issues(session, job)

    @app.get("/api/self-operated-inbound-sync/{job_id}/preview", response_model=None)
    def preview_self_operated_inbound_sync(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, object]:
        job = get_sync_job(session, SelfOperatedInboundSyncJob, job_id)
        return candidate_preview(
            session, job, limit, read_self_operated_inbound_workbook
        )

    @app.post("/api/self-operated-inbound-sync/{job_id}/activate", response_model=None)
    def activate_self_operated_inbound_sync(
        job_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        version = commands.activate_self_operated_inbound_sync(job_id, user, session)
        return version_json(version)
