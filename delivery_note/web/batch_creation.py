"""普通交货批次创建及其文件落盘事务。"""

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..excel_io import read_delivery_workbook
from .batch_queries import VERSION_FIELDS
from .batch_views import batch_json
from .input_versions import INPUT_KINDS, require_active_versions
from .models import (
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    InputVersion,
    OverreceiptRuleVersion,
)
from .schemas import BatchPayload, DeliveryBatchForm
from .uploads import UploadParser, _safe_filename, _save_upload


def validated_batch_name(name: str) -> str:
    batch_name = name.strip()
    if not batch_name:
        raise HTTPException(status_code=400, detail="批次名称不能为空")
    if len(batch_name) > 200:
        raise HTTPException(status_code=400, detail="批次名称不能超过 200 个字符")
    return batch_name


def _delivery_names(files: list[UploadFile]) -> list[str]:
    original_names = [_safe_filename(file.filename or "") for file in files]
    if any(
        Path(original_name).suffix.lower() not in {".xls", ".xlsx"}
        for original_name in original_names
    ):
        raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
    if len(original_names) != len(set(original_names)):
        raise HTTPException(status_code=400, detail="同一批次不可上传同名文件")

    return original_names


def _new_delivery_batch(
    session: Session,
    name: str,
    user_id: int,
    versions: dict[str, InputVersion],
) -> Batch:
    batch = Batch(
        name=name,
        created_by=user_id,
        **{VERSION_FIELDS[kind]: versions[kind].id for kind in INPUT_KINDS},
    )
    session.add(batch)
    session.flush()
    return batch


def _active_overreceipt_rule(session: Session) -> OverreceiptRuleVersion | None:
    return session.scalar(
        select(OverreceiptRuleVersion).where(OverreceiptRuleVersion.active.is_(True))
    )


def _bind_overreceipt_rule(
    session: Session,
    batch_id: int,
    rule: OverreceiptRuleVersion | None,
) -> None:
    if rule is not None:
        session.add(BatchOverreceiptRule(batch_id=batch_id, rule_version_id=rule.id))


@dataclass
class DeliveryBatchCreator:
    app: FastAPI
    storage: Path
    audit: Callable[..., None]
    parse_workbook: UploadParser

    def create(
        self, session: Session, payload: BatchPayload, user_id: int
    ) -> dict[str, object]:
        versions = require_active_versions(session, INPUT_KINDS)
        active_overreceipt_rule = _active_overreceipt_rule(session)
        batch = _new_delivery_batch(session, payload.name, user_id, versions)
        _bind_overreceipt_rule(session, batch.id, active_overreceipt_rule)
        self.audit(
            session,
            user_id,
            "create_batch",
            "batch",
            batch.id,
            {
                "overreceipt_rule_version_id": (
                    active_overreceipt_rule.id
                    if active_overreceipt_rule is not None
                    else None
                )
            },
        )
        session.commit()
        return batch_json(batch, session)

    async def create_with_files(
        self,
        session: Session,
        form: DeliveryBatchForm,
        user_id: int,
    ) -> dict[str, object]:
        name, files = form.name, form.files
        batch_name = validated_batch_name(name)
        if not files:
            raise HTTPException(status_code=400, detail="请至少上传一份交货文件")
        if len(files) > self.app.state.max_batch_upload_files:
            for upload in files:
                await upload.close()
            max_files = self.app.state.max_batch_upload_files
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"单批次最多上传 {max_files} 份交货文件",
            )

        active_versions = require_active_versions(session, INPUT_KINDS)
        original_names = _delivery_names(files)

        temporary_root = self.storage / "temporary" / "delivery-batches"
        token = uuid4().hex
        temporary_paths = [
            temporary_root / f"{token}_{index}_{original_name}"
            for index, original_name in enumerate(original_names, start=1)
        ]
        created_paths: list[Path] = []
        active_overreceipt_rule = _active_overreceipt_rule(session)
        try:
            for file, temporary_path in zip(files, temporary_paths):
                await _save_upload(
                    file,
                    temporary_path,
                    self.app.state.max_upload_bytes,
                )
                await self.parse_workbook(
                    read_delivery_workbook,
                    temporary_path,
                )

            batch = _new_delivery_batch(session, batch_name, user_id, active_versions)
            input_root = self.storage / "batches" / str(batch.id) / "inputs"
            await run_in_threadpool(input_root.mkdir, parents=True, exist_ok=True)
            for file_order, (original_name, temporary_path) in enumerate(
                zip(original_names, temporary_paths),
                start=1,
            ):
                destination = input_root / f"{uuid4().hex}_{original_name}"
                await run_in_threadpool(os.replace, temporary_path, destination)
                created_paths.append(destination)
                session.add(
                    BatchFile(
                        batch_id=batch.id,
                        original_name=original_name,
                        storage_path=str(destination),
                        file_order=file_order,
                    )
                )
            _bind_overreceipt_rule(session, batch.id, active_overreceipt_rule)
            self.audit(
                session,
                user_id,
                "create_batch_with_files",
                "batch",
                batch.id,
                {
                    "file_count": len(original_names),
                    "overreceipt_rule_version_id": (
                        active_overreceipt_rule.id
                        if active_overreceipt_rule is not None
                        else None
                    ),
                },
            )
            session.commit()
        except Exception as error:
            session.rollback()
            for path in created_paths:
                await run_in_threadpool(path.unlink, missing_ok=True)
            if isinstance(error, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"交货文件校验失败：{error}",
                ) from error
            raise
        finally:
            for temporary_path in temporary_paths:
                await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        return batch_json(batch, session)
