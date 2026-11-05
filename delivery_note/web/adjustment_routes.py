"""自营仓追加额度与站点选择统一保存，只启动一次整批重算。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .batch_views import batch_json
from .dependencies import RequestDependencies
from .job_routes import AuditCallback, JobQueue
from .manual_handling import prepare_recompute, recompute_disabled_reason
from .manual_handling_routes import (
    AllowancePayload,
    allowance_inputs,
    save_allowance_inputs,
)
from .models import SelfOperatedBatch, User
from .receipt_routes import (
    ReceiptSitePayload,
    queue_receipt_preflight,
    save_receipt_site,
    validate_receipt_site,
)


class SiteAdjustment(ReceiptSitePayload):
    file_id: int


class AdjustmentPayload(BaseModel):
    allowances: list[AllowancePayload] = Field(default_factory=list)
    sites: list[SiteAdjustment] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def require_changes(self) -> "AdjustmentPayload":
        if not self.allowances and not self.sites:
            raise ValueError("至少需要一项调整")
        return self


def register_adjustment_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    queue_job: JobQueue,
    audit: AuditCallback,
) -> None:
    @app.put("/api/batches/{batch_id}/adjustments", response_model=None)
    def save_adjustments(
        batch_id: int,
        payload: AdjustmentPayload,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, object]:
        batch = dependencies.get_batch_or_404(batch_id, session, for_update=True)
        profile = session.get(SelfOperatedBatch, batch.id)
        if profile is None:
            raise HTTPException(status_code=400, detail="仅自营仓批次可以调整入库")
        reason = recompute_disabled_reason(session, batch)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        items = [
            item.model_copy(update={"reason": payload.reason.strip()})
            if payload.reason is not None
            else item
            for item in payload.allowances
        ]
        inputs = allowance_inputs(session, batch.id, profile, items)
        sites = [
            validate_receipt_site(session, batch.id, item.file_id, item)
            for item in payload.sites
        ]
        site_keys = [
            (item.file_id, item.sku, item.original_site) for item in payload.sites
        ]
        if len(site_keys) != len(set(site_keys)):
            raise HTTPException(
                status_code=400, detail="不可重复指定同一文件、SKU 和原始站点"
            )
        if not sites:
            prepare_recompute(session, batch)
        save_allowance_inputs(session, profile, inputs, user.id, audit)
        for source, item in zip(sites, payload.sites):
            save_receipt_site(source, item)
            audit(
                session,
                user.id,
                "choose_receipt_site",
                "batch_file",
                source.id,
                item.model_dump(exclude={"file_id"}),
            )
        if sites:
            return queue_receipt_preflight(
                session, batch, user, queue_job, allow_succeeded=True
            )
        queue_job(batch, "compute", user, session)
        batch.status = "queued"
        session.commit()
        return batch_json(batch, session)
