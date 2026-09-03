from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import ceil
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


CACHE_SCHEMA_VERSION = 1
CACHE_FILENAME = "purchase-details-v1.json"
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class ShadowCacheStats:
    cached_orders: int
    current_orders: int
    duplicate_orders: int
    comparable_orders: int
    matching_orders: int
    mismatched_orders: int


@dataclass(frozen=True)
class PurchaseDetailCacheState:
    orders: dict[str, dict[str, Any]]
    last_full_verified_at: datetime | None


@dataclass(frozen=True)
class IncrementalDetailPlan:
    fetch_orders: list[dict[str, Any]]
    cached_details: dict[str, dict[str, Any]]
    sampled_codes: frozenset[str]
    changed_codes: frozenset[str]
    force_full_reason: str | None = None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def purchase_cache_source_identity(base_url: str, app_id: str) -> str:
    return payload_hash(
        {
            "base_url": str(base_url).strip().rstrip("/"),
            "app_id": str(app_id).strip(),
        }
    )


def purchase_detail_cache_path(storage_root: str | Path) -> Path:
    return Path(storage_root) / "cache" / CACHE_FILENAME


def _purchase_order_code(order: dict[str, Any]) -> str:
    return str(
        order.get("code") or order.get("poCode") or order.get("purchaseOrderCode") or ""
    ).strip()


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unique_order_details(
    order_details: list[tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[dict[str, tuple[dict[str, Any], dict[str, Any]]], int]:
    codes = [_purchase_order_code(order) for order, _ in order_details]
    counts = Counter(code for code in codes if code)
    duplicate_orders = sum(count for count in counts.values() if count > 1)
    unique = {
        code: (order, detail)
        for code, (order, detail) in zip(codes, order_details)
        if code and counts[code] == 1
    }
    return unique, duplicate_orders


def load_purchase_detail_cache_state(
    path: str | Path,
    source_identity: str,
) -> PurchaseDetailCacheState:
    cache_path = Path(path)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return PurchaseDetailCacheState({}, None)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != CACHE_SCHEMA_VERSION
        or payload.get("source_identity") != source_identity
        or not isinstance(payload.get("orders"), dict)
    ):
        return PurchaseDetailCacheState({}, None)
    valid_orders: dict[str, dict[str, Any]] = {}
    for code, entry in payload["orders"].items():
        if not isinstance(code, str) or not isinstance(entry, dict):
            continue
        detail = entry.get("detail")
        detail_hash = entry.get("detail_hash")
        list_fingerprint = entry.get("list_fingerprint")
        if (
            not isinstance(detail, dict)
            or not isinstance(detail_hash, str)
            or not isinstance(list_fingerprint, str)
        ):
            continue
        try:
            if payload_hash(detail) != detail_hash:
                continue
        except (TypeError, ValueError):
            continue
        valid_orders[code] = entry
    last_full_verified_at = _timestamp(
        payload.get("last_full_verified_at") or payload.get("created_at")
    )
    return PurchaseDetailCacheState(valid_orders, last_full_verified_at)


def load_purchase_detail_cache(
    path: str | Path,
    source_identity: str,
) -> dict[str, dict[str, Any]]:
    return load_purchase_detail_cache_state(path, source_identity).orders


def full_verification_due(
    last_full_verified_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if last_full_verified_at is None:
        return True
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (
        last_full_verified_at.astimezone(BUSINESS_TIMEZONE).date()
        != current.astimezone(BUSINESS_TIMEZONE).date()
    )


def plan_incremental_detail_fetch(
    orders: list[dict[str, Any]],
    cached_orders: dict[str, dict[str, Any]],
    sample_key: str,
    sample_ratio: float = 0.1,
    minimum_sample_size: int = 5,
) -> IncrementalDetailPlan:
    codes = [_purchase_order_code(order) for order in orders]
    if any(not code for code in codes):
        return IncrementalDetailPlan([], {}, frozenset(), frozenset(), "missing_code")
    counts = Counter(codes)
    if any(count > 1 for count in counts.values()):
        return IncrementalDetailPlan([], {}, frozenset(), frozenset(), "duplicate_code")
    if not cached_orders:
        return IncrementalDetailPlan([], {}, frozenset(), frozenset(), "empty_cache")

    unchanged_codes: list[str] = []
    changed_codes: set[str] = set()
    try:
        for order, code in zip(orders, codes):
            cached = cached_orders.get(code)
            if cached and cached.get("list_fingerprint") == payload_hash(order):
                unchanged_codes.append(code)
            else:
                changed_codes.add(code)
    except (TypeError, ValueError):
        return IncrementalDetailPlan(
            [],
            {},
            frozenset(),
            frozenset(),
            "fingerprint_error",
        )

    sample_size = min(
        len(unchanged_codes),
        max(minimum_sample_size, ceil(len(unchanged_codes) * sample_ratio)),
    )
    sampled_codes = frozenset(
        sorted(
            unchanged_codes,
            key=lambda code: payload_hash([sample_key, code]),
        )[:sample_size]
    )
    fetch_codes = changed_codes | set(sampled_codes)
    fetch_orders = [order for order, code in zip(orders, codes) if code in fetch_codes]
    cached_details = {
        code: cached_orders[code]["detail"]
        for code in unchanged_codes
        if code not in sampled_codes
    }
    return IncrementalDetailPlan(
        fetch_orders=fetch_orders,
        cached_details=cached_details,
        sampled_codes=sampled_codes,
        changed_codes=frozenset(changed_codes),
    )


def evaluate_shadow_cache(
    cached_orders: dict[str, dict[str, Any]],
    order_details: list[tuple[dict[str, Any], dict[str, Any]]],
) -> ShadowCacheStats:
    unique_orders, duplicate_orders = _unique_order_details(order_details)
    comparable_orders = 0
    matching_orders = 0
    mismatched_orders = 0
    for code, (order, detail) in unique_orders.items():
        cached = cached_orders.get(code)
        if not cached or cached.get("list_fingerprint") != payload_hash(order):
            continue
        comparable_orders += 1
        if cached.get("detail_hash") == payload_hash(detail):
            matching_orders += 1
        else:
            mismatched_orders += 1
    return ShadowCacheStats(
        cached_orders=len(cached_orders),
        current_orders=len(order_details),
        duplicate_orders=duplicate_orders,
        comparable_orders=comparable_orders,
        matching_orders=matching_orders,
        mismatched_orders=mismatched_orders,
    )


def build_purchase_detail_cache(
    source_identity: str,
    order_details: list[tuple[dict[str, Any], dict[str, Any]]],
    last_full_verified_at: datetime | None = None,
) -> dict[str, Any]:
    unique_orders, _ = _unique_order_details(order_details)
    verified_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "source_identity": source_identity,
        "created_at": verified_at,
        "last_full_verified_at": (last_full_verified_at or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat(),
        "orders": {
            code: {
                "po_code": code,
                "list_fingerprint": payload_hash(order),
                "detail_hash": payload_hash(detail),
                "detail": detail,
                "verified_at": verified_at,
            }
            for code, (order, detail) in unique_orders.items()
        },
    }


def write_purchase_detail_cache(path: str | Path, payload: dict[str, Any]) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(_canonical_json(payload), encoding="utf-8")
        temporary_path.chmod(0o600)
        os.replace(temporary_path, cache_path)
    finally:
        temporary_path.unlink(missing_ok=True)
