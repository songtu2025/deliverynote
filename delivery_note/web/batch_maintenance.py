"""批次删除、空草稿清理和供应商版本更新。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import shutil

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .batch_views import batch_json
from .models import (
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputVersion,
    Job,
    SelfOperatedBatch,
    SelfOperatedSiteResolution,
    SplitRecord,
)


@dataclass
class BatchMaintenance:
    """在事务提交后清理批次文件，并复用既有审计写入。"""

    storage: Path
    audit: Callable

    def delete_selected(
        self,
        session: Session,
        user_id: int,
        requested_ids: list[int],
    ) -> dict:
        batch_ids = list(dict.fromkeys(requested_ids))
        batches = session.scalars(
            select(Batch)
            .where(Batch.id.in_(batch_ids))
            .order_by(Batch.id)
            .with_for_update()
        ).all()
        found_ids = {batch.id for batch in batches}
        missing_ids = [batch_id for batch_id in batch_ids if batch_id not in found_ids]
        if missing_ids:
            missing_text = "、".join(str(batch_id) for batch_id in missing_ids)
            raise HTTPException(
                status_code=404,
                detail=f"批次不存在：{missing_text}",
            )

        active_job_batch_ids = set(
            session.scalars(
                select(Job.batch_id).where(
                    Job.batch_id.in_(batch_ids),
                    Job.status.in_({"queued", "running"}),
                )
            ).all()
        )
        active_batches = [
            batch
            for batch in batches
            if batch.status in {"queued", "running"} or batch.id in active_job_batch_ids
        ]
        if active_batches:
            active_text = "、".join(
                f"{batch.id}（{batch.name}）" for batch in active_batches
            )
            raise HTTPException(
                status_code=409,
                detail=f"以下批次存在排队或运行中的任务，不能删除：{active_text}",
            )

        sources = session.scalars(
            select(BatchFile).where(BatchFile.batch_id.in_(batch_ids))
        ).all()
        source_ids = [source.id for source in sources]
        exception_ids = (
            session.scalars(
                select(ExceptionRecord.id).where(
                    ExceptionRecord.batch_file_id.in_(source_ids)
                )
            ).all()
            if source_ids
            else []
        )
        if exception_ids:
            session.execute(
                delete(SplitRecord).where(SplitRecord.exception_id.in_(exception_ids))
            )
            session.execute(
                delete(ExceptionRecord).where(ExceptionRecord.id.in_(exception_ids))
            )
        session.execute(
            delete(SelfOperatedSiteResolution).where(
                SelfOperatedSiteResolution.batch_id.in_(batch_ids)
            )
        )
        session.execute(delete(BatchFile).where(BatchFile.batch_id.in_(batch_ids)))
        session.execute(
            delete(BatchOverreceiptRule).where(
                BatchOverreceiptRule.batch_id.in_(batch_ids)
            )
        )
        session.execute(delete(Job).where(Job.batch_id.in_(batch_ids)))
        session.execute(
            delete(SelfOperatedBatch).where(SelfOperatedBatch.batch_id.in_(batch_ids))
        )
        session.execute(delete(Batch).where(Batch.id.in_(batch_ids)))
        self.audit(
            session,
            user_id,
            "delete_batches",
            "batch",
            "bulk",
            {
                "batch_ids": batch_ids,
                "batch_names": [batch.name for batch in batches],
            },
        )
        session.commit()

        file_cleanup_failed_ids = []
        for batch_id in batch_ids:
            batch_root = self.storage / "batches" / str(batch_id)
            try:
                if batch_root.exists():
                    shutil.rmtree(batch_root)
            except OSError:
                file_cleanup_failed_ids.append(batch_id)
        return {
            "deleted_count": len(batch_ids),
            "deleted_ids": batch_ids,
            "file_cleanup_failed_ids": file_cleanup_failed_ids,
        }

    def delete_empty(
        self,
        session: Session,
        user_id: int,
        self_operated: bool,
    ) -> dict:
        query = select(Batch)
        if self_operated:
            query = query.join(
                SelfOperatedBatch, SelfOperatedBatch.batch_id == Batch.id
            ).where(SelfOperatedBatch.inbound_storage_path == "")
        else:
            query = query.outerjoin(
                SelfOperatedBatch, SelfOperatedBatch.batch_id == Batch.id
            ).where(SelfOperatedBatch.batch_id.is_(None))
        empty_batches = session.scalars(
            query.where(
                Batch.status == "draft",
                ~select(BatchFile.id).where(BatchFile.batch_id == Batch.id).exists(),
            )
        ).all()
        batch_ids = [batch.id for batch in empty_batches]
        if not batch_ids:
            return {"deleted_count": 0, "deleted_ids": []}
        if self_operated:
            session.execute(
                delete(SelfOperatedSiteResolution).where(
                    SelfOperatedSiteResolution.batch_id.in_(batch_ids)
                )
            )
        else:
            session.execute(
                delete(BatchOverreceiptRule).where(
                    BatchOverreceiptRule.batch_id.in_(batch_ids)
                )
            )
        session.execute(delete(Job).where(Job.batch_id.in_(batch_ids)))
        if self_operated:
            session.execute(
                delete(SelfOperatedBatch).where(
                    SelfOperatedBatch.batch_id.in_(batch_ids)
                )
            )
        session.execute(delete(Batch).where(Batch.id.in_(batch_ids)))
        self.audit(
            session,
            user_id,
            "delete_empty_self_operated_batches"
            if self_operated
            else "delete_empty_delivery_batches",
            "batch",
            "self_operated_empty" if self_operated else "delivery_empty",
            {"batch_ids": batch_ids},
        )
        session.commit()
        return {"deleted_count": len(batch_ids), "deleted_ids": batch_ids}

    def refresh_supplier(
        self,
        session: Session,
        batch_id: int,
        user_id: int,
    ) -> dict:
        batch = session.scalar(
            select(Batch).where(Batch.id == batch_id).with_for_update()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        if batch.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="仅草稿状态批次可以更新供应商资料版本",
            )
        active_supplier = session.scalar(
            select(InputVersion).where(
                InputVersion.kind == "supplier",
                InputVersion.active.is_(True),
            )
        )
        if active_supplier is None:
            raise HTTPException(status_code=409, detail="当前没有启用的供应商资料版本")

        previous_version_id = batch.supplier_version_id
        batch.supplier_version_id = active_supplier.id
        self.audit(
            session,
            user_id,
            "refresh_batch_supplier_version",
            "batch",
            batch.id,
            {
                "previous_supplier_version_id": previous_version_id,
                "supplier_version_id": active_supplier.id,
            },
        )
        session.commit()
        return batch_json(batch, session)
