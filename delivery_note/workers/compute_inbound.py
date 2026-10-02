from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select

from ..config import resolve_supplier
from ..excel_io import (
    read_product_workbook,
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
    read_supplier_workbook,
)
from ..exception_reasons import ExceptionReason, exception_reason_code
from ..self_operated_inbound import (
    SelfOperatedInboundBatchResult,
    SelfOperatedInboundRequest,
    process_self_operated_inbound_batch,
)
from ..web.models import AuditLog, Batch, BatchFile, ExceptionRecord, Job
from .compute_inputs import ComputeInputs
from .compute_records import _json_records, clear_compute_results
from .leases import JobContext, LostJobLeaseError, _heartbeat


def _save_inbound_compute(
    context: JobContext,
    batch_id: int,
    payloads: list[dict[str, Any]],
    batch_result: SelfOperatedInboundBatchResult,
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
            stored_source = session.get(BatchFile, payload["source_id"])
            if stored_source is None or stored_source.batch_id != batch.id:
                raise RuntimeError("批次来源文件已变化")
            supplier = payload["supplier"]
            stored_source.supplier_name = supplier.name
            stored_source.supplier_code = supplier.code
            stored_source.document_note = "、".join(payload["delivery_numbers"])
            stored_source.delivery_total = payload["delivery_total"]
            stored_source.import_total = payload["import_total"]
            stored_source.manual_total = payload["manual_total"]
            stored_source.import_rows = payload["import_rows"]
            stored_source.result_path = None

            for pending in payload["pending_rows"]:
                normal = int(pending["正常分配数量"])
                overreceipt = int(pending["规则内超收数量"])
                session.add(
                    ExceptionRecord(
                        batch_file_id=stored_source.id,
                        sku=str(pending["SKU"]),
                        original_site=str(pending["原始站点"] or ""),
                        full_site=str(pending["完整站点"] or ""),
                        destination="",
                        delivery_quantity=int(pending["质检合格数量"]),
                        allocated_quantity=normal + overreceipt,
                        purchase_allocated_quantity=normal,
                        overreceipt_allocated_quantity=overreceipt,
                        overreceipt_remaining_quantity=(
                            0
                            if pending["待处理原因"]
                            == ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED
                            else None
                        ),
                        manual_quantity=int(pending["待处理数量"]),
                        reason=str(pending["待处理原因"]),
                        reason_code=exception_reason_code(pending["待处理原因"]),
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
                action="worker_self_operated_compute_succeeded",
                entity_type="batch",
                entity_id=str(batch.id),
                details={
                    "qualified_total": batch_result.qualified_total,
                    "import_total": batch_result.import_total,
                    "pending_total": batch_result.pending_total,
                },
            )
        )
        session.commit()


def _execute_self_operated_compute(
    context: JobContext,
    batch_id: int,
    inputs: ComputeInputs,
) -> None:
    database = context.database
    job_id = context.job_id
    claim_token = context.claim_token
    version_paths = inputs.version_paths
    sources = inputs.sources
    self_operated_data = cast(dict[str, Any], inputs.self_operated_data)
    supplier_rows = read_supplier_workbook(version_paths["supplier"])
    product_rows = read_product_workbook(version_paths["product"])
    inbound_rows = read_self_operated_inbound_workbook(
        self_operated_data["inbound_path"]
    )
    identities = {}
    deliveries = {}
    requests = []
    for source in sources:
        _heartbeat(database, job_id, claim_token)
        if not source["path"].is_file():
            raise FileNotFoundError(f"交货文件不存在：{source['path']}")
        supplier = resolve_supplier(Path(source["original_name"]), supplier_rows)
        delivery = read_self_operated_delivery_workbook(source["path"])
        identities[source["id"]] = supplier
        deliveries[source["id"]] = delivery
        requests.append(
            SelfOperatedInboundRequest(
                source_id=source["id"],
                delivery_lines=delivery.delivery_lines,
                delivery_numbers=delivery.delivery_numbers,
                supplier_name=supplier.name,
            )
        )
    batch_result = process_self_operated_inbound_batch(
        requests,
        product_rows,
        inbound_rows,
        overreceipt_limit=self_operated_data["overreceipt_limit"],
        site_overrides=self_operated_data["site_overrides"],
    )
    _heartbeat(database, job_id, claim_token)
    payloads: list[dict[str, Any]] = []
    for item in batch_result.items:
        source_id = int(item.source_id)
        result = item.result
        payloads.append(
            {
                "source_id": source_id,
                "supplier": identities[source_id],
                "delivery_numbers": deliveries[source_id].delivery_numbers,
                "delivery_total": result.qualified_total,
                "import_total": result.import_total,
                "manual_total": result.pending_total,
                "import_rows": _json_records(result.allocation_rows),
                "pending_rows": _json_records(result.pending_rows),
            }
        )
    context.before_finalize()

    _save_inbound_compute(
        context,
        batch_id,
        payloads=payloads,
        batch_result=batch_result,
    )
