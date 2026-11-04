from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .models import BatchFile, ExceptionRecord
from .models.batches import ExceptionTransfer


def transferred_quantity_expression() -> ColumnElement[int]:
    return func.coalesce(
        select(func.sum(ExceptionTransfer.quantity))
        .where(ExceptionTransfer.exception_id == ExceptionRecord.id)
        .correlate(ExceptionRecord)
        .scalar_subquery(),
        0,
    )


def remaining_quantity_expression() -> ColumnElement[int]:
    return (
        ExceptionRecord.manual_quantity
        - transferred_quantity_expression()
        - ExceptionRecord.offline_quantity
    )


def require_no_transfer_links(session: Session, batch_ids: list[int]) -> None:
    source_ids = (
        select(ExceptionRecord.id)
        .join(BatchFile)
        .where(BatchFile.batch_id.in_(batch_ids))
    )
    linked = session.scalar(
        select(ExceptionTransfer.id)
        .where(
            or_(
                ExceptionTransfer.exception_id.in_(source_ids),
                ExceptionTransfer.target_batch_id.in_(batch_ids),
            )
        )
        .limit(1)
    )
    if linked is not None:
        raise HTTPException(
            status_code=409, detail="批次已有转交记录，不能删除或重算关联数据"
        )
