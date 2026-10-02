from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..gerpgo import GerpgoClient
from ..web.models import PurchaseSyncJob
from ..purchase_detail_cache import (
    ShadowCacheStats,
    build_purchase_detail_cache,
    evaluate_shadow_cache,
    load_purchase_detail_cache_state,
    purchase_cache_source_identity,
    purchase_detail_cache_path,
    write_purchase_detail_cache,
)
from ..workers.leases import JobContext, _sync_heartbeat
from ..workers.purchase_details import (
    _fetch_incremental_purchase_order_details,
    _fetch_purchase_order_details,
)


@dataclass
class PurchaseCollection:
    """抓取结果及与本次候选版本对应的缓存验证信息。"""

    sync_mode: str
    order_details: list[tuple[dict[str, Any], dict[str, Any]]]
    detail_cache_path: Path
    detail_cache_payload: dict[str, Any] | None
    detail_cache_error: str | None
    incremental_stats: dict[str, Any] | None
    shadow_stats: ShadowCacheStats | None


def _collect_purchase_details(
    context: JobContext, storage_root: Path, sync_mode: str
) -> PurchaseCollection:
    database, job_id, claim_token = (
        context.database,
        context.job_id,
        context.claim_token,
    )
    client = GerpgoClient.from_config(storage_root)
    orders = client.list_purchase_orders()
    _sync_heartbeat(
        database,
        PurchaseSyncJob,
        job_id,
        claim_token,
        total_orders=len(orders),
        processed_orders=0,
    )

    def update_progress(processed_orders: int, current_order: str) -> None:
        _sync_heartbeat(
            database,
            PurchaseSyncJob,
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
    incremental_stats: dict[str, Any] | None = None
    last_full_verified_at: datetime | None = datetime.now(timezone.utc)
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
    shadow_stats: ShadowCacheStats | None = None
    detail_cache_payload: dict[str, Any] | None = None
    detail_cache_error: str | None = None
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
    return PurchaseCollection(
        sync_mode,
        order_details,
        detail_cache_path,
        detail_cache_payload,
        detail_cache_error,
        incremental_stats,
        shadow_stats,
    )


def _purchase_audit_details(
    collection: PurchaseCollection, warning_count: int
) -> dict[str, Any]:
    incremental_stats = collection.incremental_stats
    shadow_stats = collection.shadow_stats
    audit_details: dict[str, Any] = {
        "warning_count": warning_count,
        "purchase_sync_mode": collection.sync_mode,
        "detail_request_count": incremental_stats["detail_request_count"]
        if incremental_stats is not None
        else len(collection.order_details),
    }
    if incremental_stats is not None:
        audit_details.update(incremental_stats)
    if shadow_stats is not None:
        audit_details.update(
            {
                "shadow_cached_orders": shadow_stats.cached_orders,
                "shadow_current_orders": shadow_stats.current_orders,
                "shadow_duplicate_orders": shadow_stats.duplicate_orders,
                "shadow_comparable_orders": shadow_stats.comparable_orders,
                "shadow_matching_orders": shadow_stats.matching_orders,
                "shadow_mismatched_orders": shadow_stats.mismatched_orders,
            }
        )
    if collection.detail_cache_error:
        audit_details["detail_cache_error"] = collection.detail_cache_error
    return audit_details


def _write_collection_cache(collection: PurchaseCollection) -> None:
    if collection.detail_cache_payload is not None:
        try:
            write_purchase_detail_cache(
                collection.detail_cache_path, collection.detail_cache_payload
            )
        except Exception as error:
            print(f"采购同步影子缓存写入失败：{error}")
