from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import signal
import shutil
from threading import Event, Thread
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from sqlalchemy import delete, select, update

from .application import (
    DeliveryRequest,
    SplitPart,
    process_delivery_batch,
    project_split,
)
from .config import resolve_supplier
from .excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
    read_supplier_workbook,
    write_delivery_workbook,
    write_self_operated_inbound_workbook,
)
from .gerpgo import GerpgoClient
from .purchase_detail_cache import (
    build_purchase_detail_cache,
    evaluate_shadow_cache,
    full_verification_due,
    load_purchase_detail_cache_state,
    payload_hash,
    plan_incremental_detail_fetch,
    purchase_cache_source_identity,
    purchase_detail_cache_path,
    write_purchase_detail_cache,
)
from .pipeline import (
    EXCEPTION_COLUMNS,
    IMPORT_COLUMNS,
    BatchResult,
    OverreceiptPolicy,
    build_manual_import_rows,
    enrich_pending_import_rows,
)
from .purchase_sync import (
    compare_purchase_frames,
    map_purchase_orders,
    purchase_frame,
    write_purchase_workbook,
)
from .self_operated_inbound import (
    INBOUND_TEMPLATE_COLUMNS,
    process_self_operated_inbound,
)
from .self_operated_inbound_sync import (
    compare_self_operated_inbound_frames,
    map_self_operated_inbound_orders,
    self_operated_inbound_frame,
    write_self_operated_inbound_source,
)
from .web.database import Database
from .web.models import (
    AuditLog,
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputVersion,
    Job,
    OverreceiptRuleVersion,
    PurchaseSyncJob,
    SelfOperatedBatch,
    SelfOperatedInboundSyncJob,
    SelfOperatedOverreceiptRuleVersion,
    SelfOperatedSiteResolution,
    SplitRecord,
)


class LostJobLeaseError(RuntimeError):
    pass


VERSION_FIELDS = {
    "purchase": "purchase_version_id",
    "product": "product_version_id",
    "supplier": "supplier_version_id",
    "position": "position_version_id",
    "template": "template_version_id",
}


PURCHASE_DETAIL_WORKERS = 8
PURCHASE_SYNC_MODES = {"full", "shadow", "incremental"}


def _json_value(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _json_records(frame: pd.DataFrame) -> list[dict]:
    return [
        {column: _json_value(value) for column, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _version_paths(
    session,
    batch: Batch,
    kinds: tuple[str, ...] = tuple(VERSION_FIELDS),
) -> dict[str, Path]:
    result = {}
    for kind in kinds:
        version_id = getattr(batch, VERSION_FIELDS[kind])
        if version_id is None:
            raise RuntimeError(f"批次缺少锁定的 {kind} 输入版本")
        version = session.get(InputVersion, version_id)
        if version is None:
            raise RuntimeError(f"批次缺少锁定的 {kind} 输入版本")
        path = Path(version.storage_path)
        if not path.is_file():
            raise FileNotFoundError(f"批次输入版本文件不存在：{path}")
        result[kind] = path
    return result


def _claim_job(database: Database) -> tuple[int, int, str, str] | None:
    with database.session() as session:
        job = session.scalar(
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        now = datetime.utcnow()
        claim_token = uuid4().hex
        job.status = "running"
        job.claim_token = claim_token
        job.attempts += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.error_message = None
        batch = session.get(Batch, job.batch_id)
        if batch is None:
            raise RuntimeError("任务关联的批次不存在")
        if job.kind == "compute":
            batch.status = "running"
            batch.error_message = None
        session.commit()
        return job.id, job.batch_id, job.kind, claim_token


def _heartbeat(database: Database, job_id: int, claim_token: str) -> None:
    with database.session() as session:
        result = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.claim_token == claim_token,
            )
            .values(heartbeat_at=datetime.utcnow())
        )
        session.commit()
        if result.rowcount != 1:
            raise LostJobLeaseError("任务租约已失效")


def _claim_purchase_sync_job(database: Database) -> tuple[int, str] | None:
    with database.session() as session:
        job = session.scalar(
            select(PurchaseSyncJob)
            .where(PurchaseSyncJob.status == "queued")
            .order_by(PurchaseSyncJob.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        now = datetime.utcnow()
        claim_token = uuid4().hex
        job.status = "running"
        job.claim_token = claim_token
        job.attempts += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.error_message = None
        session.commit()
        return job.id, claim_token


def _purchase_sync_heartbeat(
    database: Database,
    job_id: int,
    claim_token: str,
    **values,
) -> None:
    with database.session() as session:
        result = session.execute(
            update(PurchaseSyncJob)
            .where(
                PurchaseSyncJob.id == job_id,
                PurchaseSyncJob.status == "running",
                PurchaseSyncJob.claim_token == claim_token,
            )
            .values(heartbeat_at=datetime.utcnow(), **values)
        )
        session.commit()
        if result.rowcount != 1:
            raise LostJobLeaseError("采购同步任务租约已失效")


def _claim_self_operated_inbound_sync_job(
    database: Database,
) -> tuple[int, str] | None:
    with database.session() as session:
        job = session.scalar(
            select(SelfOperatedInboundSyncJob)
            .where(SelfOperatedInboundSyncJob.status == "queued")
            .order_by(SelfOperatedInboundSyncJob.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        now = datetime.utcnow()
        claim_token = uuid4().hex
        job.status = "running"
        job.claim_token = claim_token
        job.attempts += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.error_message = None
        session.commit()
        return job.id, claim_token


def _self_operated_inbound_sync_heartbeat(
    database: Database,
    job_id: int,
    claim_token: str,
    **values,
) -> None:
    with database.session() as session:
        result = session.execute(
            update(SelfOperatedInboundSyncJob)
            .where(
                SelfOperatedInboundSyncJob.id == job_id,
                SelfOperatedInboundSyncJob.status == "running",
                SelfOperatedInboundSyncJob.claim_token == claim_token,
            )
            .values(heartbeat_at=datetime.utcnow(), **values)
        )
        session.commit()
        if result.rowcount != 1:
            raise LostJobLeaseError("待入库同步任务租约已失效")


def recover_stale_jobs(
    database_url: str,
    stale_after: timedelta = timedelta(minutes=30),
) -> int:
    database = Database(database_url)
    cutoff = datetime.utcnow() - stale_after
    recovered = 0
    try:
        with database.session() as session:
            jobs = session.scalars(
                select(Job)
                .where(Job.status == "running")
                .with_for_update(skip_locked=True)
            ).all()
            for job in jobs:
                marker = job.heartbeat_at or job.claimed_at
                if marker is None or marker >= cutoff:
                    continue
                job.status = "queued"
                job.claim_token = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.error_message = "任务运行超时，已自动重试"
                batch = session.get(Batch, job.batch_id)
                if batch is not None and job.kind == "compute":
                    batch.status = "queued"
                    batch.error_message = job.error_message
                recovered += 1
            sync_jobs = session.scalars(
                select(PurchaseSyncJob)
                .where(PurchaseSyncJob.status == "running")
                .with_for_update(skip_locked=True)
            ).all()
            for job in sync_jobs:
                marker = job.heartbeat_at or job.claimed_at
                if marker is None or marker >= cutoff:
                    continue
                job.status = "queued"
                job.claim_token = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.error_message = "采购同步运行超时，已自动重试"
                recovered += 1
            inbound_sync_jobs = session.scalars(
                select(SelfOperatedInboundSyncJob)
                .where(SelfOperatedInboundSyncJob.status == "running")
                .with_for_update(skip_locked=True)
            ).all()
            for job in inbound_sync_jobs:
                marker = job.heartbeat_at or job.claimed_at
                if marker is None or marker >= cutoff:
                    continue
                job.status = "queued"
                job.claim_token = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.error_message = "待入库同步运行超时，已自动重试"
                recovered += 1
            session.commit()
    finally:
        database.dispose()
    return recovered


def _load_compute_inputs(database: Database, batch_id: int):
    with database.session() as session:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise RuntimeError("批次不存在")
        profile = session.get(SelfOperatedBatch, batch.id)
        version_kinds = (
            ("product", "supplier") if profile is not None else tuple(VERSION_FIELDS)
        )
        version_paths = _version_paths(session, batch, version_kinds)
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        if not sources:
            raise RuntimeError("批次没有交货文件")
        source_data = [
            {
                "id": source.id,
                "path": Path(source.storage_path),
                "original_name": source.original_name,
                "file_order": source.file_order,
            }
            for source in sources
        ]
        overreceipt_policy = None
        binding = session.get(BatchOverreceiptRule, batch.id)
        if binding is not None:
            rule = session.get(OverreceiptRuleVersion, binding.rule_version_id)
            if rule is None:
                raise RuntimeError("批次锁定的超收规则版本不存在")
            overreceipt_policy = OverreceiptPolicy(
                short_tail_limit=rule.short_tail_limit,
                medium_tail_limit=rule.medium_tail_limit,
                long_tail_limit=rule.long_tail_limit,
                allowed_warehouses=frozenset(rule.allowed_warehouses or []),
            )
        self_operated_data = None
        if profile is not None:
            if len(source_data) != 1:
                raise RuntimeError("自营仓入库批次必须且只能包含一份质检交货单")
            inbound_path = Path(profile.inbound_storage_path)
            if not profile.inbound_storage_path or not inbound_path.is_file():
                raise FileNotFoundError("自营仓收货入库单不存在")
            template = session.get(InputVersion, profile.template_version_id)
            if template is None or not Path(template.storage_path).is_file():
                raise FileNotFoundError("批次锁定的积加入库模板不存在")
            rule = (
                session.get(
                    SelfOperatedOverreceiptRuleVersion,
                    profile.rule_version_id,
                )
                if profile.rule_version_id is not None
                else None
            )
            resolutions = session.scalars(
                select(SelfOperatedSiteResolution).where(
                    SelfOperatedSiteResolution.batch_id == batch.id
                )
            ).all()
            self_operated_data = {
                "inbound_path": inbound_path,
                "template_path": Path(template.storage_path),
                "overreceipt_limit": rule.allowance if rule is not None else 0,
                "site_overrides": {
                    (resolution.sku, resolution.original_site): resolution.full_site
                    for resolution in resolutions
                },
            }
    return version_paths, source_data, overreceipt_policy, self_operated_data


def _execute_self_operated_compute(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
    version_paths: dict[str, Path],
    sources: list[dict],
    self_operated_data: dict,
) -> None:
    supplier_rows = read_supplier_workbook(version_paths["supplier"])
    product_rows = read_product_workbook(version_paths["product"])
    source = sources[0]
    if not source["path"].is_file():
        raise FileNotFoundError(f"交货文件不存在：{source['path']}")
    supplier = resolve_supplier(Path(source["original_name"]), supplier_rows)
    delivery = read_self_operated_delivery_workbook(source["path"])
    inbound_rows = read_self_operated_inbound_workbook(
        self_operated_data["inbound_path"]
    )
    result = process_self_operated_inbound(
        delivery.delivery_lines,
        delivery.delivery_numbers,
        product_rows,
        inbound_rows,
        supplier.name,
        overreceipt_limit=self_operated_data["overreceipt_limit"],
        site_overrides=self_operated_data["site_overrides"],
    )
    _heartbeat(database, job_id, claim_token)

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
        exception_ids = session.scalars(
            select(ExceptionRecord.id).where(
                ExceptionRecord.batch_file_id == source["id"]
            )
        ).all()
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
            )
            session.execute(
                delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
            )

        stored_source = session.get(BatchFile, source["id"])
        if stored_source is None or stored_source.batch_id != batch.id:
            raise RuntimeError("批次来源文件已变化")
        stored_source.supplier_name = supplier.name
        stored_source.supplier_code = supplier.code
        stored_source.document_note = "、".join(delivery.delivery_numbers)
        stored_source.delivery_total = result.qualified_total
        stored_source.import_total = result.import_total
        stored_source.manual_total = result.pending_total
        stored_source.import_rows = _json_records(result.allocation_rows)
        stored_source.result_path = None

        for pending in result.pending_rows.to_dict("records"):
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
                        0 if pending["待处理原因"] == "超出允许超收量" else None
                    ),
                    manual_quantity=int(pending["待处理数量"]),
                    reason=str(pending["待处理原因"]),
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
                    "qualified_total": result.qualified_total,
                    "import_total": result.import_total,
                    "pending_total": result.pending_total,
                },
            )
        )
        session.commit()


def _execute_compute(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
) -> None:
    _heartbeat(database, job_id, claim_token)
    (
        version_paths,
        sources,
        overreceipt_policy,
        self_operated_data,
    ) = _load_compute_inputs(database, batch_id)
    if self_operated_data is not None:
        _execute_self_operated_compute(
            database,
            job_id,
            batch_id,
            claim_token,
            version_paths,
            sources,
            self_operated_data,
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
    payloads = []
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
        source_ids = [payload["source_id"] for payload in payloads]
        exception_ids = session.scalars(
            select(ExceptionRecord.id).where(
                ExceptionRecord.batch_file_id.in_(source_ids)
            )
        ).all()
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
            )
            session.execute(
                delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
            )

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


def _exception_dict(exception: ExceptionRecord) -> dict:
    return {
        "SKU": exception.sku,
        "原始站点": exception.original_site,
        "完整站点": exception.full_site,
        "目的仓": exception.destination,
        "交货量": exception.delivery_quantity,
        "已自动分配量": exception.allocated_quantity,
        "人工处理量": exception.manual_quantity,
        "异常原因": exception.reason,
    }


def _merge_delivery_notes(values: pd.Series) -> str:
    """按原顺序合并有效备注，并保留带数量的详细版本。"""

    notes: list[str] = []
    for value in values:
        if pd.isna(value):
            continue
        note = str(value)
        if note.strip() and note not in notes:
            notes.append(note)
    detailed_notes = [
        note
        for note in notes
        if not any(other.startswith(f"{note}：") for other in notes)
    ]
    return "；".join(detailed_notes)


def _consolidate_import_rows(import_rows: pd.DataFrame) -> pd.DataFrame:
    """合并业务身份相同的导入行，避免积加忽略后续记录。"""

    group_columns = [
        column for column in IMPORT_COLUMNS if column not in {"*本次交货量", "交货备注"}
    ]
    consolidated = import_rows.groupby(
        group_columns,
        as_index=False,
        sort=False,
        dropna=False,
    ).agg(
        {
            "*本次交货量": "sum",
            "交货备注": _merge_delivery_notes,
        }
    )
    return consolidated[IMPORT_COLUMNS]


def _load_export_inputs(database: Database, batch_id: int):
    with database.session() as session:
        batch = session.get(Batch, batch_id)
        if batch is None or batch.status != "succeeded":
            raise RuntimeError("批次尚未计算成功")
        version_paths = _version_paths(session, batch)
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        source_ids = [source.id for source in sources]
        exceptions = (
            session.scalars(
                select(ExceptionRecord)
                .where(ExceptionRecord.batch_file_id.in_(source_ids))
                .order_by(
                    ExceptionRecord.batch_file_id,
                    ExceptionRecord.id,
                )
            ).all()
            if source_ids
            else []
        )
        exception_ids = [exception.id for exception in exceptions]
        parts = (
            session.scalars(
                select(SplitRecord)
                .where(SplitRecord.exception_id.in_(exception_ids))
                .order_by(SplitRecord.exception_id, SplitRecord.id)
            ).all()
            if exception_ids
            else []
        )
        exceptions_by_source: dict[int, list[ExceptionRecord]] = {}
        for exception in exceptions:
            exceptions_by_source.setdefault(
                exception.batch_file_id,
                [],
            ).append(exception)
        parts_by_exception: dict[int, list[SplitRecord]] = {}
        for part in parts:
            parts_by_exception.setdefault(part.exception_id, []).append(part)
        payloads = []
        for source in sources:
            exception_payloads = []
            for exception in exceptions_by_source.get(source.id, []):
                exception_payloads.append(
                    {
                        "row": _exception_dict(exception),
                        "parts": [
                            SplitPart(
                                quantity=part.quantity,
                                destination=part.destination,
                                site=part.site,
                                supplier_code=part.supplier_code,
                                sku=part.sku,
                                delivery_note=part.delivery_note,
                                resolved=part.resolved,
                            )
                            for part in parts_by_exception.get(
                                exception.id,
                                [],
                            )
                        ],
                    }
                )
            payloads.append(
                {
                    "id": source.id,
                    "original_name": source.original_name,
                    "file_order": source.file_order,
                    "supplier_code": source.supplier_code,
                    "document_note": source.document_note,
                    "delivery_total": source.delivery_total,
                    "import_rows": source.import_rows or [],
                    "exceptions": exception_payloads,
                }
            )
    return version_paths, payloads


def _prepare_export_result(source: dict, position_rows: pd.DataFrame):
    import_frames = [pd.DataFrame(source["import_rows"], columns=IMPORT_COLUMNS)]
    pending_frames = []
    exception_rows = []
    for exception_payload in source["exceptions"]:
        row = exception_payload["row"]
        exception_rows.append(row)
        exception_frame = pd.DataFrame([row], columns=EXCEPTION_COLUMNS)
        parts = exception_payload["parts"]
        if parts:
            projection = project_split(
                exception_frame.iloc[0],
                parts,
                supplier_code=source["supplier_code"],
                document_note=source["document_note"],
            )
            import_frames.append(projection.import_rows)
            pending_frames.append(projection.pending_rows)
        else:
            pending = build_manual_import_rows(
                exception_frame,
                source["supplier_code"],
            )
            pending["单据备注"] = source["document_note"]
            pending_frames.append(pending)

    import_rows = pd.concat(import_frames, ignore_index=True)
    import_rows = _consolidate_import_rows(import_rows)
    pending_rows = (
        pd.concat(pending_frames, ignore_index=True)
        if pending_frames
        else pd.DataFrame(columns=IMPORT_COLUMNS)
    )
    pending_rows = enrich_pending_import_rows(pending_rows, position_rows)
    import_total = int(import_rows["*本次交货量"].sum()) if not import_rows.empty else 0
    pending_total = (
        int(pending_rows["*本次交货量"].sum()) if not pending_rows.empty else 0
    )
    if source["delivery_total"] != import_total + pending_total:
        raise RuntimeError("导出数量不守恒")
    result = BatchResult(
        import_rows=import_rows,
        exception_rows=pd.DataFrame(exception_rows, columns=EXCEPTION_COLUMNS),
        delivery_total=source["delivery_total"],
        import_total=import_total,
        manual_total=pending_total,
    )
    return result, import_rows, pending_rows


def _execute_self_operated_export(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
    storage_root: Path,
) -> None:
    with database.session() as session:
        batch = session.get(Batch, batch_id)
        profile = session.get(SelfOperatedBatch, batch_id)
        if batch is None or batch.status != "succeeded" or profile is None:
            raise RuntimeError("自营仓入库批次尚未计算成功")
        template = session.get(InputVersion, profile.template_version_id)
        if template is None or not Path(template.storage_path).is_file():
            raise FileNotFoundError("批次锁定的积加入库模板不存在")
        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id == batch.id)
        ).all()
        if len(sources) != 1:
            raise RuntimeError("自营仓入库批次必须且只能包含一份质检交货单")
        source = sources[0]
        source_data = {
            "id": source.id,
            "original_name": source.original_name,
            "import_rows": source.import_rows or [],
        }
        template_path = Path(template.storage_path)

    _heartbeat(database, job_id, claim_token)
    export_root = storage_root / "batches" / str(batch_id) / "exports"
    export_token = uuid4().hex
    temporary = export_root / f".tmp-{export_token}"
    published = export_root / f"export-{export_token}"
    temporary.mkdir(parents=True, exist_ok=False)
    output_name = f"{Path(source_data['original_name']).stem}_积加入库.xlsx"
    output_path = temporary / output_name
    published_path = published / output_name
    allocation_rows = (
        pd.DataFrame(source_data["import_rows"])
        if source_data["import_rows"]
        else pd.DataFrame(columns=INBOUND_TEMPLATE_COLUMNS)
    )
    if "最大可收货" not in allocation_rows.columns:
        allocation_rows["最大可收货"] = pd.NA
    try:
        write_self_operated_inbound_workbook(
            template_path,
            output_path,
            allocation_rows,
        )
        _heartbeat(database, job_id, claim_token)
        os.replace(temporary, published)

        with database.session() as session:
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            batch = session.get(Batch, batch_id)
            source = session.get(BatchFile, source_data["id"])
            if (
                job is None
                or batch is None
                or source is None
                or source.batch_id != batch.id
                or job.status != "running"
                or job.claim_token != claim_token
            ):
                raise LostJobLeaseError("导出任务租约已失效")
            source.result_path = str(published_path)
            batch.zip_path = str(published_path)
            batch.error_message = None
            job.status = "succeeded"
            job.finished_at = datetime.utcnow()
            job.heartbeat_at = job.finished_at
            job.error_message = None
            job.claim_token = None
            job.output_path = str(published_path)
            session.add(
                AuditLog(
                    user_id=None,
                    action="worker_self_operated_export_succeeded",
                    entity_type="batch",
                    entity_id=str(batch.id),
                    details={"output_name": output_name},
                )
            )
            session.commit()
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        if published.exists() and not _published_is_registered(
            database,
            job_id,
            published_path,
        ):
            shutil.rmtree(published)
        raise


def _execute_export(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
    storage_root: Path,
) -> None:
    with database.session() as session:
        self_operated = session.get(SelfOperatedBatch, batch_id)
    if self_operated is not None:
        _execute_self_operated_export(
            database,
            job_id,
            batch_id,
            claim_token,
            storage_root,
        )
        return
    _heartbeat(database, job_id, claim_token)
    version_paths, sources = _load_export_inputs(database, batch_id)
    position_rows = read_position_workbook(version_paths["position"])
    _heartbeat(database, job_id, claim_token)
    export_root = storage_root / "batches" / str(batch_id) / "exports"
    export_token = uuid4().hex
    temporary = export_root / f".tmp-{export_token}"
    published = export_root / f"export-{export_token}"
    temporary.mkdir(parents=True, exist_ok=False)
    output_names: dict[int, str] = {}
    used_names: set[str] = set()
    merged_import_frames: list[pd.DataFrame] = []
    merged_pending_frames: list[pd.DataFrame] = []
    try:
        for source in sources:
            _heartbeat(database, job_id, claim_token)
            result, import_rows, pending_rows = _prepare_export_result(
                source, position_rows
            )
            merged_import_frames.append(import_rows)
            merged_pending_frames.append(pending_rows)
            output_name = f"{Path(source['original_name']).stem}_交货处理.xlsx"
            if output_name in used_names:
                raise RuntimeError(f"导出文件名重复：{output_name}")
            used_names.add(output_name)
            output_path = temporary / output_name
            write_delivery_workbook(
                version_paths["template"],
                output_path,
                result,
                import_rows,
                pending_rows,
            )
            output_names[source["id"]] = output_name

        if len(sources) > 1:
            merged_import_rows = pd.concat(
                merged_import_frames,
                ignore_index=True,
            )
            merged_pending_rows = pd.concat(
                merged_pending_frames,
                ignore_index=True,
            )
            delivery_total = sum(source["delivery_total"] for source in sources)
            import_total = int(merged_import_rows["*本次交货量"].sum())
            pending_total = int(merged_pending_rows["*本次交货量"].sum())
            if delivery_total != import_total + pending_total:
                raise RuntimeError("合并导出数量不守恒")
            merged_result = BatchResult(
                import_rows=merged_import_rows,
                exception_rows=pd.DataFrame(columns=EXCEPTION_COLUMNS),
                delivery_total=delivery_total,
                import_total=import_total,
                manual_total=pending_total,
            )
            write_delivery_workbook(
                version_paths["template"],
                temporary / f"batch-{batch_id}-merged.xlsx",
                merged_result,
                merged_import_rows,
                merged_pending_rows,
            )

        archive_path = temporary / f"batch-{batch_id}.zip"
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            for source in sources:
                output_name = output_names[source["id"]]
                archive.write(temporary / output_name, arcname=output_name)
        _heartbeat(database, job_id, claim_token)
        os.replace(temporary, published)

        with database.session() as session:
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            batch = session.get(Batch, batch_id)
            if (
                job is None
                or batch is None
                or job.status != "running"
                or job.claim_token != claim_token
            ):
                raise LostJobLeaseError("导出任务租约已失效")
            for source_id, output_name in output_names.items():
                source = session.get(BatchFile, source_id)
                if source is None or source.batch_id != batch.id:
                    raise RuntimeError("批次来源文件已变化")
                source.result_path = str(published / output_name)
            batch.zip_path = str(published / f"batch-{batch_id}.zip")
            job.status = "succeeded"
            job.finished_at = datetime.utcnow()
            job.heartbeat_at = job.finished_at
            job.error_message = None
            job.claim_token = None
            job.output_path = batch.zip_path
            session.add(
                AuditLog(
                    user_id=None,
                    action="worker_export_succeeded",
                    entity_type="batch",
                    entity_id=str(batch.id),
                    details={
                        "file_count": len(sources),
                        "merged_workbook": len(sources) > 1,
                    },
                )
            )
            session.commit()
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        registered_archive = published / f"batch-{batch_id}.zip"
        if published.exists() and not _published_is_registered(
            database, job_id, registered_archive
        ):
            shutil.rmtree(published)
        raise


def _published_is_registered(
    database: Database,
    job_id: int,
    archive_path: Path,
) -> bool:
    try:
        with database.session() as session:
            job = session.get(Job, job_id)
            return (
                job is not None
                and job.status == "succeeded"
                and job.output_path == str(archive_path)
            )
    except Exception:
        # 数据库状态无法确认时保留文件，避免删除已成功提交的正式结果。
        return True


def _fetch_purchase_order_details(
    client: GerpgoClient,
    orders: list[dict],
    update_progress: Callable[[int, str], None],
) -> list[tuple[dict, dict]]:
    indexed_orders = []
    for index, order in enumerate(orders):
        po_code = str(order.get("code") or order.get("poCode") or "").strip()
        if not po_code:
            raise RuntimeError("积加采购单缺少单号字段 code")
        indexed_orders.append((index, order, po_code))
    if not indexed_orders:
        return []

    order_details: list[tuple[dict, dict] | None] = [None] * len(orders)
    with ThreadPoolExecutor(
        max_workers=min(PURCHASE_DETAIL_WORKERS, len(indexed_orders))
    ) as executor:
        futures = {
            executor.submit(client.purchase_order_detail, po_code): (
                index,
                order,
                po_code,
            )
            for index, order, po_code in indexed_orders
        }
        try:
            for processed_orders, future in enumerate(as_completed(futures), start=1):
                index, order, po_code = futures[future]
                order_details[index] = (order, future.result())
                update_progress(processed_orders, po_code)
        except Exception:
            for future in futures:
                future.cancel()
            raise

    return [detail for detail in order_details if detail is not None]


def _fetch_incremental_purchase_order_details(
    client: GerpgoClient,
    orders: list[dict],
    cached_orders: dict[str, dict],
    last_full_verified_at: datetime | None,
    update_progress: Callable[[int, str], None],
    now: datetime | None = None,
) -> tuple[list[tuple[dict, dict]], dict, datetime]:
    current_time = now or datetime.now(timezone.utc)
    if full_verification_due(last_full_verified_at, current_time):
        order_details = _fetch_purchase_order_details(
            client,
            orders,
            update_progress,
        )
        return (
            order_details,
            {
                "detail_request_count": len(orders),
                "cache_hit_count": 0,
                "changed_order_count": 0,
                "sampled_order_count": 0,
                "sample_mismatch_count": 0,
                "incremental_fallback": False,
                "forced_full_reason": "daily_full",
            },
            current_time,
        )

    sample_key = current_time.astimezone().date().isoformat()
    plan = plan_incremental_detail_fetch(
        orders,
        cached_orders,
        sample_key,
    )
    if plan.force_full_reason:
        order_details = _fetch_purchase_order_details(
            client,
            orders,
            update_progress,
        )
        return (
            order_details,
            {
                "detail_request_count": len(orders),
                "cache_hit_count": 0,
                "changed_order_count": 0,
                "sampled_order_count": 0,
                "sample_mismatch_count": 0,
                "incremental_fallback": False,
                "forced_full_reason": plan.force_full_reason,
            },
            current_time,
        )

    cached_count = len(plan.cached_details)
    if cached_count:
        update_progress(cached_count, "")

    def update_incremental_progress(processed: int, current_order: str) -> None:
        update_progress(cached_count + processed, current_order)

    fetched = _fetch_purchase_order_details(
        client,
        plan.fetch_orders,
        update_incremental_progress,
    )
    fetched_by_code = {
        str(order.get("code") or order.get("poCode") or "").strip(): detail
        for order, detail in fetched
    }
    mismatch_count = 0
    for code in plan.sampled_codes:
        try:
            matches = (
                payload_hash(fetched_by_code[code])
                == cached_orders[code]["detail_hash"]
            )
        except (KeyError, TypeError, ValueError):
            matches = False
        if not matches:
            mismatch_count += 1

    request_count = len(plan.fetch_orders)
    if mismatch_count:
        update_progress(0, "")
        order_details = _fetch_purchase_order_details(
            client,
            orders,
            update_progress,
        )
        return (
            order_details,
            {
                "detail_request_count": request_count + len(orders),
                "cache_hit_count": 0,
                "changed_order_count": len(plan.changed_codes),
                "sampled_order_count": len(plan.sampled_codes),
                "sample_mismatch_count": mismatch_count,
                "incremental_fallback": True,
                "forced_full_reason": "sample_mismatch",
            },
            current_time,
        )

    order_details = []
    for order in orders:
        code = str(order.get("code") or order.get("poCode") or "").strip()
        detail = (
            plan.cached_details[code]
            if code in plan.cached_details
            else fetched_by_code[code]
        )
        order_details.append((order, detail))
    return (
        order_details,
        {
            "detail_request_count": request_count,
            "cache_hit_count": cached_count,
            "changed_order_count": len(plan.changed_codes),
            "sampled_order_count": len(plan.sampled_codes),
            "sample_mismatch_count": 0,
            "incremental_fallback": False,
            "forced_full_reason": None,
        },
        last_full_verified_at,
    )


def _execute_purchase_sync(
    database: Database,
    job_id: int,
    claim_token: str,
    storage_root: Path,
) -> None:
    sync_mode = os.getenv("PURCHASE_SYNC_MODE", "incremental").strip().lower()
    if sync_mode not in PURCHASE_SYNC_MODES:
        raise RuntimeError(f"未知采购同步模式：{sync_mode}")

    with database.session() as session:
        job = session.get(PurchaseSyncJob, job_id)
        if job is None:
            raise RuntimeError("采购同步任务不存在")
        base_version = (
            session.get(InputVersion, job.base_version_id)
            if job.base_version_id is not None
            else None
        )
        base_path = Path(base_version.storage_path) if base_version else None

    client = GerpgoClient.from_config(storage_root)
    orders = client.list_purchase_orders()
    _purchase_sync_heartbeat(
        database,
        job_id,
        claim_token,
        total_orders=len(orders),
        processed_orders=0,
    )

    def update_progress(processed_orders: int, current_order: str) -> None:
        _purchase_sync_heartbeat(
            database,
            job_id,
            claim_token,
            processed_orders=processed_orders,
            current_order=current_order,
        )

    source_identity = purchase_cache_source_identity(
        client.base_url,
        client.app_id,
    )
    detail_cache_path = purchase_detail_cache_path(storage_root)
    cache_state = load_purchase_detail_cache_state(
        detail_cache_path,
        source_identity,
    )

    incremental_stats = None
    last_full_verified_at = datetime.now(timezone.utc)
    if sync_mode == "incremental":
        (
            order_details,
            incremental_stats,
            last_full_verified_at,
        ) = _fetch_incremental_purchase_order_details(
            client,
            orders,
            cache_state.orders,
            cache_state.last_full_verified_at,
            update_progress,
        )
    else:
        order_details = _fetch_purchase_order_details(
            client,
            orders,
            update_progress,
        )

    shadow_stats = None
    detail_cache_payload = None
    detail_cache_error = None
    try:
        if sync_mode == "shadow":
            shadow_stats = evaluate_shadow_cache(
                cache_state.orders,
                order_details,
            )
        detail_cache_payload = build_purchase_detail_cache(
            source_identity,
            order_details,
            last_full_verified_at,
        )
    except Exception as error:
        # 缓存优化不能影响正式同步结果。
        detail_cache_error = str(error)[:500]

    mapped = map_purchase_orders(order_details)
    findings = [*mapped.issues, *mapped.warnings]
    _purchase_sync_heartbeat(
        database,
        job_id,
        claim_token,
        raw_detail_count=mapped.raw_count,
        eligible_detail_count=mapped.eligible_count,
        filtered_detail_count=mapped.filtered_count,
        issues=findings,
        current_order=None,
    )
    if mapped.issues:
        with database.session() as session:
            job = session.scalar(
                select(PurchaseSyncJob)
                .where(PurchaseSyncJob.id == job_id)
                .with_for_update()
            )
            if job is None or job.status != "running" or job.claim_token != claim_token:
                raise LostJobLeaseError("采购同步任务租约已失效")
            now = datetime.utcnow()
            job.status = "blocked"
            job.active_slot = None
            job.finished_at = now
            job.heartbeat_at = now
            job.claim_token = None
            session.add(
                AuditLog(
                    user_id=job.created_by,
                    action="purchase_sync_blocked",
                    entity_type="purchase_sync_job",
                    entity_id=str(job.id),
                    details={"issue_count": len(mapped.issues)},
                )
            )
            session.commit()
        return

    candidate = purchase_frame(mapped.rows)
    current = (
        read_purchase_workbook(base_path)
        if base_path is not None and base_path.is_file()
        else None
    )
    difference = compare_purchase_frames(current, candidate)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    original_name = f"积加采购数据_{timestamp}.xlsx"
    candidate_path = (
        storage_root / "master" / "purchase" / f"purchase_sync_{job_id}_{original_name}"
    )
    write_purchase_workbook(candidate_path, candidate)
    read_purchase_workbook(candidate_path)
    try:
        with database.session() as session:
            job = session.scalar(
                select(PurchaseSyncJob)
                .where(PurchaseSyncJob.id == job_id)
                .with_for_update()
            )
            if job is None or job.status != "running" or job.claim_token != claim_token:
                raise LostJobLeaseError("采购同步任务租约已失效")
            version = InputVersion(
                kind="purchase",
                name=f"积加同步-{timestamp}-#{job.id}",
                original_name=original_name,
                storage_path=str(candidate_path),
                active=False,
                created_by=job.created_by,
            )
            session.add(version)
            session.flush()
            now = datetime.utcnow()
            job.status = "succeeded"
            job.active_slot = None
            job.candidate_version_id = version.id
            job.diff = difference
            job.finished_at = now
            job.heartbeat_at = now
            job.claim_token = None
            audit_details = {
                "candidate_version_id": version.id,
                "warning_count": len(mapped.warnings),
                "purchase_sync_mode": sync_mode,
                "detail_request_count": (
                    incremental_stats["detail_request_count"]
                    if incremental_stats is not None
                    else len(order_details)
                ),
            }
            if incremental_stats is not None:
                audit_details.update(incremental_stats)
            if shadow_stats is not None:
                audit_details.update(
                    {
                        "shadow_cached_orders": shadow_stats.cached_orders,
                        "shadow_current_orders": shadow_stats.current_orders,
                        "shadow_duplicate_orders": shadow_stats.duplicate_orders,
                        "shadow_comparable_orders": (shadow_stats.comparable_orders),
                        "shadow_matching_orders": shadow_stats.matching_orders,
                        "shadow_mismatched_orders": (shadow_stats.mismatched_orders),
                    }
                )
            if detail_cache_error:
                audit_details["detail_cache_error"] = detail_cache_error
            session.add(
                AuditLog(
                    user_id=job.created_by,
                    action="purchase_sync_succeeded",
                    entity_type="purchase_sync_job",
                    entity_id=str(job.id),
                    details=audit_details,
                )
            )
            session.commit()
    except Exception:
        candidate_path.unlink(missing_ok=True)
        raise
    if detail_cache_payload is not None:
        try:
            write_purchase_detail_cache(
                detail_cache_path,
                detail_cache_payload,
            )
        except Exception as error:
            print(f"采购同步影子缓存写入失败：{error}")


def _fail_purchase_sync(
    database: Database,
    job_id: int,
    claim_token: str,
    message: str,
) -> None:
    with database.session() as session:
        job = session.scalar(
            select(PurchaseSyncJob)
            .where(PurchaseSyncJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "running" or job.claim_token != claim_token:
            return
        now = datetime.utcnow()
        job.status = "failed"
        job.active_slot = None
        job.error_message = message
        job.finished_at = now
        job.heartbeat_at = now
        job.claim_token = None
        session.add(
            AuditLog(
                user_id=job.created_by,
                action="purchase_sync_failed",
                entity_type="purchase_sync_job",
                entity_id=str(job.id),
                details={"error": message},
            )
        )
        session.commit()


def _execute_self_operated_inbound_sync(
    database: Database,
    job_id: int,
    claim_token: str,
    storage_root: Path,
) -> None:
    with database.session() as session:
        job = session.get(SelfOperatedInboundSyncJob, job_id)
        if job is None:
            raise RuntimeError("待入库同步任务不存在")
        base_version = (
            session.get(InputVersion, job.base_version_id)
            if job.base_version_id is not None
            else None
        )
        base_path = Path(base_version.storage_path) if base_version else None

    client = GerpgoClient.from_config(storage_root)
    orders = client.list_self_operated_inbound_orders()
    mapped = map_self_operated_inbound_orders(orders)
    findings = [*mapped.issues, *mapped.warnings]
    _self_operated_inbound_sync_heartbeat(
        database,
        job_id,
        claim_token,
        total_orders=len(orders),
        raw_detail_count=mapped.raw_count,
        eligible_detail_count=mapped.eligible_count,
        filtered_detail_count=mapped.filtered_count,
        issues=findings,
    )
    if mapped.issues:
        with database.session() as session:
            job = session.scalar(
                select(SelfOperatedInboundSyncJob)
                .where(SelfOperatedInboundSyncJob.id == job_id)
                .with_for_update()
            )
            if job is None or job.status != "running" or job.claim_token != claim_token:
                raise LostJobLeaseError("待入库同步任务租约已失效")
            now = datetime.utcnow()
            job.status = "blocked"
            job.active_slot = None
            job.finished_at = now
            job.heartbeat_at = now
            job.claim_token = None
            session.add(
                AuditLog(
                    user_id=job.created_by,
                    action="self_operated_inbound_sync_blocked",
                    entity_type="self_operated_inbound_sync_job",
                    entity_id=str(job.id),
                    details={"issue_count": len(mapped.issues)},
                )
            )
            session.commit()
        return

    candidate = self_operated_inbound_frame(mapped.rows)
    current = (
        read_self_operated_inbound_workbook(base_path)
        if base_path is not None and base_path.is_file()
        else None
    )
    difference = compare_self_operated_inbound_frames(current, candidate)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    original_name = f"积加待入库数据_{timestamp}.xlsx"
    candidate_path = (
        storage_root
        / "master"
        / "self_operated_inbound"
        / f"self_operated_inbound_sync_{job_id}_{original_name}"
    )
    write_self_operated_inbound_source(candidate_path, candidate)
    read_self_operated_inbound_workbook(candidate_path)
    try:
        with database.session() as session:
            job = session.scalar(
                select(SelfOperatedInboundSyncJob)
                .where(SelfOperatedInboundSyncJob.id == job_id)
                .with_for_update()
            )
            if job is None or job.status != "running" or job.claim_token != claim_token:
                raise LostJobLeaseError("待入库同步任务租约已失效")
            version = InputVersion(
                kind="self_operated_inbound",
                name=f"积加待入库-{timestamp}-#{job.id}",
                original_name=original_name,
                storage_path=str(candidate_path),
                active=False,
                created_by=job.created_by,
            )
            session.add(version)
            session.flush()
            now = datetime.utcnow()
            job.status = "succeeded"
            job.active_slot = None
            job.candidate_version_id = version.id
            job.diff = difference
            job.finished_at = now
            job.heartbeat_at = now
            job.claim_token = None
            session.add(
                AuditLog(
                    user_id=job.created_by,
                    action="self_operated_inbound_sync_succeeded",
                    entity_type="self_operated_inbound_sync_job",
                    entity_id=str(job.id),
                    details={
                        "candidate_version_id": version.id,
                        "warning_count": len(mapped.warnings),
                    },
                )
            )
            session.commit()
    except Exception:
        candidate_path.unlink(missing_ok=True)
        raise


def _fail_self_operated_inbound_sync(
    database: Database,
    job_id: int,
    claim_token: str,
    message: str,
) -> None:
    with database.session() as session:
        job = session.scalar(
            select(SelfOperatedInboundSyncJob)
            .where(SelfOperatedInboundSyncJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "running" or job.claim_token != claim_token:
            return
        now = datetime.utcnow()
        job.status = "failed"
        job.active_slot = None
        job.error_message = message
        job.finished_at = now
        job.heartbeat_at = now
        job.claim_token = None
        session.add(
            AuditLog(
                user_id=job.created_by,
                action="self_operated_inbound_sync_failed",
                entity_type="self_operated_inbound_sync_job",
                entity_id=str(job.id),
                details={"error": message},
            )
        )
        session.commit()


def _fail_job(
    database: Database,
    job_id: int,
    claim_token: str,
    message: str,
) -> None:
    with database.session() as session:
        job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.claim_token != claim_token:
            return
        job.status = "failed"
        job.error_message = message
        job.finished_at = datetime.utcnow()
        job.heartbeat_at = job.finished_at
        job.claim_token = None
        batch = session.get(Batch, job.batch_id)
        if batch is not None:
            batch.error_message = message
            if job.kind == "compute":
                batch.status = "failed"
        session.add(
            AuditLog(
                user_id=None,
                action=f"worker_{job.kind}_failed",
                entity_type="job",
                entity_id=str(job.id),
                details={"error": message},
            )
        )
        session.commit()


WORKER_QUEUES = ("all", "batch", "purchase-sync", "inbound-sync")


def run_once(
    database_url: str,
    storage_root: Path | str,
    queue: str = "all",
) -> int | None:
    if queue not in WORKER_QUEUES:
        raise ValueError(f"未知 Worker 队列：{queue}")
    database = Database(database_url)
    try:
        claimed = _claim_job(database) if queue in {"all", "batch"} else None
        if claimed is not None:
            job_id, batch_id, kind, claim_token = claimed
            try:
                if kind == "compute":
                    _execute_compute(database, job_id, batch_id, claim_token)
                elif kind == "export":
                    _execute_export(
                        database,
                        job_id,
                        batch_id,
                        claim_token,
                        Path(storage_root),
                    )
                else:
                    raise RuntimeError(f"未知任务类型：{kind}")
            except Exception as error:
                _fail_job(database, job_id, claim_token, str(error))
            return job_id
        if queue == "batch":
            return None

        sync_claimed = (
            _claim_purchase_sync_job(database)
            if queue in {"all", "purchase-sync"}
            else None
        )
        if sync_claimed is not None:
            job_id, claim_token = sync_claimed
            try:
                _execute_purchase_sync(
                    database,
                    job_id,
                    claim_token,
                    Path(storage_root),
                )
            except Exception as error:
                _fail_purchase_sync(database, job_id, claim_token, str(error))
            return job_id
        if queue == "purchase-sync":
            return None

        inbound_sync_claimed = _claim_self_operated_inbound_sync_job(database)
        if inbound_sync_claimed is None:
            return None
        job_id, claim_token = inbound_sync_claimed
        try:
            _execute_self_operated_inbound_sync(
                database,
                job_id,
                claim_token,
                Path(storage_root),
            )
        except Exception as error:
            _fail_self_operated_inbound_sync(
                database,
                job_id,
                claim_token,
                str(error),
            )
        return job_id
    finally:
        database.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="交货处理后台任务 Worker")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "sqlite+pysqlite:///delivery_note.db"),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(os.getenv("STORAGE_ROOT", "storage")),
    )
    parser.add_argument("--queue", choices=WORKER_QUEUES, default="all")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--stale-minutes", type=int, default=30)
    return parser


def _watch_stale_jobs(
    database_url: str,
    stale_after: timedelta,
    stop_event: Event,
) -> None:
    while not stop_event.wait(60):
        try:
            recovered = recover_stale_jobs(database_url, stale_after=stale_after)
            if recovered:
                print(
                    f"已回收 {recovered} 个超时任务，退出 Worker 交由进程管理器重启",
                    flush=True,
                )
                os._exit(1)
        except Exception as error:
            print(f"任务恢复扫描失败：{error}", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stop_event = Event()
    previous_handlers = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        recover_stale_jobs(
            args.database_url,
            stale_after=timedelta(minutes=args.stale_minutes),
        )
        if args.once:
            run_once(args.database_url, args.storage_root, args.queue)
            return 0
        stale_after = timedelta(minutes=args.stale_minutes)
        watcher = Thread(
            target=_watch_stale_jobs,
            args=(args.database_url, stale_after, stop_event),
            name="delivery-note-stale-job-watcher",
            daemon=True,
        )
        watcher.start()
        try:
            while not stop_event.is_set():
                if run_once(args.database_url, args.storage_root, args.queue) is None:
                    stop_event.wait(args.poll_interval)
        finally:
            stop_event.set()
            watcher.join(timeout=5)
        return 0
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
