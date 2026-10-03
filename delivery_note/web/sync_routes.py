from datetime import datetime
from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..excel_io import read_purchase_workbook, read_self_operated_inbound_workbook
from ..gerpgo import GerpgoClient, GerpgoError
from .models import InputVersion, PurchaseSyncJob, SelfOperatedInboundSyncJob, User
from .sync.views import sync_job_json
from .sync.queries import get_sync_job, candidate_preview
from .sync.issues import (
    download_purchase_sync_issues as purchase_issues_download,
    download_self_operated_inbound_sync_issues as inbound_issues_download,
    _self_operated_inbound_sync_issues,
)


def register_sync_routes(
    app: FastAPI,
    storage: Path,
    *,
    get_session: Callable,
    current_user: Callable,
    audit: Callable,
    version_json: Callable,
    utc_isoformat: Callable[[datetime], str],
) -> None:
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
        try:
            GerpgoClient.from_config(storage)
        except GerpgoError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        running = session.scalar(
            select(PurchaseSyncJob).where(PurchaseSyncJob.active_slot == 1)
        )
        if running is not None:
            raise HTTPException(status_code=409, detail="已有采购同步正在运行")

        active_versions = {
            version.kind: version
            for version in session.scalars(
                select(InputVersion).where(
                    InputVersion.active.is_(True),
                    InputVersion.kind.in_(("purchase", "product", "supplier")),
                )
            )
        }
        product = active_versions.get("product")
        supplier = active_versions.get("supplier")
        job = PurchaseSyncJob(
            status="queued",
            active_slot=1,
            created_by=user.id,
            base_version_id=(
                active_versions["purchase"].id
                if "purchase" in active_versions
                else None
            ),
            product_version_id=product.id if product else None,
            supplier_version_id=supplier.id if supplier else None,
        )
        session.add(job)
        try:
            session.flush()
            audit(
                session,
                user.id,
                "start_purchase_sync",
                "purchase_sync_job",
                job.id,
            )
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="已有采购同步正在运行",
            ) from error
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
        job = session.get(PurchaseSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="采购同步任务不存在")
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

    @app.get("/api/self-operated-inbound-sync")
    def self_operated_inbound_sync_status(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        configured = True
        try:
            GerpgoClient.from_config(storage)
        except GerpgoError:
            configured = False
        job = session.scalar(
            select(SelfOperatedInboundSyncJob).order_by(
                SelfOperatedInboundSyncJob.id.desc()
            )
        )
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
    )
    def start_self_operated_inbound_sync(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        try:
            GerpgoClient.from_config(storage)
        except GerpgoError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        running = session.scalar(
            select(SelfOperatedInboundSyncJob).where(
                SelfOperatedInboundSyncJob.active_slot == 1
            )
        )
        if running is not None:
            raise HTTPException(status_code=409, detail="已有待入库同步正在运行")
        active_version = session.scalar(
            select(InputVersion).where(
                InputVersion.kind == "self_operated_inbound",
                InputVersion.active.is_(True),
            )
        )
        job = SelfOperatedInboundSyncJob(
            status="queued",
            active_slot=1,
            created_by=user.id,
            base_version_id=active_version.id if active_version else None,
        )
        session.add(job)
        try:
            session.flush()
            audit(
                session,
                user.id,
                "start_self_operated_inbound_sync",
                "self_operated_inbound_sync_job",
                job.id,
            )
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="已有待入库同步正在运行",
            ) from error
        return sync_job_json(job, utc_isoformat)

    @app.get("/api/self-operated-inbound-sync/{job_id}/issues/download")
    def download_self_operated_inbound_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return inbound_issues_download(job_id, session)

    @app.get("/api/self-operated-inbound-sync/{job_id}/issues")
    def list_self_operated_inbound_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(SelfOperatedInboundSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="待入库同步任务不存在")
        return _self_operated_inbound_sync_issues(session, job)

    @app.get("/api/self-operated-inbound-sync/{job_id}/preview")
    def preview_self_operated_inbound_sync(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        job = get_sync_job(session, SelfOperatedInboundSyncJob, job_id)
        return candidate_preview(
            session, job, limit, read_self_operated_inbound_workbook
        )

    @app.post("/api/self-operated-inbound-sync/{job_id}/activate")
    def activate_self_operated_inbound_sync(
        job_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(SelfOperatedInboundSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="待入库同步任务不存在")
        if job.status != "succeeded" or job.candidate_version_id is None:
            raise HTTPException(status_code=409, detail="候选版本尚未生成")
        version = session.get(InputVersion, job.candidate_version_id)
        if version is None or version.kind != "self_operated_inbound":
            raise HTTPException(status_code=409, detail="候选版本不存在")
        try:
            current_versions = list(
                session.scalars(
                    select(InputVersion)
                    .where(InputVersion.kind == "self_operated_inbound")
                    .order_by(InputVersion.id)
                    .with_for_update()
                )
            )
            for current in current_versions:
                current.active = False
            session.flush()
            version.active = True
            audit(
                session,
                user.id,
                "activate_self_operated_inbound_sync",
                "input_version",
                version.id,
                {"job_id": job.id},
            )
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="输入版本发生并发冲突，请刷新后重试",
            ) from error
        return version_json(version)
