from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


import pandas as pd

from ..excel_io import (
    read_product_workbook,
)
from ..exception_reasons import ExceptionReason, exception_reason_code
from ..inbound.models import (
    SelfOperatedInboundBatchResult,
)
from ..inbound.receipts import prepare_receipts
from ..self_operated_inbound import (
    process_self_operated_inbound_batch,
)
from ..web.models import AuditLog, ExceptionRecord
from .compute_inputs import ComputeInputs
from .compute_records import (
    _json_records,
    clear_compute_results,
    load_owned_compute,
    mark_compute_succeeded,
    update_compute_source,
)
from .leases import JobContext, _heartbeat
from .receipt_inputs import read_receipt_sources


def _save_inbound_compute(
    context: JobContext,
    batch_id: int,
    payloads: list[dict[str, Any]],
    batch_result: SelfOperatedInboundBatchResult,
) -> None:
    with context.database.session() as session:
        job, batch = load_owned_compute(session, context, batch_id)
        clear_compute_results(session, payloads)
        for payload in payloads:
            stored_source = update_compute_source(
                session, batch.id, payload, "、".join(payload["delivery_numbers"])
            )

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

        mark_compute_succeeded(job, batch)
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
    self_operated_data = cast(dict[str, Any], inputs.self_operated_data)
    product_rows = read_product_workbook(version_paths["product"])
    snapshot = self_operated_data["receipt_snapshot"]
    if not snapshot:
        raise ValueError("请先预检并获取完整入库历史")
    payload = json.loads(Path(snapshot["path"]).read_text(encoding="utf-8"))
    inbound_rows = pd.DataFrame(payload["rows"], columns=payload["columns"])
    originals, identities, choices = read_receipt_sources(inputs)
    contexts, requests = prepare_receipts(
        originals, product_rows, inbound_rows, choices
    )
    if len(requests) != len(originals):
        raise ValueError("累计实收存在待核对记录，请重新预检")
    for request in requests:
        for row in contexts[request.source_id]["rows"]:
            choices[request.source_id][(row["sku"], row["original_site"])] = row[
                "full_site"
            ]
    batch_result = process_self_operated_inbound_batch(
        requests,
        product_rows,
        inbound_rows,
        overreceipt_limit=self_operated_data["overreceipt_limit"],
        file_site_overrides=choices,
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
                "delivery_numbers": item.delivery_numbers,
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
