from io import BytesIO
from pathlib import Path
from collections.abc import Hashable, Mapping

import pandas as pd
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...excel_io import read_self_operated_inbound_workbook
from ...inspection.frames import _json_safe
from ..models import InputVersion, PurchaseSyncJob, SelfOperatedInboundSyncJob
from .queries import get_sync_job


def _self_operated_inbound_sync_issues(
    session: Session,
    job: SelfOperatedInboundSyncJob,
) -> list[dict[str, object]]:
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

    def key_value(value: object) -> str:
        return "" if _json_safe(value) is None else str(value).strip()

    candidates: dict[tuple[str, str, str], list[Mapping[Hashable, object]]] = {}
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
        matched_record = matches[offset]
        offsets[key] = offset + 1
        quantity = matched_record.get("应收货")
        issue.setdefault("warehouse", key_value(matched_record.get("入库仓")))
        issue.setdefault(
            "remaining_quantity",
            None
            if _json_safe(quantity) is None
            else quantity.item()
            if hasattr(quantity, "item")
            else quantity,
        )
        issue.setdefault("purchase_code", key_value(matched_record.get("关联采购单")))
        issue.setdefault(
            "related_code",
            key_value(matched_record.get("关联交货单/调拨单")),
        )
    return issues


def _issues_excel_response(
    issues: list[dict[str, object]], columns: dict[str, str], filename: str
) -> StreamingResponse:
    output = BytesIO()
    pd.DataFrame(issues, columns=list(columns)).rename(columns=columns).to_excel(
        output, index=False
    )
    output.seek(0)
    return StreamingResponse(
        output,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def download_purchase_sync_issues(job_id: int, session: Session) -> StreamingResponse:
    job = get_sync_job(session, PurchaseSyncJob, job_id)
    if not job.issues:
        raise HTTPException(status_code=404, detail="当前任务没有待处理问题")
    return _issues_excel_response(
        job.issues,
        {
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
        },
        f"purchase_sync_issues_{job.id}.xlsx",
    )


def download_self_operated_inbound_sync_issues(
    job_id: int, session: Session
) -> StreamingResponse:
    job = get_sync_job(session, SelfOperatedInboundSyncJob, job_id)
    issues = _self_operated_inbound_sync_issues(session, job)
    if not issues:
        raise HTTPException(status_code=404, detail="当前任务没有异常数据")
    return _issues_excel_response(
        issues,
        {
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
        },
        f"self_operated_inbound_issues_{job.id}.xlsx",
    )
