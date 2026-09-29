from typing import Annotated, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Batch, BatchFile, SelfOperatedBatch, User


MAX_LIST_PAGE_SIZE = 200


def register_batch_read_routes(
    app: FastAPI,
    *,
    get_session: Callable,
    current_user: Callable,
    batch_json: Callable[[Batch, Session], dict],
    batch_list_json: Callable[[list[Batch], Session], list[dict]],
    get_batch_or_404: Callable[[int, Session], Batch],
) -> None:
    @app.get("/api/batches")
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
    ):
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
                func.lower(Batch.name).contains(
                    search.strip().lower(), autoescape=True
                )
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

    @app.get("/api/batches/{batch_id}")
    def get_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return batch_json(get_batch_or_404(batch_id, session), session)
