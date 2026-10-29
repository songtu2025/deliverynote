"""后台获取并冻结本批单号的完整历史，同时完成累计数量核对。"""

from datetime import datetime, timezone
import json
import pandas as pd
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from ..excel_io import (
    read_product_workbook,
    read_self_operated_inbound_workbook,
    validate_self_operated_template_workbook,
)
from ..gerpgo import GerpgoClient
from ..inbound.history import history_frame, validate_history_frame
from ..inbound.receipts import prepare_receipts
from ..web.models import AuditLog, BatchFile, InputVersion, SelfOperatedBatch
from ..web.receipt_state import receipt_signature
from .compute_inputs import _load_compute_inputs
from .compute_records import _json_records, load_owned_compute
from .receipt_inputs import read_receipt_sources


def _capture_snapshot(managed, numbers, storage, batch_id, inbound_path):
    if managed:
        client = GerpgoClient.from_config(storage)
        orders = client.list_self_operated_inbound_orders(bill_codes=numbers)
        frame = history_frame(orders)
        payload = {
            "orders": orders,
            "rows": _json_records(frame),
            "columns": list(frame.columns),
        }
    else:
        frame = validate_history_frame(
            read_self_operated_inbound_workbook(inbound_path)
        )
        payload = {"rows": _json_records(frame), "columns": list(frame.columns)}
    path = storage / "batches" / str(batch_id) / "history" / f"{uuid4().hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    snapshot = {
        "path": str(path),
        "delivery_numbers": numbers,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "api" if managed else "upload",
    }
    return snapshot, payload


def execute_prepare_inbound(context, batch_id: int, storage: Path) -> None:
    inputs = _load_compute_inputs(context.database, batch_id)
    if inputs.self_operated_data is None:
        raise ValueError("不是自营仓批次")
    validate_self_operated_template_workbook(inputs.self_operated_data["template_path"])
    requests, identities, choices = read_receipt_sources(inputs)
    numbers = sorted({number for item in requests for number in item.delivery_numbers})
    with context.database.session() as session:
        job, batch = load_owned_compute(session, context, batch_id)
        profile = session.get(SelfOperatedBatch, batch_id)
        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id == batch_id)
        ).all()
        signature = receipt_signature(batch, profile, sources)
        previous = profile.receipt_snapshot
        managed = (
            session.scalar(
                select(InputVersion.id).where(
                    InputVersion.storage_path == profile.inbound_storage_path
                )
            )
            is not None
        )
    if previous and previous.get("signature") == signature:
        snapshot = previous
        payload = json.loads(Path(snapshot["path"]).read_text(encoding="utf-8"))
    else:
        snapshot, payload = _capture_snapshot(
            managed,
            numbers,
            storage,
            batch_id,
            inputs.self_operated_data["inbound_path"],
        )
        snapshot["signature"] = signature
    frame = validate_history_frame(
        pd.DataFrame(payload["rows"], columns=payload["columns"])
    )
    products = read_product_workbook(inputs.version_paths["product"])
    contexts, _ = prepare_receipts(requests, products, frame, choices)
    context.before_finalize()
    with context.database.session() as session:
        job, batch = load_owned_compute(session, context, batch_id)
        profile = session.get(SelfOperatedBatch, batch_id)
        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id == batch_id)
        ).all()
        if receipt_signature(batch, profile, sources) != signature:
            raise RuntimeError("核对期间输入发生变化，请重新预检")
        profile.receipt_snapshot = {
            **snapshot,
            "summary": {
                key: None
                if any(item[key] is None for item in contexts.values())
                else sum(item[key] for item in contexts.values())
                for key in (
                    "cumulative_total",
                    "history_total",
                    "requested_total",
                    "issue_count",
                )
            },
        }
        for source in sources:
            source.receipt_context = contexts[source.id]
            source.supplier_name = identities[source.id].name
            source.supplier_code = identities[source.id].code
            source.document_note = "、".join(contexts[source.id]["delivery_numbers"])
        blocked = any(item["issue_count"] for item in contexts.values())
        batch.status = "draft" if blocked else "preflight_ready"
        batch.error_message = (
            "累计实收存在待核对记录，请查看核对明细" if blocked else None
        )
        job.status = "succeeded"
        job.claim_token = None
        job.finished_at = job.heartbeat_at = datetime.utcnow()
        session.add(
            AuditLog(
                user_id=None,
                action="worker_prepare_succeeded",
                entity_type="batch",
                entity_id=str(batch_id),
                details=profile.receipt_snapshot["summary"],
            )
        )
        session.commit()
