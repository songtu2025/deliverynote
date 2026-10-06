from pathlib import Path
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...gerpgo import GerpgoClient, GerpgoError
from ..models import InputVersion, PurchaseSyncJob, SelfOperatedInboundSyncJob, User


class SyncCommands:
    """创建同步任务并事务性启用待入库候选版本。"""

    def __init__(self, storage: Path, audit: Callable[..., None]) -> None:
        self.storage = storage
        self.audit = audit

    def is_configured(self) -> bool:
        try:
            GerpgoClient.from_config(self.storage)
        except GerpgoError:
            return False
        return True

    def start_purchase_sync(self, user: User, session: Session) -> PurchaseSyncJob:
        try:
            GerpgoClient.from_config(self.storage)
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
            self.audit(
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
        return job

    def start_self_operated_inbound_sync(
        self, user: User, session: Session
    ) -> SelfOperatedInboundSyncJob:
        try:
            GerpgoClient.from_config(self.storage)
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
            self.audit(
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
        return job

    def activate_self_operated_inbound_sync(
        self, job_id: int, user: User, session: Session
    ) -> InputVersion:
        job = session.get(SelfOperatedInboundSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="待入库同步任务不存在")
        if job.status != "succeeded" or job.candidate_version_id is None:
            raise HTTPException(status_code=409, detail="候选版本尚未生成")
        version = session.get(InputVersion, job.candidate_version_id)
        if version is None or version.kind != "self_operated_inbound":
            raise HTTPException(status_code=409, detail="候选版本不存在")
        if not Path(version.storage_path).is_file():
            raise HTTPException(status_code=409, detail="候选版本文件不存在")
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
            self.audit(
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
        return version
