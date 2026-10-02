from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import signal
from threading import Event, Thread

from sqlalchemy import select

from .excel_io import (
    read_purchase_workbook,
    read_self_operated_inbound_workbook,
)
from .gerpgo import GerpgoClient
from .purchase_detail_cache import (
    build_purchase_detail_cache,
    evaluate_shadow_cache,
    load_purchase_detail_cache_state,
    purchase_cache_source_identity,
    purchase_detail_cache_path,
    write_purchase_detail_cache,
)
from .purchase_sync import (
    compare_purchase_frames,
    map_purchase_orders,
    purchase_frame,
    write_purchase_workbook,
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
    InputVersion,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)
from .workers.purchase_details import (
    _fetch_purchase_order_details,
    _fetch_incremental_purchase_order_details,
)
from .workers.export_delivery import _execute_export
from .workers.compute_delivery import _execute_compute
from .workers.leases import (
    WORKER_QUEUES,
    JobContext,
    LeaseKeeper,
    LostJobLeaseError,
    _claim_job,
    _heartbeat,
    _claim_purchase_sync_job,
    _purchase_sync_heartbeat,
    _claim_self_operated_inbound_sync_job,
    _self_operated_inbound_sync_heartbeat,
)
from .workers.recovery import _recover_stale_jobs, _watch_stale_jobs
from .workers.recovery import recover_stale_jobs as recover_stale_jobs


PURCHASE_SYNC_MODES = {"full", "shadow", "incremental"}
LOGGER = logging.getLogger(__name__)


def _execute_purchase_sync(
    database: Database,
    job_id: int,
    claim_token: str,
    storage_root: Path,
    before_finalize: Callable[[], None],
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
            cache_state,
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
        before_finalize()
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
        before_finalize()
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
    before_finalize: Callable[[], None],
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
        before_finalize()
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
        before_finalize()
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


def _run_batch_job(
    database: Database,
    claimed: tuple[int, int, str, str],
    storage_root: Path | str,
) -> int:
    job_id, batch_id, kind, claim_token = claimed
    try:
        with LeaseKeeper(
            lambda: _heartbeat(database, job_id, claim_token),
            "batch",
            job_id,
            claim_token,
        ) as lease_keeper:
            if kind == "compute":
                _execute_compute(
                    database,
                    job_id,
                    batch_id,
                    claim_token,
                    lease_keeper.stop,
                )
            elif kind == "export":
                _execute_export(
                    JobContext(database, job_id, claim_token, lease_keeper.stop),
                    batch_id,
                    Path(storage_root),
                )
            else:
                raise RuntimeError(f"未知任务类型：{kind}")
    except Exception as error:
        LOGGER.exception(
            "Worker 任务执行失败 queue=batch job_id=%s claim=%s",
            job_id,
            claim_token[:8],
        )
        _fail_job(database, job_id, claim_token, str(error))
    return job_id


def _run_purchase_job(
    database: Database,
    sync_claimed: tuple[int, str],
    storage_root: Path | str,
) -> int:
    job_id, claim_token = sync_claimed
    try:
        with LeaseKeeper(
            lambda: _purchase_sync_heartbeat(
                database,
                job_id,
                claim_token,
            ),
            "purchase-sync",
            job_id,
            claim_token,
        ) as lease_keeper:
            _execute_purchase_sync(
                database,
                job_id,
                claim_token,
                Path(storage_root),
                lease_keeper.stop,
            )
    except Exception as error:
        LOGGER.exception(
            "Worker 任务执行失败 queue=purchase-sync job_id=%s claim=%s",
            job_id,
            claim_token[:8],
        )
        _fail_purchase_sync(database, job_id, claim_token, str(error))
    return job_id


def _run_inbound_job(
    database: Database,
    inbound_sync_claimed: tuple[int, str],
    storage_root: Path | str,
) -> int:
    job_id, claim_token = inbound_sync_claimed
    try:
        with LeaseKeeper(
            lambda: _self_operated_inbound_sync_heartbeat(
                database,
                job_id,
                claim_token,
            ),
            "inbound-sync",
            job_id,
            claim_token,
        ) as lease_keeper:
            _execute_self_operated_inbound_sync(
                database,
                job_id,
                claim_token,
                Path(storage_root),
                lease_keeper.stop,
            )
    except Exception as error:
        LOGGER.exception(
            "Worker 任务执行失败 queue=inbound-sync job_id=%s claim=%s",
            job_id,
            claim_token[:8],
        )
        _fail_self_operated_inbound_sync(
            database,
            job_id,
            claim_token,
            str(error),
        )
    return job_id


def _run_once(
    database: Database,
    storage_root: Path | str,
    queue: str = "all",
) -> int | None:
    if queue not in WORKER_QUEUES:
        raise ValueError(f"未知 Worker 队列：{queue}")
    claimed = _claim_job(database) if queue in {"all", "batch"} else None
    if claimed is not None:
        return _run_batch_job(database, claimed, storage_root)
    if queue == "batch":
        return None
    sync_claimed = (
        _claim_purchase_sync_job(database)
        if queue in {"all", "purchase-sync"}
        else None
    )
    if sync_claimed is not None:
        return _run_purchase_job(database, sync_claimed, storage_root)
    if queue == "purchase-sync":
        return None
    inbound_sync_claimed = _claim_self_operated_inbound_sync_job(database)
    if inbound_sync_claimed is None:
        return None
    return _run_inbound_job(database, inbound_sync_claimed, storage_root)


def run_once(
    database_url: str,
    storage_root: Path | str,
    queue: str = "all",
) -> int | None:
    if queue not in WORKER_QUEUES:
        raise ValueError(f"未知 Worker 队列：{queue}")
    database = Database(database_url)
    try:
        return _run_once(database, storage_root, queue)
    finally:
        database.dispose()


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须是整数") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


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
    parser.add_argument(
        "--max-attempts",
        type=_positive_int,
        default=os.getenv("WORKER_MAX_ATTEMPTS", "3"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stop_event = Event()
    previous_handlers = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        database = Database(args.database_url)
        try:
            _recover_stale_jobs(
                database,
                stale_after=timedelta(minutes=args.stale_minutes),
                queue=args.queue,
                max_attempts=args.max_attempts,
            )
            if args.once:
                _run_once(database, args.storage_root, args.queue)
                return 0
            stale_after = timedelta(minutes=args.stale_minutes)
            watcher = Thread(
                target=_watch_stale_jobs,
                args=(
                    database,
                    stale_after,
                    stop_event,
                    args.queue,
                    args.max_attempts,
                ),
                name="delivery-note-stale-job-watcher",
                daemon=True,
            )
            watcher.start()
            try:
                while not stop_event.is_set():
                    if _run_once(database, args.storage_root, args.queue) is None:
                        stop_event.wait(args.poll_interval)
            finally:
                stop_event.set()
                watcher.join()
            return 0
        finally:
            database.dispose()
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
