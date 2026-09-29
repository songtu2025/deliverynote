from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated, Callable

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..excel_io import read_purchase_workbook, read_self_operated_inbound_workbook
from ..gerpgo import GerpgoClient, GerpgoError
from .models import InputVersion, PurchaseSyncJob, SelfOperatedInboundSyncJob, User


def _purchase_sync_job_json(
    job: PurchaseSyncJob,
    utc_isoformat: Callable[[datetime], str],
) -> dict:
    findings = job.issues or []
    warning_count = sum(finding.get("severity") == "warning" for finding in findings)
    return {
        "id": job.id,
        "status": job.status,
        "base_version_id": job.base_version_id,
        "product_version_id": job.product_version_id,
        "supplier_version_id": job.supplier_version_id,
        "candidate_version_id": job.candidate_version_id,
        "total_orders": job.total_orders,
        "processed_orders": job.processed_orders,
        "raw_detail_count": job.raw_detail_count,
        "eligible_detail_count": job.eligible_detail_count,
        "filtered_detail_count": job.filtered_detail_count,
        "current_order": job.current_order,
        "issue_count": len(findings) - warning_count,
        "warning_count": warning_count,
        "diff": job.diff or {},
        "error_message": job.error_message,
        "created_at": utc_isoformat(job.created_at),
        "claimed_at": (utc_isoformat(job.claimed_at) if job.claimed_at else None),
        "heartbeat_at": (
            utc_isoformat(job.heartbeat_at) if job.heartbeat_at else None
        ),
        "finished_at": (utc_isoformat(job.finished_at) if job.finished_at else None),
    }


def _self_operated_inbound_sync_job_json(
    job: SelfOperatedInboundSyncJob,
    utc_isoformat: Callable[[datetime], str],
) -> dict:
    findings = job.issues or []
    warning_count = sum(finding.get("severity") == "warning" for finding in findings)
    return {
        "id": job.id,
        "status": job.status,
        "base_version_id": job.base_version_id,
        "candidate_version_id": job.candidate_version_id,
        "total_orders": job.total_orders,
        "raw_detail_count": job.raw_detail_count,
        "eligible_detail_count": job.eligible_detail_count,
        "filtered_detail_count": job.filtered_detail_count,
        "issue_count": len(findings) - warning_count,
        "warning_count": warning_count,
        "diff": job.diff or {},
        "error_message": job.error_message,
        "created_at": utc_isoformat(job.created_at),
        "claimed_at": (utc_isoformat(job.claimed_at) if job.claimed_at else None),
        "heartbeat_at": (
            utc_isoformat(job.heartbeat_at) if job.heartbeat_at else None
        ),
        "finished_at": (utc_isoformat(job.finished_at) if job.finished_at else None),
    }


def _self_operated_inbound_sync_issues(
    session: Session,
    job: SelfOperatedInboundSyncJob,
) -> list[dict]:
    issues = [dict(issue) for issue in (job.issues or [])]
    detail_fields = {
        "warehouse",
        "remaining_quantity",
        "purchase_code",
        "related_code",
    }
    if (
        not issues
        or all(detail_fields.issubset(issue) for issue in issues)
        or job.candidate_version_id is None
    ):
        return issues

    version = session.get(InputVersion, job.candidate_version_id)
    if version is None:
        return issues
    try:
        frame = read_self_operated_inbound_workbook(Path(version.storage_path))
    except (OSError, ValueError):
        return issues

    def key_value(value) -> str:
        return "" if pd.isna(value) else str(value).strip()

    candidates: dict[tuple[str, str, str], list[dict]] = {}
    for record in frame.to_dict("records"):
        key = (
            key_value(record.get("入库单号")),
            key_value(record.get("SKU")),
            key_value(record.get("接口站点", record.get("平台站点"))),
        )
        candidates.setdefault(key, []).append(record)

    offsets: dict[tuple[str, str, str], int] = {}
    for issue in issues:
        if detail_fields.issubset(issue):
            continue
        key = (
            key_value(issue.get("order_no")),
            key_value(issue.get("sku")),
            key_value(issue.get("source_site")),
        )
        matches = candidates.get(key, [])
        offset = offsets.get(key, 0)
        if offset >= len(matches):
            continue
        record = matches[offset]
        offsets[key] = offset + 1
        quantity = record.get("应收货")
        issue.setdefault("warehouse", key_value(record.get("入库仓")))
        issue.setdefault(
            "remaining_quantity",
            None
            if pd.isna(quantity)
            else quantity.item()
            if hasattr(quantity, "item")
            else quantity,
        )
        issue.setdefault("purchase_code", key_value(record.get("关联采购单")))
        issue.setdefault(
            "related_code",
            key_value(record.get("关联交货单/调拨单")),
        )
    return issues


def _sync_preview_json(frame: pd.DataFrame, limit: int) -> dict:
    preview = frame.head(limit)
    rows = [
        {
            "_row_number": row_number,
            **{
                column: (
                    None
                    if pd.isna(value)
                    else value.item()
                    if hasattr(value, "item")
                    else value
                )
                for column, value in record.items()
            },
        }
        for row_number, record in enumerate(
            preview.to_dict("records"),
            start=1,
        )
    ]
    return {
        "columns": list(frame.columns),
        "rows": rows,
        "total": len(frame),
    }


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
            "job": _purchase_sync_job_json(job, utc_isoformat) if job else None,
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
        return _purchase_sync_job_json(job, utc_isoformat)

    @app.get("/api/purchase-sync/{job_id}/issues/download")
    def download_purchase_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(PurchaseSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="采购同步任务不存在")
        if not job.issues:
            raise HTTPException(status_code=404, detail="当前任务没有待处理问题")
        columns = [
            "severity",
            "message",
            "po_code",
            "sku",
            "warehouse",
            "quantity",
            "source_site",
            "supplier_code",
            "supplier_name",
            "code",
        ]
        output = BytesIO()
        pd.DataFrame(job.issues, columns=columns).rename(
            columns={
                "severity": "级别",
                "message": "问题",
                "po_code": "采购单号",
                "sku": "SKU",
                "warehouse": "目的仓",
                "quantity": "未交量",
                "source_site": "接口站点",
                "supplier_code": "接口供应商编号",
                "supplier_name": "接口供应商名称",
                "code": "问题类型",
            }
        ).to_excel(output, index=False)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="purchase_sync_issues_{job.id}.xlsx"'
                )
            },
        )

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
        job = session.get(PurchaseSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="采购同步任务不存在")
        version = (
            session.get(InputVersion, job.candidate_version_id)
            if job.candidate_version_id is not None
            else None
        )
        if version is None:
            raise HTTPException(status_code=409, detail="候选版本尚未生成")
        try:
            frame = read_purchase_workbook(Path(version.storage_path))
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=409,
                detail=f"候选版本无法读取：{error}",
            ) from error
        return _sync_preview_json(frame, limit)

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
            "job": (
                _self_operated_inbound_sync_job_json(job, utc_isoformat)
                if job
                else None
            ),
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
        return _self_operated_inbound_sync_job_json(job, utc_isoformat)

    @app.get("/api/self-operated-inbound-sync/{job_id}/issues/download")
    def download_self_operated_inbound_sync_issues(
        job_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        job = session.get(SelfOperatedInboundSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="待入库同步任务不存在")
        issues = _self_operated_inbound_sync_issues(session, job)
        if not issues:
            raise HTTPException(status_code=404, detail="当前任务没有异常数据")
        columns = [
            "severity",
            "message",
            "order_no",
            "sku",
            "warehouse",
            "remaining_quantity",
            "purchase_code",
            "related_code",
            "source_site",
            "supplier_code",
            "supplier_name",
            "code",
        ]
        output = BytesIO()
        pd.DataFrame(issues, columns=columns).rename(
            columns={
                "severity": "级别",
                "message": "问题",
                "order_no": "入库单号",
                "sku": "SKU",
                "warehouse": "入库仓",
                "remaining_quantity": "剩余应收货",
                "purchase_code": "关联采购单",
                "related_code": "关联交货单/调拨单",
                "source_site": "接口站点",
                "supplier_code": "接口供应商编号",
                "supplier_name": "接口供应商名称",
                "code": "问题类型",
            }
        ).to_excel(output, index=False)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="self_operated_inbound_issues_{job.id}.xlsx"'
                )
            },
        )

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
        job = session.get(SelfOperatedInboundSyncJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="待入库同步任务不存在")
        version = (
            session.get(InputVersion, job.candidate_version_id)
            if job.candidate_version_id is not None
            else None
        )
        if version is None:
            raise HTTPException(status_code=409, detail="候选版本尚未生成")
        try:
            frame = read_self_operated_inbound_workbook(Path(version.storage_path))
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=409,
                detail=f"候选版本无法读取：{error}",
            ) from error
        return _sync_preview_json(frame, limit)

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
