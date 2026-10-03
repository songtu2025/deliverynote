"""待处理记录的拆分查询、锁定库位回填和响应字段。"""

from pathlib import Path
from typing import cast

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..exception_reasons import exception_reason_code
from ..processing.models import (IMPORT_COLUMNS, POSITION_VALUE_COLUMNS)
from ..pipeline import (enrich_pending_import_rows)
from .caches import PositionFrameCache
from .models import Batch, ExceptionRecord, InputVersion, SplitRecord


def _split_records_by_exception(
    session: Session,
    exceptions: list[ExceptionRecord],
) -> dict[int, list[SplitRecord]]:
    exception_ids = [exception.id for exception in exceptions]
    if not exception_ids:
        return {}
    records = session.scalars(
        select(SplitRecord)
        .where(SplitRecord.exception_id.in_(exception_ids))
        .order_by(SplitRecord.exception_id, SplitRecord.id)
    ).all()
    grouped: dict[int, list[SplitRecord]] = {}
    for record in records:
        grouped.setdefault(record.exception_id, []).append(record)
    return grouped


def _exception_position_values(
    exceptions: list[ExceptionRecord],
    batch: Batch,
    session: Session,
    position_frame_cache: PositionFrameCache,
) -> dict[int, dict[str, str | int | float]]:
    if not exceptions:
        return {}
    version = session.get(InputVersion, batch.position_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="批次锁定的库位资料不存在")
    pending_rows = pd.DataFrame(
        [
            {
                "*目的仓": exception.destination,
                "*供应商编码": "",
                "*SKU": exception.sku,
                "*本次交货量": exception.manual_quantity,
                "*站点": exception.full_site,
                "单据备注": "",
                "交货备注": exception.reason,
            }
            for exception in exceptions
        ],
        index=[exception.id for exception in exceptions],
        columns=IMPORT_COLUMNS,
    )
    try:
        position_rows = position_frame_cache.get(
            version.id,
            Path(version.storage_path),
        )
        enriched = enrich_pending_import_rows(
            pending_rows,
            position_rows,
        )
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=409,
            detail=f"批次锁定的库位资料无法读取：{error}",
        ) from error

    result: dict[int, dict[str, str | int | float]] = {}
    for exception_id, row in enriched.iterrows():
        values = {}
        for column, key in zip(
            POSITION_VALUE_COLUMNS,
            ("scale_position", "stocking_position"),
            strict=True,
        ):
            value = row[column]
            if pd.isna(value):
                value = ""
            elif hasattr(value, "item"):
                value = value.item()
            values[key] = value
        result[cast(int, exception_id)] = values
    return result


def _exception_json(
    exception: ExceptionRecord,
    parts: list[SplitRecord],
    position_values: dict[str, str | int | float] | None = None,
    *,
    self_operated: bool = False,
) -> dict:
    position_values = position_values or {}
    reason_code = exception.reason_code or exception_reason_code(exception.reason)
    if self_operated:
        allowed_actions = (
            ["resolve_site"] if reason_code == "ambiguous_product_site" else []
        )
    else:
        allowed_actions = ["split"]
    return {
        "id": exception.id,
        "batch_file_id": exception.batch_file_id,
        "sku": exception.sku,
        "original_site": exception.original_site,
        "full_site": exception.full_site,
        "destination": exception.destination,
        "delivery_quantity": exception.delivery_quantity,
        "allocated_quantity": exception.allocated_quantity,
        "purchase_allocated_quantity": exception.purchase_allocated_quantity,
        "overreceipt_allocated_quantity": exception.overreceipt_allocated_quantity,
        "overreceipt_remaining_quantity": exception.overreceipt_remaining_quantity,
        "manual_quantity": exception.manual_quantity,
        "reason": exception.reason,
        "reason_code": reason_code,
        "allowed_actions": allowed_actions,
        "status": exception.status,
        "scale_position": position_values.get("scale_position", ""),
        "stocking_position": position_values.get("stocking_position", ""),
        "parts": [
            {
                "id": part.id,
                "quantity": part.quantity,
                "destination": part.destination,
                "site": part.site,
                "supplier_code": part.supplier_code,
                "sku": part.sku,
                "delivery_note": part.delivery_note,
                "resolved": part.resolved,
            }
            for part in parts
        ],
    }
