"""批次追加交货文件和替换自营收货入库文件。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..excel_io import read_self_operated_inbound_workbook
from .batch_views import batch_json, file_json
from .dependencies import RequestDependencies
from .models import BatchFile, SelfOperatedBatch
from .uploads import UploadParser, _safe_filename, _save_upload, _unlink_after_commit


@dataclass
class BatchFileUploader:
    """在文件落盘后再次持锁核对批次状态、文件名和数量上限。"""

    app: FastAPI
    dependencies: RequestDependencies
    storage: Path
    audit: Callable[..., None]
    parse_workbook: UploadParser
    append_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def replace_inbound(
        self,
        session: Session,
        batch_id: int,
        file: UploadFile,
        user_id: int,
    ) -> dict[str, object]:
        batch = self.dependencies.get_batch_or_404(batch_id, session)
        profile = session.get(SelfOperatedBatch, batch.id)
        if profile is None:
            raise HTTPException(status_code=404, detail="自营仓入库批次不存在")
        if batch.status not in {"draft", "preflight_ready", "failed"}:
            raise HTTPException(status_code=409, detail="当前批次状态不可修改文件")
        original_name = _safe_filename(file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        destination = (
            self.storage
            / "batches"
            / str(batch.id)
            / "inputs"
            / f"{uuid4().hex}_{original_name}"
        )
        await _save_upload(file, destination, self.app.state.max_upload_bytes)
        try:
            await self.parse_workbook(
                read_self_operated_inbound_workbook,
                destination,
            )
        except Exception as error:
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"自营仓收货入库单校验失败：{error}",
            ) from error

        try:
            batch = self.dependencies.get_editable_batch(
                batch_id, session, for_update=True
            )
            profile = session.scalar(
                select(SelfOperatedBatch)
                .where(SelfOperatedBatch.batch_id == batch_id)
                .execution_options(populate_existing=True)
            )
            if profile is None:
                raise HTTPException(status_code=404, detail="自营仓入库批次不存在")
            old_path = (
                Path(profile.inbound_storage_path)
                if profile.inbound_storage_path
                else None
            )
            profile.inbound_original_name = original_name
            profile.inbound_storage_path = str(destination)
            batch.status = "draft"
            batch.error_message = None
            batch.zip_path = None
            self.audit(
                session,
                user_id,
                "upload_self_operated_inbound_file",
                "batch",
                batch.id,
                {"original_name": original_name},
            )
            session.commit()
        except Exception:
            session.rollback()
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise
        if (
            old_path is not None
            and old_path != destination
            and old_path.parent.resolve() == destination.parent.resolve()
        ):
            await run_in_threadpool(_unlink_after_commit, old_path)
        return batch_json(batch, session)

    async def append(
        self,
        session: Session,
        batch_id: int,
        file: UploadFile,
        user_id: int,
    ) -> dict[str, object]:
        batch = self.dependencies.get_editable_batch(batch_id, session)
        source_count = session.scalar(
            select(func.count())
            .select_from(BatchFile)
            .where(BatchFile.batch_id == batch.id)
        )
        if source_count >= self.app.state.max_batch_upload_files:
            await file.close()
            max_files = self.app.state.max_batch_upload_files
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"单批次最多上传 {max_files} 份交货文件",
            )
        original_name = _safe_filename(file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        duplicate = session.scalar(
            select(BatchFile).where(
                BatchFile.batch_id == batch.id,
                BatchFile.original_name == original_name,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="同一批次不可上传同名文件")
        destination = (
            self.storage
            / "batches"
            / str(batch.id)
            / "inputs"
            / f"{uuid4().hex}_{original_name}"
        )
        await _save_upload(file, destination, self.app.state.max_upload_bytes)
        try:
            async with self.append_lock:
                batch = self.dependencies.get_editable_batch(
                    batch_id, session, for_update=True
                )
                source_count = session.scalar(
                    select(func.count())
                    .select_from(BatchFile)
                    .where(BatchFile.batch_id == batch.id)
                )
                if source_count >= self.app.state.max_batch_upload_files:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            "单批次最多上传 "
                            f"{self.app.state.max_batch_upload_files} 份交货文件"
                        ),
                    )
                duplicate = session.scalar(
                    select(BatchFile).where(
                        BatchFile.batch_id == batch.id,
                        BatchFile.original_name == original_name,
                    )
                )
                if duplicate is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="同一批次不可上传同名文件",
                    )
                current_max = (
                    session.scalar(
                        select(func.max(BatchFile.file_order)).where(
                            BatchFile.batch_id == batch.id
                        )
                    )
                    or 0
                )
                source = BatchFile(
                    batch_id=batch.id,
                    original_name=original_name,
                    storage_path=str(destination),
                    file_order=current_max + 1,
                )
                session.add(source)
                batch.status = "draft"
                batch.error_message = None
                session.flush()
                self.audit(
                    session,
                    user_id,
                    "upload_batch_file",
                    "batch_file",
                    source.id,
                    {"batch_id": batch.id},
                )
                session.commit()
        except HTTPException:
            session.rollback()
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise
        except IntegrityError as error:
            session.rollback()
            await run_in_threadpool(destination.unlink, missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="文件上传发生并发冲突，请刷新后重试",
            ) from error
        return file_json(source)
