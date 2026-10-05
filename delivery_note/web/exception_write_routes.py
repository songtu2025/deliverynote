from collections.abc import Callable, Iterator
from typing import Annotated

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..application import SplitPart, project_split
from ..exception_reasons import exception_reason_code
from .caches import PositionFrameCache
from .dependencies import BatchLookup
from .exception_views import ExceptionRenderer, PositionLookup, SplitLookup
from .models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    SelfOperatedBatch,
    SelfOperatedSiteResolution,
    SplitRecord,
    User,
)
from .schemas import SelfOperatedSiteResolutionPayload, SplitPayload
from .serializers import exception_row


def register_exception_write_routes(
    app: FastAPI,
    *,
    get_session: Callable[[], Iterator[Session]],
    current_user: Callable[..., User],
    get_batch_or_404: BatchLookup,
    position_frame_cache: PositionFrameCache,
    exception_position_values: PositionLookup,
    split_records_by_exception: SplitLookup,
    exception_json: ExceptionRenderer,
    queue_job: Callable[[Batch, str, User, Session], Job],
    job_json: Callable[[Job], dict[str, object]],
    audit: Callable[..., None],
) -> None:
    @app.put(
        "/api/exceptions/{exception_id}/self-operated-site",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=None,
    )
    def save_self_operated_site_resolution(
        exception_id: int,
        payload: SelfOperatedSiteResolutionPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        exception = session.get(ExceptionRecord, exception_id)
        if exception is None:
            raise HTTPException(status_code=404, detail="待处理记录不存在")
        source = session.get(BatchFile, exception.batch_file_id)
        batch = (
            get_batch_or_404(source.batch_id, session, for_update=True)
            if source is not None
            else None
        )
        profile = (
            session.get(SelfOperatedBatch, batch.id) if batch is not None else None
        )
        if batch is None or profile is None:
            raise HTTPException(status_code=409, detail="不是自营仓入库待处理记录")
        if batch.status != "succeeded":
            raise HTTPException(status_code=409, detail="批次尚未计算成功")
        # 与导出共用批次锁；取得锁后刷新异常，避免使用重算前的记录。
        exception = session.scalar(
            select(ExceptionRecord)
            .where(ExceptionRecord.id == exception_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if exception is None:
            raise HTTPException(status_code=404, detail="待处理记录不存在")
        if (
            exception.reason_code or exception_reason_code(exception.reason)
        ) != "ambiguous_product_site":
            raise HTTPException(status_code=409, detail="当前记录不需要选择站点")

        candidates = [
            site.strip() for site in exception.full_site.split("、") if site.strip()
        ]
        selected = next(
            (
                site
                for site in candidates
                if site.upper() == payload.full_site.strip().upper()
            ),
            None,
        )
        if selected is None:
            raise HTTPException(status_code=400, detail="所选站点不在候选范围")

        export_job = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
        )
        if export_job and export_job.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="导出任务运行期间不可修改站点")
        resolution = session.scalar(
            select(SelfOperatedSiteResolution).where(
                SelfOperatedSiteResolution.batch_id == batch.id,
                SelfOperatedSiteResolution.sku == exception.sku,
                SelfOperatedSiteResolution.original_site == exception.original_site,
            )
        )
        if resolution is None:
            resolution = SelfOperatedSiteResolution(
                batch_id=batch.id,
                sku=exception.sku,
                original_site=exception.original_site,
                full_site=selected,
                updated_by=user.id,
            )
            session.add(resolution)
        else:
            resolution.full_site = selected
            resolution.updated_by = user.id

        compute_job = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "compute")
        )
        if compute_job is not None:
            compute_job.status = "stale"
        if export_job is not None:
            export_job.status = "stale"
            export_job.output_path = None
        batch.zip_path = None
        if source is not None:
            source.result_path = None
        job = queue_job(batch, "compute", user, session)
        batch.status = "queued"
        batch.error_message = None
        audit(
            session,
            user.id,
            "save_self_operated_site_resolution",
            "batch",
            batch.id,
            {
                "sku": exception.sku,
                "original_site": exception.original_site,
                "full_site": selected,
            },
        )
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="站点选择发生并发冲突，请刷新后重试",
            ) from error
        return job_json(job)

    @app.put("/api/exceptions/{exception_id}/split", response_model=None)
    def save_split(
        exception_id: int,
        payload: SplitPayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        exception = session.scalar(
            select(ExceptionRecord)
            .where(ExceptionRecord.id == exception_id)
            .with_for_update()
        )
        if exception is None:
            raise HTTPException(status_code=404, detail="待处理记录不存在")
        source = session.get(BatchFile, exception.batch_file_id)
        batch = (
            session.scalar(
                select(Batch).where(Batch.id == source.batch_id).with_for_update()
            )
            if source
            else None
        )
        if source is None or batch is None or batch.status != "succeeded":
            raise HTTPException(status_code=409, detail="批次尚未计算成功")
        if session.get(SelfOperatedBatch, batch.id) is not None:
            raise HTTPException(
                status_code=409,
                detail="自营仓入库待处理记录必须通过站点选择重新计算",
            )
        export_job = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
        )
        if export_job and export_job.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="导出任务运行期间不可修改拆分")
        position_values = exception_position_values(
            [exception],
            batch,
            session,
            position_frame_cache,
        )
        previous_parts = session.scalars(
            select(SplitRecord)
            .where(SplitRecord.exception_id == exception.id)
            .order_by(SplitRecord.id)
        ).all()
        before_snapshot = [
            {
                "quantity": part.quantity,
                "destination": part.destination,
                "site": part.site,
                "supplier_code": part.supplier_code,
                "sku": part.sku,
                "delivery_note": part.delivery_note,
                "resolved": part.resolved,
            }
            for part in previous_parts
        ]
        parts = [SplitPart(**part.model_dump()) for part in payload.parts]
        pending_row = pd.Series(exception_row(exception))
        supplier_code = next(
            (part.supplier_code for part in parts if part.supplier_code),
            "",
        )
        if not supplier_code:
            supplier_code = source.supplier_code
        if not supplier_code:
            import_rows = source.import_rows or []
            supplier_code = (
                str(import_rows[0].get("*供应商编码", "")) if import_rows else ""
            )
        try:
            project_split(
                pending_row,
                parts,
                supplier_code=supplier_code,
                document_note=source.document_note,
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        session.execute(
            delete(SplitRecord).where(SplitRecord.exception_id == exception.id)
        )
        for part in parts:
            session.add(
                SplitRecord(
                    exception_id=exception.id,
                    quantity=part.quantity,
                    destination=part.destination,
                    site=part.site,
                    supplier_code=part.supplier_code,
                    sku=part.sku,
                    delivery_note=part.delivery_note,
                    resolved=part.resolved,
                )
            )
        resolved_count = sum(part.resolved for part in parts)
        exception.status = (
            "resolved"
            if resolved_count == len(parts)
            else "partial"
            if resolved_count
            else "pending"
        )
        if export_job:
            export_job.status = "stale"
            export_job.output_path = None
        batch.zip_path = None
        source.result_path = None
        audit(
            session,
            user.id,
            "save_split",
            "exception",
            exception.id,
            {
                "before": before_snapshot,
                "after": [part.model_dump() for part in payload.parts],
            },
        )
        session.commit()
        splits = split_records_by_exception(session, [exception])
        return exception_json(
            exception,
            splits.get(exception.id, []),
            position_values.get(exception.id),
        )
