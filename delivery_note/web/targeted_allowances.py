from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..processing.keys import _normalize_position_text as key
from .exception_transfer_state import remaining_quantity_expression
from .models import BatchFile, ExceptionRecord, SelfOperatedBatch


TARGET_FIELDS = ("supplier_code", "sku", "full_site", "inbound_no", "po_code")


def target_identity(entry: dict[str, Any]) -> dict[str, str]:
    return {name: key(entry[name]) for name in TARGET_FIELDS}


def allocation_rows(
    source: BatchFile, sku: str, full_site: str
) -> list[dict[str, Any]]:
    return [
        row
        for row in source.import_rows or []
        if key(row.get("SKU")) == key(sku)
        and key(row.get("平台站点")) == key(full_site)
    ]


def saved_targets(profile: SelfOperatedBatch) -> list[dict[str, Any]]:
    return [
        item
        for item in (profile.manual_handling or {}).get("allowances", [])
        if item.get("inbound_no")
    ]


def allocation_extra(
    row: dict[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    saved = next(
        (
            entry
            for entry in entries
            if (key(entry["inbound_no"]), key(entry["po_code"]))
            == (key(row.get("入库单号")), key(row.get("关联采购单")))
        ),
        {},
    )
    return {
        "extra_quantity": saved.get("quantity", 0),
        "extra_reason": saved.get("reason", ""),
    }


def group_targets(
    entries: list[dict[str, Any]], supplier_code: str, sku: str, full_site: str
) -> list[dict[str, Any]]:
    group = (key(supplier_code), key(sku), key(full_site))
    return [
        entry
        for entry in entries
        if tuple(key(entry[name]) for name in TARGET_FIELDS[:3]) == group
    ]


def pending_capacity(session: Session, source: BatchFile, sku: str, site: str) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(remaining_quantity_expression()), 0)).where(
                ExceptionRecord.batch_file_id == source.id,
                ExceptionRecord.sku == sku,
                ExceptionRecord.full_site == site,
                ExceptionRecord.reason.in_(("超出允许超收量", "超出应收货")),
            )
        )
        or 0
    )


def targeted_input(
    session: Session, batch_id: int, profile: SelfOperatedBatch, item: dict[str, Any]
) -> tuple[dict[str, str], dict[str, object]]:
    identity = target_identity(item)
    source = session.get(BatchFile, item["file_id"])
    if (
        source is None
        or source.batch_id != batch_id
        or key(source.supplier_code) != identity["supplier_code"]
    ):
        raise HTTPException(
            status_code=400, detail="指定追加必须对应本批来源文件和供应商"
        )
    previous = next(
        (
            entry
            for entry in saved_targets(profile)
            if target_identity(entry) == identity
        ),
        None,
    )
    matching = [
        row
        for row in allocation_rows(source, item["sku"], item["full_site"])
        if (key(row.get("入库单号")), key(row.get("关联采购单")))
        == (identity["inbound_no"], identity["po_code"])
    ]
    if not matching and not (previous and item["quantity"] == 0):
        raise HTTPException(
            status_code=400, detail="只能向本次分配明细中已出现的 PO 行追加超收"
        )
    return identity, {
        "supplier_name": source.supplier_name,
        "file_id": source.id,
        "quantity": item["quantity"],
        "reason": item["reason"],
    }


def validate_targeted_totals(
    session: Session, profile: SelfOperatedBatch, items: list[dict[str, Any]]
) -> None:
    saved = saved_targets(profile)
    proposed = {tuple(target_identity(entry).values()): entry for entry in saved}
    for item in items:
        proposed[tuple(target_identity(item).values())] = item
    groups = {
        (item["file_id"], item["supplier_code"], item["sku"], item["full_site"])
        for item in items
    }
    for file_id, supplier, sku, site in groups:
        source = session.get(BatchFile, file_id)
        assert source is not None
        before = sum(
            entry["quantity"] for entry in group_targets(saved, supplier, sku, site)
        )
        after = sum(
            entry["quantity"]
            for entry in group_targets(list(proposed.values()), supplier, sku, site)
        )
        if after > before + pending_capacity(session, source, sku, site):
            raise HTTPException(
                status_code=400,
                detail="合计追加不得超过当前剩余待处理量加已保存的指定追加量",
            )


def allocation_allowances(
    session: Session,
    profile: SelfOperatedBatch,
    source: BatchFile,
    exception: ExceptionRecord,
) -> dict[str, Any]:
    saved = saved_targets(profile)
    entries = group_targets(
        saved, source.supplier_code, exception.sku, exception.full_site
    )
    rows = allocation_rows(source, exception.sku, exception.full_site)
    by_target = {(key(row.get("入库单号")), key(row.get("关联采购单"))) for row in rows}
    inactive = [
        entry
        for entry in saved
        if key(entry["supplier_code"]) == key(source.supplier_code)
        and key(entry["sku"]) == key(exception.sku)
        and (entry.get("file_id") == source.id or entry in entries)
        and (
            key(entry["full_site"]) != key(exception.full_site)
            or (key(entry["inbound_no"]), key(entry["po_code"])) not in by_target
        )
    ]
    return {
        "saved_allowances": entries,
        "inactive_allowances": inactive,
        "allowance_limit": pending_capacity(
            session, source, exception.sku, exception.full_site
        )
        + sum(entry["quantity"] for entry in entries),
    }
