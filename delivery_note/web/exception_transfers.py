from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import case, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from ..excel_io import read_supplier_workbook
from .batch_creation import DeliveryBatchCreator, validated_batch_name
from .dependencies import RequestDependencies
from .exception_transfer_files import TransferFile, transfer_sites
from .exception_transfer_state import remaining_quantity_expression
from .input_versions import INPUT_KINDS, require_active_versions
from .models import Batch, BatchFile, ExceptionRecord, Job, SelfOperatedBatch
from .models.batches import ExceptionTransfer
from .job_queue import queue_followup_job


@dataclass(frozen=True)
class TransferItem:
    exception_id: int
    quantity: int
    full_site: str


@dataclass
class ExceptionTransferService:
    dependencies: RequestDependencies
    creator: DeliveryBatchCreator

    def _source_batch(self, session: Session, batch_id: int) -> Batch:
        batch = self.dependencies.get_batch_or_404(batch_id, session, for_update=True)
        if session.get(SelfOperatedBatch, batch.id) is None:
            raise HTTPException(status_code=400, detail="仅自营仓批次可以转交货")
        if batch.status != "succeeded":
            raise HTTPException(status_code=409, detail="批次尚未计算成功")
        active_export = session.scalar(
            select(Job.id).where(
                Job.batch_id == batch.id,
                Job.kind == "export",
                Job.status.in_(("queued", "running")),
            )
        )
        if active_export:
            raise HTTPException(status_code=409, detail="导出任务运行期间不可转交货")
        return batch

    def _reserve(
        self, session: Session, batch: Batch, items: list[TransferItem]
    ) -> tuple[dict[int, ExceptionRecord], dict[int, TransferFile]]:
        ids = [item.exception_id for item in items]
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=400, detail="待处理记录不可重复选择")
        records = session.scalars(
            select(ExceptionRecord)
            .join(BatchFile)
            .where(
                ExceptionRecord.id.in_(ids),
                BatchFile.batch_id == batch.id,
            )
            .order_by(ExceptionRecord.id)
            .with_for_update(of=ExceptionRecord)
        ).all()
        by_id = {record.id: record for record in records}
        if set(by_id) != set(ids):
            raise HTTPException(status_code=400, detail="所选待处理记录不属于该批次")
        groups: dict[int, TransferFile] = {}
        sites_by_sku: dict[str, list[str]] = {}
        for item in items:
            record = by_id[item.exception_id]
            if record.sku not in sites_by_sku:
                sites_by_sku[record.sku] = transfer_sites(session, batch, record.sku)
            if item.full_site not in sites_by_sku[record.sku]:
                raise HTTPException(
                    status_code=400,
                    detail=f"{record.sku} 所选站点不在批次锁定商品资料中",
                )
            source = session.get(BatchFile, record.batch_file_id)
            if source is None or not source.supplier_code:
                raise HTTPException(status_code=400, detail="来源文件缺少供应商编码")
            group = groups.setdefault(
                source.id, TransferFile(source.supplier_code, source.original_name)
            )
            group.add(record.sku, item.full_site, item.quantity)
            self._reserve_quantity(session, item)
        return by_id, groups

    def _reserve_quantity(self, session: Session, item: TransferItem) -> None:
        remaining = remaining_quantity_expression()
        changed = cast(
            CursorResult[Any],
            session.execute(
                update(ExceptionRecord)
                .where(
                    ExceptionRecord.id == item.exception_id,
                    ExceptionRecord.status == "pending",
                    remaining >= item.quantity,
                )
                .values(
                    status=case(
                        (remaining == item.quantity, "resolved"), else_="pending"
                    )
                )
                .execution_options(synchronize_session=False)
            ),
        )
        if changed.rowcount != 1:
            raise HTTPException(
                status_code=400,
                detail="记录已处理或转交数量超过剩余可转量，请刷新后重试",
            )

    def transfer(
        self,
        session: Session,
        batch_id: int,
        user_id: int,
        *,
        name: str | None,
        items: list[TransferItem],
    ) -> int:
        created_paths: list[Path] = []
        try:
            batch = self._source_batch(session, batch_id)
            time_label = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M:%S")
            batch_name = validated_batch_name(
                name if name is not None else f"自营仓 #{batch.id} 转交货 {time_label}"
            )
            records, groups = self._reserve(session, batch, items)
            if len(groups) > self.creator.app.state.max_batch_upload_files:
                raise HTTPException(
                    status_code=413, detail="来源文件数量超过单批次文件上限"
                )
            versions = require_active_versions(session, INPUT_KINDS)
            suppliers = read_supplier_workbook(Path(versions["supplier"].storage_path))
            temporary_root = self.creator.storage / "temporary" / "exception-transfers"
            temporary_root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=temporary_root) as directory:
                files = []
                for source_id, group in groups.items():
                    file_directory = Path(directory) / str(source_id)
                    file_directory.mkdir()
                    files.append(group.write(file_directory, suppliers))
                target = self.creator.stage_files(
                    session,
                    batch_name,
                    user_id,
                    versions=versions,
                    files=files,
                    created_paths=created_paths,
                )
            target_files = list(
                session.scalars(
                    select(BatchFile)
                    .where(BatchFile.batch_id == target.id)
                    .order_by(BatchFile.file_order)
                )
            )
            file_by_source = dict(zip(groups, target_files))
            for source_id, target_file in file_by_source.items():
                target_file.supplier_code = groups[source_id].supplier_code
                target_file.receipt_sites = groups[source_id].sites
            self._save_transfers(session, records, items, target, file_by_source)
            queue_followup_job(session, batch, "export", refresh=True)
            session.commit()
            return target.id
        except Exception as error:
            session.rollback()
            for path in created_paths:
                path.unlink(missing_ok=True)
            if isinstance(error, ValueError):
                raise HTTPException(
                    status_code=400, detail=f"转交货文件校验失败：{error}"
                ) from error
            raise

    def _save_transfers(
        self,
        session: Session,
        records: dict[int, ExceptionRecord],
        items: list[TransferItem],
        target: Batch,
        files: dict[int, BatchFile],
    ) -> None:
        for item in items:
            record = records[item.exception_id]
            session.add(
                ExceptionTransfer(
                    exception_id=record.id,
                    quantity=item.quantity,
                    full_site=item.full_site,
                    target_batch_id=target.id,
                    target_file_id=files[record.batch_file_id].id,
                    created_by=target.created_by,
                )
            )
        self.creator.audit(
            session,
            target.created_by,
            "transfer_exceptions_to_delivery",
            "batch",
            target.id,
            {
                "items": [
                    {
                        "exception_id": item.exception_id,
                        "quantity": item.quantity,
                        "full_site": item.full_site,
                        "target_batch_id": target.id,
                    }
                    for item in items
                ]
            },
        )
