from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from ..application import DeliveryBatchResult, DeliveryRequest, process_delivery_batch
from ..config import resolve_supplier
from ..excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_supplier_workbook,
)
from ..exception_reasons import exception_reason_code
from ..web.database import Database
from ..web.models import AuditLog, Batch, BatchFile, ExceptionRecord, Job
from .compute_inbound import _execute_self_operated_compute
from .compute_inputs import _load_compute_inputs
from .compute_records import _json_records, clear_compute_results
from .leases import JobContext, LostJobLeaseError, _heartbeat


def _save_delivery_compute(
    context: JobContext,
    batch_id: int,
    payloads: list[dict[str, Any]],
    batch_result: DeliveryBatchResult,
) -> None:
    database = context.database
    job_id = context.job_id
    claim_token = context.claim_token
    with database.session() as session:
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        batch = session.get(Batch, batch_id)
        if (
            job is None
            or batch is None
            or job.status != "running"
            or job.claim_token != claim_token
        ):
            raise LostJobLeaseError("计算任务租约已失效")
        clear_compute_results(session, payloads)

        for payload in payloads:
            source = session.get(BatchFile, payload["source_id"])
            if source is None or source.batch_id != batch.id:
                raise RuntimeError("批次来源文件已变化")
            source.supplier_name = payload["supplier"].name
            source.supplier_code = payload["supplier"].code
            source.document_note = payload["document_note"]
            source.delivery_total = payload["delivery_total"]
            source.import_total = payload["import_total"]
            source.manual_total = payload["manual_total"]
            source.import_rows = payload["import_rows"]
            source.result_path = None
            for exception in payload["exceptions"]:
                session.add(
                    ExceptionRecord(
                        batch_file_id=source.id,
                        sku=str(exception["SKU"]),
                        original_site=str(exception["原始站点"] or ""),
                        full_site=str(exception["完整站点"] or ""),
                        destination=str(exception["目的仓"] or ""),
                        delivery_quantity=int(exception["交货量"]),
                        allocated_quantity=int(exception["已自动分配量"]),
                        purchase_allocated_quantity=int(exception["正常采购分配量"]),
                        overreceipt_allocated_quantity=int(exception["超收规则分配量"]),
                        overreceipt_remaining_quantity=(
                            None
                            if pd.isna(exception["超收剩余额度"])
                            else int(exception["超收剩余额度"])
                        ),
                        manual_quantity=int(exception["人工处理量"]),
                        reason=str(exception["异常原因"]),
                        reason_code=exception_reason_code(exception["异常原因"]),
                        status="pending",
                    )
                )

        batch.status = "succeeded"
        batch.error_message = None
        batch.zip_path = None
        job.status = "succeeded"
        job.finished_at = datetime.utcnow()
        job.heartbeat_at = job.finished_at
        job.error_message = None
        job.claim_token = None
        session.add(
            AuditLog(
                user_id=None,
                action="worker_compute_succeeded",
                entity_type="batch",
                entity_id=str(batch.id),
                details={
                    "delivery_total": batch_result.delivery_total,
                    "import_total": batch_result.import_total,
                    "manual_total": batch_result.manual_total,
                },
            )
        )
        session.commit()


def _execute_compute(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
    before_finalize: Callable[[], None],
) -> None:
    context = JobContext(database, job_id, claim_token, before_finalize)
    _heartbeat(database, job_id, claim_token)
    inputs = _load_compute_inputs(database, batch_id)
    version_paths = inputs.version_paths
    sources = inputs.sources
    overreceipt_policy = inputs.overreceipt_policy
    self_operated_data = inputs.self_operated_data
    if self_operated_data is not None:
        _execute_self_operated_compute(
            context,
            batch_id,
            inputs,
        )
        return
    supplier_rows = read_supplier_workbook(version_paths["supplier"])
    product_rows = read_product_workbook(version_paths["product"])
    purchase_rows = read_purchase_workbook(version_paths["purchase"])
    position_rows = (
        read_position_workbook(version_paths["position"])
        if overreceipt_policy is not None
        else None
    )
    _heartbeat(database, job_id, claim_token)

    requests = []
    identities = {}
    for source in sources:
        _heartbeat(database, job_id, claim_token)
        if not source["path"].is_file():
            raise FileNotFoundError(f"交货文件不存在：{source['path']}")
        supplier = resolve_supplier(Path(source["original_name"]), supplier_rows)
        identities[source["id"]] = supplier
        requests.append(
            DeliveryRequest(
                source_id=str(source["id"]),
                delivery_rows=read_delivery_workbook(source["path"]),
                supplier_name=supplier.name,
                supplier_code=supplier.code,
                source_name=source["original_name"],
            )
        )

    batch_result = process_delivery_batch(
        requests,
        product_rows,
        purchase_rows,
        position_data=position_rows,
        overreceipt_policy=overreceipt_policy,
    )
    _heartbeat(database, job_id, claim_token)
    payloads: list[dict[str, Any]] = []
    for item in batch_result.items:
        source_id = int(item.source_id)
        payloads.append(
            {
                "source_id": source_id,
                "supplier": identities[source_id],
                "file_order": item.file_order,
                "document_note": item.document_note,
                "delivery_total": item.result.delivery_total,
                "import_total": item.result.import_total,
                "manual_total": item.result.manual_total,
                "import_rows": _json_records(item.result.import_rows),
                "exceptions": _json_records(item.result.exception_rows),
            }
        )

    before_finalize()
    _save_delivery_compute(
        context,
        batch_id,
        payloads=payloads,
        batch_result=batch_result,
    )
