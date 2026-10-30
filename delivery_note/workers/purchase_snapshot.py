"""后台采集整批采购快照，校验租约后统一发布成功版本。"""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from ..excel_io import read_self_operated_delivery_workbook
from ..gerpgo import GerpgoClient, GerpgoError
from ..inbound.purchase_options import collect_purchase_options
from ..processing.keys import _normalize_position_text as key
from ..web.models import AuditLog
from ..web.purchase_snapshot import (
    PURCHASE_SNAPSHOT_ERROR,
    require_snapshot_batch,
    snapshot_sources,
)
from .compute_records import load_owned_compute
from .leases import JobContext


def execute_purchase_snapshot(
    context: JobContext, batch_id: int, storage: Path
) -> None:
    with context.database.session() as session:
        _, batch = load_owned_compute(session, context, batch_id)
        require_snapshot_batch(session, batch)
        sources, signature = snapshot_sources(session, batch)
        inputs = [(source.supplier_code, source.storage_path) for source in sources]
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        targets: set[tuple[str, str]] = set()
        for supplier, source_path in inputs:
            if not key(supplier):
                raise ValueError("来源文件缺少供应商编码")
            delivery = read_self_operated_delivery_workbook(Path(source_path))
            targets.update(
                (key(supplier), key(sku))
                for sku in delivery.delivery_lines["SKU"]
                if key(sku)
            )
        rows = collect_purchase_options(GerpgoClient.from_config(storage), targets)
    except (GerpgoError, OSError, ValueError):
        raise ValueError(PURCHASE_SNAPSHOT_ERROR) from None
    snapshot_id = uuid4().hex
    path = (
        storage
        / "batches"
        / str(batch_id)
        / "purchase-snapshots"
        / f"{snapshot_id}.json"
    )
    document = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "source_signature": signature,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "supplier_count": len({supplier for supplier, _ in targets}),
        "sku_count": len({sku for _, sku in targets}),
        "items": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        context.before_finalize()
        with context.database.session() as session:
            job, batch = load_owned_compute(session, context, batch_id)
            _, current = snapshot_sources(session, batch)
            if current != signature:
                raise ValueError("批次范围已变化，请重新刷新整批采购数据")
            job.output_path = str(path)
            job.status = "succeeded"
            job.claim_token = None
            job.finished_at = job.heartbeat_at = datetime.utcnow()
            session.add(
                AuditLog(
                    user_id=None,
                    action="worker_purchase_snapshot_succeeded",
                    entity_type="job",
                    entity_id=str(job.id),
                    details={
                        "batch_id": batch_id,
                        "snapshot_id": snapshot_id,
                        "row_count": len(rows),
                    },
                )
            )
            session.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
