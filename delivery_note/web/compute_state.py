"""清除可重建的计算明细，供 API 重排与 Worker 保存共用。"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import ExceptionRecord, SplitRecord


def clear_compute_results(session: Session, source_ids: list[int]) -> None:
    exception_ids = session.scalars(
        select(ExceptionRecord.id).where(ExceptionRecord.batch_file_id.in_(source_ids))
    ).all()
    if exception_ids:
        session.execute(
            delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
        )
        session.execute(
            delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
        )
