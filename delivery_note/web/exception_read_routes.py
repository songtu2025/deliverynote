import json
from collections.abc import Callable, Iterator, Sequence
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .batch_read_routes import MAX_LIST_PAGE_SIZE
from .caches import PositionFrameCache
from .dependencies import BatchLookup
from .exception_views import (
    ExceptionRenderer,
    PositionLookup,
    PositionValuesByException,
    SplitLookup,
    _exception_review_stats,
)
from .models import (
    BatchFile,
    ExceptionRecord,
    SelfOperatedBatch,
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


def register_exception_read_routes(
    app: FastAPI,
    *,
    get_session: Callable[[], Iterator[Session]],
    current_user: Callable[..., User],
    get_batch_or_404: BatchLookup,
    exception_position_values: PositionLookup,
    position_frame_cache: PositionFrameCache,
    split_records_by_exception: SplitLookup,
    exception_json: ExceptionRenderer,
) -> None:
    @app.get("/api/batches/{batch_id}/exceptions", response_model=None)
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
    ) -> list[dict[str, object]] | dict[str, object]:
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
        filtered_positions: PositionValuesByException | None = None
        exceptions: Sequence[ExceptionRecord]
        if search.strip() or scale_position or stocking_position:
            filtered_positions = {}
            keyword = search.strip().casefold()
            total = 0
            selected_exceptions: list[ExceptionRecord] = []
            with session.execute(
                query.add_columns(BatchFile.original_name).execution_options(
                    yield_per=MAX_LIST_PAGE_SIZE
                )
            ) as candidates:
                for chunk in candidates.partitions(MAX_LIST_PAGE_SIZE):
                    positions = (
                        {}
                        if self_operated
                        else exception_position_values(
                            [record for record, _ in chunk],
                            batch,
                            session,
                            position_frame_cache,
                        )
                    )
                    for record, filename in chunk:
                        values = positions.get(record.id, {})
                        scale = values.get("scale_position", "")
                        stocking = values.get("stocking_position", "")
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
                        if scale_position and scale_position not in (
                            _position_filter_values(scale)
                        ):
                            continue
                        if stocking_position and stocking_position not in (
                            _position_filter_values(stocking)
                        ):
                            continue
                        if limit is None and total >= MAX_LIST_PAGE_SIZE:
                            raise HTTPException(
                                status_code=422,
                                detail="结果超过 200 条，请使用分页查询",
                            )
                        if limit is None or offset <= total < offset + limit:
                            selected_exceptions.append(record)
                            if record.id in positions:
                                filtered_positions[record.id] = values
                        total += 1
            exceptions = selected_exceptions
        elif limit is None:
            exceptions = session.scalars(query.limit(MAX_LIST_PAGE_SIZE + 1)).all()
            if len(exceptions) > MAX_LIST_PAGE_SIZE:
                raise HTTPException(
                    status_code=422, detail="结果超过 200 条，请使用分页查询"
                )
        else:
            total = (
                session.scalar(
                    select(func.count(ExceptionRecord.id))
                    .join(BatchFile, ExceptionRecord.batch_file_id == BatchFile.id)
                    .where(*conditions)
                )
                or 0
            )
            exceptions = session.scalars(query.offset(offset).limit(limit)).all()
        position_values = (
            filtered_positions
            if filtered_positions is not None
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

    @app.get("/api/batches/{batch_id}/exceptions/filters", response_model=None)
    def exception_filters(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[str]]:
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
