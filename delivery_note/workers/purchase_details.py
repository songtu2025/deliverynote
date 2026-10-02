from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from ..gerpgo import GerpgoClient
from ..purchase_detail_cache import (
    PurchaseDetailCacheState,
    full_verification_due,
    payload_hash,
    plan_incremental_detail_fetch,
)

PURCHASE_DETAIL_WORKERS = 8


def _fetch_purchase_order_details(
    client: GerpgoClient,
    orders: list[dict[str, Any]],
    update_progress: Callable[[int, str], None],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    indexed_orders = []
    for index, order in enumerate(orders):
        po_code = str(order.get("code") or order.get("poCode") or "").strip()
        if not po_code:
            raise RuntimeError("积加采购单缺少单号字段 code")
        indexed_orders.append((index, order, po_code))
    if not indexed_orders:
        return []

    order_details: list[tuple[dict[str, Any], dict[str, Any]] | None] = [None] * len(
        orders
    )
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
    orders: list[dict[str, Any]],
    cache_state: PurchaseDetailCacheState,
    update_progress: Callable[[int, str], None],
    now: datetime | None = None,
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any]]], dict[str, Any], datetime | None
]:
    cached_orders = cache_state.orders
    last_full_verified_at = cache_state.last_full_verified_at
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
