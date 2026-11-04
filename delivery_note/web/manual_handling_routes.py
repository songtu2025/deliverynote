"""自营仓本批追加额度与线下处理接口。"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .batch_views import batch_json
from .dependencies import RequestDependencies
from .exception_views import _exception_json
from .job_routes import AuditCallback, JobQueue
from .manual_handling import prepare_recompute, replace_input, save_offline
from .models import BatchFile, ExceptionRecord, SelfOperatedBatch, User


class OfflinePayload(BaseModel):
    quantity: int = Field(ge=0, strict=True)
    note: str = ""

    @model_validator(mode="after")
    def require_note(self) -> "OfflinePayload":
        self.note = self.note.strip()
        if self.quantity and not self.note:
            raise ValueError("请填写线下处理备注")
        return self


class AllowancePayload(BaseModel):
    supplier_code: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    full_site: str = Field(min_length=1)
    quantity: int = Field(ge=0, strict=True)
    reason: str = ""

    @model_validator(mode="after")
    def require_reason(self) -> "AllowancePayload":
        self.reason = self.reason.strip()
        if self.quantity and not self.reason:
            raise ValueError("请填写追加超收原因")
        return self


def register_manual_handling_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    queue_job: JobQueue,
    audit: AuditCallback,
) -> None:
    @app.put("/api/batches/{batch_id}/manual-allowances", response_model=None)
    def save_allowance(
        batch_id: int,
        payload: AllowancePayload,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, object]:
        batch = dependencies.get_batch_or_404(batch_id, session, for_update=True)
        profile = session.get(SelfOperatedBatch, batch.id)
        if profile is None:
            raise HTTPException(status_code=400, detail="仅自营仓批次可以追加超收")
        identity = {
            key: getattr(payload, key) for key in ("supplier_code", "sku", "full_site")
        }
        source = session.scalar(
            select(BatchFile)
            .join(ExceptionRecord)
            .where(
                BatchFile.batch_id == batch.id,
                BatchFile.supplier_code == payload.supplier_code,
                ExceptionRecord.sku == payload.sku,
                ExceptionRecord.full_site == payload.full_site,
            )
        )
        # 已追加后待处理可能消失，仍须允许按原有键修改或撤销。
        previous = next(
            (
                item
                for item in (profile.manual_handling or {}).get("allowances", [])
                if all(item[key] == value for key, value in identity.items())
            ),
            None,
        )
        if source is None and previous is None:
            raise HTTPException(
                status_code=400, detail="追加额度必须对应本批待处理记录"
            )
        supplier_name = (
            source.supplier_name if source else (previous or {})["supplier_name"]
        )
        prepare_recompute(session, batch)
        replace_input(
            profile,
            "allowances",
            identity,
            {
                "supplier_name": supplier_name,
                "quantity": payload.quantity,
                "reason": payload.reason,
            },
            user.id,
        )
        audit(
            session,
            user.id,
            "save_manual_allowance",
            "batch",
            batch.id,
            payload.model_dump(),
        )
        queue_job(batch, "compute", user, session)
        batch.status = "queued"
        session.commit()
        return batch_json(batch, session)

    @app.put("/api/exceptions/{exception_id}/offline-handling", response_model=None)
    def offline_handling(
        exception_id: int,
        payload: OfflinePayload,
        user: Annotated[User, Depends(dependencies.current_user)],
        session: Annotated[Session, Depends(dependencies.get_session)],
    ) -> dict[str, object]:
        source = session.scalar(
            select(BatchFile)
            .join(ExceptionRecord)
            .where(ExceptionRecord.id == exception_id)
        )
        if source is None:
            raise HTTPException(status_code=404, detail="待处理记录不存在")
        batch = dependencies.get_batch_or_404(source.batch_id, session, for_update=True)
        profile = session.get(SelfOperatedBatch, batch.id)
        if profile is None:
            raise HTTPException(
                status_code=400, detail="仅自营仓待处理记录可以线下处理"
            )
        record = session.scalar(
            select(ExceptionRecord)
            .where(ExceptionRecord.id == exception_id)
            .with_for_update()
        )
        if record is None:
            raise HTTPException(
                status_code=409, detail="待处理记录已变化，请刷新后重试"
            )
        save_offline(session, batch, record, payload.quantity, payload.note)
        replace_input(
            profile,
            "offline",
            {
                "batch_file_id": source.id,
                "sku": record.sku,
                "full_site": record.full_site,
            },
            payload.model_dump(),
            user.id,
        )
        audit(
            session,
            user.id,
            "save_offline_handling",
            "exception",
            record.id,
            payload.model_dump(),
        )
        session.commit()
        return _exception_json(record, [], self_operated=True)
