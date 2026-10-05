"""待处理记录的拆分查询、锁定库位回填和响应字段。"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, cast

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..exception_reasons import exception_reason_code
from ..processing.models import IMPORT_COLUMNS, POSITION_VALUE_COLUMNS
from ..processing.pending import enrich_pending_import_rows
from .caches import PositionFrameCache
from .models import Batch, BatchFile, ExceptionRecord, InputVersion, SplitRecord


PositionValues = dict[str, str | int | float]
PositionValuesByException = dict[int, PositionValues]
PositionLookup = Callable[
    [Sequence[ExceptionRecord], Batch, Session, PositionFrameCache],
    PositionValuesByException,
]
SplitLookup = Callable[
    [Session, Sequence[ExceptionRecord]], dict[int, list[SplitRecord]]
]


class ExceptionRenderer(Protocol):
    def __call__(
        self,
        exception: ExceptionRecord,
        parts: list[SplitRecord],
        position_values: PositionValues | None = None,
        *,
        self_operated: bool = False,
    ) -> dict[str, object]: ...


def _exception_review_stats(session: Session, batch_id: int) -> dict[str, int | float]:
    rows = session.execute(
        select(
            ExceptionRecord.status,
            func.count(func.distinct(ExceptionRecord.id)),
            func.sum(
                case(
                    (
                        SplitRecord.id.is_(None),
                        case(
                            (
                                ExceptionRecord.status != "resolved",
                                ExceptionRecord.manual_quantity,
                            ),
                            else_=0,
                        ),
                    ),
                    (SplitRecord.resolved.is_(False), SplitRecord.quantity),
                    else_=0,
                )
            ),
        )
        .join(BatchFile, BatchFile.id == ExceptionRecord.batch_file_id)
        .outerjoin(SplitRecord, SplitRecord.exception_id == ExceptionRecord.id)
        .where(BatchFile.batch_id == batch_id)
        .group_by(ExceptionRecord.status)
    )
    counts = {status: (count, quantity or 0) for status, count, quantity in rows}
    resolved_count = counts.get("resolved", (0, 0))[0]
    total_count = sum(count for count, _ in counts.values())
    return {
        "unfinished_count": total_count - resolved_count,
        "unfinished_quantity": sum(quantity for _, quantity in counts.values()),
        "resolved_count": resolved_count,
        "total_count": total_count,
    }


def _split_records_by_exception(
    session: Session,
    exceptions: Sequence[ExceptionRecord],
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
    exceptions: Sequence[ExceptionRecord],
    batch: Batch,
    session: Session,
    position_frame_cache: PositionFrameCache,
) -> PositionValuesByException:
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

    result: PositionValuesByException = {}
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
    position_values: PositionValues | None = None,
    *,
    self_operated: bool = False,
) -> dict[str, object]:
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
