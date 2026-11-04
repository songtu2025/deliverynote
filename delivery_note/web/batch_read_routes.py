from collections.abc import Callable, Iterator, Sequence
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from delivery_note.processing.models import IMPORT_COLUMNS

from .dependencies import BatchLookup
from .models import Batch, BatchFile, SelfOperatedBatch, User


MAX_LIST_PAGE_SIZE = 200


def _import_rows_page(
    session: Session, batch_id: int, offset: int, limit: int, search: str
) -> dict[str, object]:
    fields = (
        "warehouse",
        "supplier_code",
        "sku",
        "quantity",
        "site",
        "document_note",
        "delivery_note",
    )
    keyword = search.strip().casefold()
    items: list[dict[str, object]] = []
    total = 0
    query = (
        select(BatchFile.id, BatchFile.original_name, BatchFile.import_rows)
        .where(BatchFile.batch_id == batch_id)
        .order_by(BatchFile.file_order)
    )
    for file_id, file_name, rows in session.execute(query):
        for row_index, row in enumerate(rows or []):
            item = dict(zip(fields, (row.get(column, "") for column in IMPORT_COLUMNS)))
            item.update(file_id=file_id, file_name=file_name, row_index=row_index)
            if keyword and not any(
                keyword in str(item[field]).casefold()
                for field in ("sku", "site", "warehouse", "file_name")
            ):
                continue
            if offset <= total < offset + limit:
                items.append(item)
            total += 1
    return {"items": items, "total": total}


def register_batch_read_routes(
    app: FastAPI,
    *,
    get_session: Callable[[], Iterator[Session]],
    current_user: Callable[..., User],
    batch_json: Callable[[Batch, Session], dict[str, object]],
    batch_list_json: Callable[[Sequence[Batch], Session], list[dict[str, object]]],
    get_batch_or_404: BatchLookup,
) -> None:
    @app.get("/api/batches", response_model=None)
    def list_batches(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1, le=MAX_LIST_PAGE_SIZE)] = None,
        workflow: Annotated[
            str, Query(pattern="^(|delivery|self_operated_inbound)$")
        ] = "",
        batch_status: str = "",
        search: str = "",
    ) -> list[dict[str, object]] | dict[str, object]:
        conditions = []
        if workflow == "delivery":
            conditions.append(
                ~select(SelfOperatedBatch.batch_id)
                .where(SelfOperatedBatch.batch_id == Batch.id)
                .exists()
            )
        elif workflow == "self_operated_inbound":
            conditions.append(
                select(SelfOperatedBatch.batch_id)
                .where(SelfOperatedBatch.batch_id == Batch.id)
                .exists()
            )
        if batch_status:
            conditions.append(Batch.status == batch_status)
        if search.strip():
            conditions.append(
                func.lower(Batch.name).contains(search.strip().lower(), autoescape=True)
            )
        query = select(Batch).where(*conditions).order_by(Batch.id.desc())
        if limit is None:
            batches = session.scalars(query.limit(MAX_LIST_PAGE_SIZE + 1)).all()
            if len(batches) > MAX_LIST_PAGE_SIZE:
                raise HTTPException(
                    status_code=422, detail="结果超过 200 条，请使用分页查询"
                )
            return batch_list_json(batches, session)

        total = session.scalar(select(func.count(Batch.id)).where(*conditions)) or 0
        batches = session.scalars(query.offset(offset).limit(limit)).all()
        empty_conditions = [
            Batch.status == "draft",
            ~select(BatchFile.id).where(BatchFile.batch_id == Batch.id).exists(),
        ]
        if workflow == "self_operated_inbound":
            empty_query = (
                select(func.count(Batch.id))
                .join(SelfOperatedBatch, SelfOperatedBatch.batch_id == Batch.id)
                .where(*empty_conditions, SelfOperatedBatch.inbound_storage_path == "")
            )
        else:
            empty_query = (
                select(func.count(Batch.id))
                .outerjoin(SelfOperatedBatch, SelfOperatedBatch.batch_id == Batch.id)
                .where(*empty_conditions, SelfOperatedBatch.batch_id.is_(None))
            )
        return {
            "items": batch_list_json(batches, session),
            "total": total,
            "empty_draft_count": session.scalar(empty_query) or 0,
        }

    @app.get("/api/batches/{batch_id}", response_model=None)
    def get_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        return batch_json(get_batch_or_404(batch_id, session), session)

    @app.get("/api/batches/{batch_id}/import-rows", response_model=None)
    def list_import_rows(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_LIST_PAGE_SIZE)] = 10,
        search: str = "",
    ) -> dict[str, object]:
        batch = get_batch_or_404(batch_id, session)
        if session.get(SelfOperatedBatch, batch.id) is not None or not (
            batch.status == "succeeded" or batch.zip_path
        ):
            return {"items": [], "total": 0}
        return _import_rows_page(session, batch.id, offset, limit, search)
