from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import signal
import shutil
from threading import Event, Thread
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from sqlalchemy import delete, select, update

from .application import DeliveryRequest, SplitPart, process_delivery_batch, project_split
from .config import resolve_supplier
from .excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_supplier_workbook,
    write_delivery_workbook,
)
from .pipeline import (
    EXCEPTION_COLUMNS,
    IMPORT_COLUMNS,
    BatchResult,
    OverreceiptPolicy,
    build_manual_import_rows,
    enrich_pending_import_rows,
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
    SplitRecord,
)


class LostJobLease(RuntimeError):
    pass


VERSION_FIELDS = {
    "purchase": "purchase_version_id",
    "product": "product_version_id",
    "supplier": "supplier_version_id",
    "position": "position_version_id",
    "template": "template_version_id",
}


def _json_value(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _json_records(frame: pd.DataFrame) -> list[dict]:
    return [
        {column: _json_value(value) for column, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _version_paths(session, batch: Batch) -> dict[str, Path]:
    result = {}
    for kind, field in VERSION_FIELDS.items():
        version = session.get(InputVersion, getattr(batch, field))
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
            raise LostJobLease("任务租约已失效")


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
            session.commit()
    finally:
        database.dispose()
    return recovered


def _load_compute_inputs(database: Database, batch_id: int):
    with database.session() as session:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise RuntimeError("批次不存在")
        version_paths = _version_paths(session, batch)
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
    return version_paths, source_data, overreceipt_policy


def _execute_compute(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
) -> None:
    _heartbeat(database, job_id, claim_token)
    version_paths, sources, overreceipt_policy = _load_compute_inputs(
        database, batch_id
    )
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
        job = session.scalar(
            select(Job).where(Job.id == job_id).with_for_update()
        )
        batch = session.get(Batch, batch_id)
        if (
            job is None
            or batch is None
            or job.status != "running"
            or job.claim_token != claim_token
        ):
            raise LostJobLease("计算任务租约已失效")
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
        payloads = []
        for source in sources:
            exceptions = session.scalars(
                select(ExceptionRecord)
                .where(ExceptionRecord.batch_file_id == source.id)
                .order_by(ExceptionRecord.id)
            ).all()
            exception_payloads = []
            for exception in exceptions:
                parts = session.scalars(
                    select(SplitRecord)
                    .where(SplitRecord.exception_id == exception.id)
                    .order_by(SplitRecord.id)
                ).all()
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
                            for part in parts
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
    pending_rows = (
        pd.concat(pending_frames, ignore_index=True)
        if pending_frames
        else pd.DataFrame(columns=IMPORT_COLUMNS)
    )
    pending_rows = enrich_pending_import_rows(pending_rows, position_rows)
    import_total = (
        int(import_rows["*本次交货量"].sum()) if not import_rows.empty else 0
    )
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


def _execute_export(
    database: Database,
    job_id: int,
    batch_id: int,
    claim_token: str,
    storage_root: Path,
) -> None:
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
    try:
        for source in sources:
            _heartbeat(database, job_id, claim_token)
            result, import_rows, pending_rows = _prepare_export_result(
                source, position_rows
            )
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

        archive_path = temporary / f"batch-{batch_id}.zip"
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            for source in sources:
                output_name = output_names[source["id"]]
                archive.write(temporary / output_name, arcname=output_name)
        _heartbeat(database, job_id, claim_token)
        os.replace(temporary, published)

        with database.session() as session:
            job = session.scalar(
                select(Job).where(Job.id == job_id).with_for_update()
            )
            batch = session.get(Batch, batch_id)
            if (
                job is None
                or batch is None
                or job.status != "running"
                or job.claim_token != claim_token
            ):
                raise LostJobLease("导出任务租约已失效")
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
                    details={"file_count": len(sources)},
                )
            )
            session.commit()
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        registered_archive = published / f"batch-{batch_id}.zip"
        if (
            published.exists()
            and not _published_is_registered(database, job_id, registered_archive)
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


def _fail_job(
    database: Database,
    job_id: int,
    claim_token: str,
    message: str,
) -> None:
    with database.session() as session:
        job = session.scalar(
            select(Job).where(Job.id == job_id).with_for_update()
        )
        if (
            job is None
            or job.status != "running"
            or job.claim_token != claim_token
        ):
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


def run_once(database_url: str, storage_root: Path | str) -> int | None:
    database = Database(database_url)
    try:
        claimed = _claim_job(database)
        if claimed is None:
            return None
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
            run_once(args.database_url, args.storage_root)
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
                if run_once(args.database_url, args.storage_root) is None:
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
