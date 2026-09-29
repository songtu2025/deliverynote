import json
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .batch_read_routes import MAX_LIST_PAGE_SIZE
from .models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    SelfOperatedBatch,
    SplitRecord,
    User,
)


def _position_filter_values(value: str | int | float) -> list[str]:
    value_text = str(value if value is not None else "").strip()
    if not value_text:
        return []
    if not value_text.startswith("{"):
        return [value_text]
    try:
        mapping = json.loads(value_text)
    except ValueError:
        return [value_text]
    if not isinstance(mapping, dict):
        return [value_text]
    return list(
        dict.fromkeys(
            value
            for item in mapping.values()
            if (value := str(item if item is not None else "").strip())
        )
    )


def _position_display_value(value: str | int | float) -> str:
    value_text = str(value if value is not None else "").strip()
    if not value_text:
        return "—"
    if not value_text.startswith("{"):
        return value_text
    try:
        mapping = json.loads(value_text)
    except ValueError:
        return value_text
    if not isinstance(mapping, dict):
        return value_text
    return "；".join(
        f"{msku}：{str(item if item is not None else '').strip() or '—'}"
        for msku, item in mapping.items()
    )


def _exception_review_stats(session: Session, batch_id: int) -> dict:
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


def register_exception_read_routes(
    app: FastAPI,
    *,
    get_session: Callable,
    current_user: Callable,
    get_batch_or_404: Callable[[int, Session], Batch],
    exception_position_values: Callable,
    position_frame_cache: object,
    split_records_by_exception: Callable,
    exception_json: Callable,
) -> None:
    @app.get("/api/batches/{batch_id}/exceptions")
    def list_exceptions(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1, le=MAX_LIST_PAGE_SIZE)] = None,
        review_scope: Annotated[
            str, Query(pattern="^(all|unfinished|resolved)$")
        ] = "all",
        reason: str = "",
        site: str = "",
        scale_position: str = "",
        stocking_position: str = "",
        search: str = "",
    ):
        batch = get_batch_or_404(batch_id, session)
        self_operated = session.get(SelfOperatedBatch, batch.id) is not None
        conditions = [BatchFile.batch_id == batch_id]
        if review_scope == "resolved":
            conditions.append(ExceptionRecord.status == "resolved")
        elif review_scope == "unfinished":
            conditions.append(ExceptionRecord.status != "resolved")
        if reason:
            conditions.append(ExceptionRecord.reason == reason)
        if site:
            conditions.append(ExceptionRecord.full_site == site)
        query = (
            select(ExceptionRecord)
            .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
            .where(*conditions)
            .order_by(BatchFile.file_order, ExceptionRecord.id)
        )
        all_positions = None
        if search.strip() or scale_position or stocking_position:
            candidates = session.execute(
                select(ExceptionRecord, BatchFile.original_name)
                .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
                .where(*conditions)
                .order_by(BatchFile.file_order, ExceptionRecord.id)
            ).all()
            candidate_rows = [record for record, _ in candidates]
            all_positions = {} if self_operated else exception_position_values(
                candidate_rows, batch, session, position_frame_cache
            )
            keyword = search.strip().casefold()
            matches = []
            for record, filename in candidates:
                positions = all_positions.get(record.id, {})
                scale = positions.get("scale_position", "")
                stocking = positions.get("stocking_position", "")
                haystack = " ".join(
                    (
                        filename,
                        record.sku,
                        record.full_site,
                        record.destination,
                        _position_display_value(scale),
                        _position_display_value(stocking),
                    )
                ).casefold()
                if keyword and keyword not in haystack:
                    continue
                if scale_position and scale_position not in _position_filter_values(
                    scale
                ):
                    continue
                if stocking_position and stocking_position not in (
                    _position_filter_values(stocking)
                ):
                    continue
                matches.append(record)
            total = len(matches)
            if limit is None and total > MAX_LIST_PAGE_SIZE:
                raise HTTPException(
                    status_code=422, detail="结果超过 200 条，请使用分页查询"
                )
            exceptions = (
                matches[offset : offset + limit] if limit is not None else matches
            )
        elif limit is None:
            exceptions = session.scalars(query.limit(MAX_LIST_PAGE_SIZE + 1)).all()
            if len(exceptions) > MAX_LIST_PAGE_SIZE:
                raise HTTPException(
                    status_code=422, detail="结果超过 200 条，请使用分页查询"
                )
        else:
            total = session.scalar(
                select(func.count(ExceptionRecord.id))
                .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
                .where(*conditions)
            ) or 0
            exceptions = session.scalars(query.offset(offset).limit(limit)).all()
        position_values = (
            all_positions
            if all_positions is not None
            else (
                {}
                if self_operated
                else exception_position_values(
                    exceptions, batch, session, position_frame_cache
                )
            )
        )
        splits_by_exception = split_records_by_exception(
            session,
            exceptions,
        )
        items = [
            exception_json(
                exception,
                splits_by_exception.get(exception.id, []),
                position_values.get(exception.id),
                self_operated=self_operated,
            )
            for exception in exceptions
        ]
        if limit is None:
            return items
        return {
            "items": items,
            "total": total,
            "stats": _exception_review_stats(session, batch_id),
        }

    @app.get("/api/batches/{batch_id}/exceptions/filters")
    def exception_filters(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        reasons = session.scalars(
            select(ExceptionRecord.reason)
            .join(BatchFile, BatchFile.id == ExceptionRecord.batch_file_id)
            .where(BatchFile.batch_id == batch_id)
            .distinct()
        ).all()
        sites = session.scalars(
            select(ExceptionRecord.full_site)
            .join(BatchFile, BatchFile.id == ExceptionRecord.batch_file_id)
            .where(BatchFile.batch_id == batch_id)
            .distinct()
        ).all()
        scales: set[str] = set()
        stocking: set[str] = set()
        if session.get(SelfOperatedBatch, batch_id) is None:
            keys = session.execute(
                select(ExceptionRecord.sku, ExceptionRecord.full_site)
                .join(BatchFile, BatchFile.id == ExceptionRecord.batch_file_id)
                .where(BatchFile.batch_id == batch_id)
                .distinct()
            ).all()
            representatives = [
                ExceptionRecord(
                    id=index,
                    sku=sku,
                    full_site=site,
                    destination="",
                    manual_quantity=0,
                    reason="",
                )
                for index, (sku, site) in enumerate(keys, start=1)
            ]
            for values in exception_position_values(
                representatives, batch, session, position_frame_cache
            ).values():
                scales.update(_position_filter_values(values["scale_position"]))
                stocking.update(_position_filter_values(values["stocking_position"]))
        return {
            "reasons": sorted(filter(None, reasons)),
            "sites": sorted(filter(None, sites)),
            "scales": sorted(scales),
            "stocking": sorted(stocking),
        }
