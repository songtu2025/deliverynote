"""批次交货文件删除和稳定顺序调整。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .batch_views import batch_json
from .dependencies import RequestDependencies
from .models import BatchFile, ExceptionRecord, SplitRecord
from .schemas import FileOrderPayload
from .uploads import _unlink_after_commit


@dataclass
class BatchFileEditor:
    dependencies: RequestDependencies
    audit: Callable[..., None]

    def delete(
        self,
        session: Session,
        batch_id: int,
        file_id: int,
        user_id: int,
    ) -> dict[str, object]:
        batch = self.dependencies.get_editable_batch(
            batch_id, session, for_update=True, detail="当前批次状态不可删除文件"
        )
        source = session.scalar(
            select(BatchFile).where(
                BatchFile.id == file_id,
                BatchFile.batch_id == batch.id,
            )
        )
        if source is None:
            raise HTTPException(status_code=404, detail="交货文件不存在")
        storage_path = Path(source.storage_path)
        exception_ids = session.scalars(
            select(ExceptionRecord.id).where(ExceptionRecord.batch_file_id == source.id)
        ).all()
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
            )
            session.execute(
                delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
            )
        session.delete(source)
        session.flush()
        remaining = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        for item in remaining:
            item.file_order = -item.id
        session.flush()
        for file_order, item in enumerate(remaining, start=1):
            item.file_order = file_order
        batch.status = "draft"
        batch.error_message = None
        batch.zip_path = None
        self.audit(
            session,
            user_id,
            "delete_batch_file",
            "batch_file",
            source.id,
            {"batch_id": batch.id, "original_name": source.original_name},
        )
        session.commit()
        _unlink_after_commit(storage_path)
        return batch_json(batch, session)

    def reorder(
        self,
        session: Session,
        batch_id: int,
        payload: FileOrderPayload,
        user_id: int,
    ) -> dict[str, object]:
        batch = self.dependencies.get_editable_batch(
            batch_id, session, for_update=True, detail="当前批次状态不可调整顺序"
        )
        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id == batch.id)
        ).all()
        by_id = {source.id: source for source in sources}
        if len(payload.file_ids) != len(set(payload.file_ids)) or set(
            payload.file_ids
        ) != set(by_id):
            raise HTTPException(status_code=400, detail="文件顺序必须完整且不可重复")
        for source in sources:
            source.file_order = -source.id
        session.flush()
        for file_order, source_id in enumerate(payload.file_ids, start=1):
            by_id[source_id].file_order = file_order
        batch.status = "draft"
        self.audit(
            session,
            user_id,
            "reorder_batch_files",
            "batch",
            batch.id,
            {"file_ids": payload.file_ids},
        )
        session.commit()
        return batch_json(batch, session)
