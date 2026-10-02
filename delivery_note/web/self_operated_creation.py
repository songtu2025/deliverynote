"""自营批次空草稿与带文件创建事务。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..excel_io import read_self_operated_delivery_workbook
from .batch_views import batch_json
from .input_versions import SELF_OPERATED_INPUT_KINDS, require_active_versions
from .models import (
    Batch,
    BatchFile,
    InputVersion,
    SelfOperatedBatch,
    SelfOperatedOverreceiptRuleVersion,
)
from .schemas import SelfOperatedBatchForm
from .self_operated_inputs import (
    prepare_self_operated_files,
    self_operated_batch_name,
    validated_inbound_source,
)
from .uploads import _save_upload


def _new_self_operated_batch(
    session: Session,
    name: str,
    user_id: int,
    versions: dict[str, InputVersion],
) -> Batch:
    batch = Batch(
        name=name,
        created_by=user_id,
        purchase_version_id=None,
        product_version_id=versions["product"].id,
        supplier_version_id=versions["supplier"].id,
        position_version_id=None,
        template_version_id=None,
    )
    session.add(batch)
    session.flush()
    return batch


def _active_rule(session: Session) -> SelfOperatedOverreceiptRuleVersion | None:
    return session.scalar(
        select(SelfOperatedOverreceiptRuleVersion).where(
            SelfOperatedOverreceiptRuleVersion.active.is_(True)
        )
    )


@dataclass
class SelfOperatedBatchCreator:
    app: FastAPI
    storage: Path
    audit: Callable
    parse_workbook: Callable[..., Awaitable[Any]]

    def create_empty(
        self,
        session: Session,
        name: str,
        user_id: int,
        active_versions: dict[str, InputVersion],
    ) -> dict:
        active_rule = _active_rule(session)
        batch = _new_self_operated_batch(session, name, user_id, active_versions)
        session.add(
            SelfOperatedBatch(
                batch_id=batch.id,
                template_version_id=active_versions["inbound_template"].id,
                rule_version_id=(active_rule.id if active_rule is not None else None),
                inbound_original_name="",
                inbound_storage_path="",
            )
        )
        self.audit(
            session,
            user_id,
            "create_empty_self_operated_batch",
            "batch",
            batch.id,
        )
        session.commit()
        return batch_json(batch, session)

    async def create(
        self,
        session: Session,
        request: Request,
        form: SelfOperatedBatchForm,
        user_id: int,
    ) -> dict:
        batch_name = await self_operated_batch_name(request, form.name)
        active_versions = require_active_versions(session, SELF_OPERATED_INPUT_KINDS)
        delivery_files = form.delivery_file or []
        inbound_file = form.inbound_file
        if not delivery_files and inbound_file is None:
            return self.create_empty(session, batch_name, user_id, active_versions)
        prepared = await prepare_self_operated_files(
            delivery_files, inbound_file, active_versions, self.app
        )
        delivery_names = prepared.delivery_names
        inbound_name = prepared.inbound_name
        api_inbound_version = prepared.api_version
        temporary_root = self.storage / "temporary" / "self-operated-batches"
        token = uuid4().hex
        temporary_deliveries = [
            temporary_root / f"{token}_delivery_{index}_{delivery_name}"
            for index, delivery_name in enumerate(delivery_names, start=1)
        ]
        temporary_inbound = (
            temporary_root / f"{token}_inbound_{inbound_name}"
            if inbound_file is not None
            else None
        )
        created_paths: list[Path] = []
        active_rule = _active_rule(session)
        try:
            for upload, temporary_delivery in zip(
                delivery_files,
                temporary_deliveries,
                strict=True,
            ):
                await _save_upload(
                    upload,
                    temporary_delivery,
                    self.app.state.max_upload_bytes,
                )
                await self.parse_workbook(
                    read_self_operated_delivery_workbook,
                    temporary_delivery,
                )
            inbound_source_path = await validated_inbound_source(
                prepared, temporary_inbound, self.parse_workbook, self.app
            )
            batch = _new_self_operated_batch(
                session, batch_name, user_id, active_versions
            )
            input_root = self.storage / "batches" / str(batch.id) / "inputs"
            await run_in_threadpool(input_root.mkdir, parents=True, exist_ok=True)
            delivery_paths = []
            for temporary_delivery, delivery_name in zip(
                temporary_deliveries,
                delivery_names,
                strict=True,
            ):
                delivery_path = input_root / f"{uuid4().hex}_{delivery_name}"
                await run_in_threadpool(
                    os.replace,
                    temporary_delivery,
                    delivery_path,
                )
                created_paths.append(delivery_path)
                delivery_paths.append(delivery_path)
            if inbound_file is not None:
                inbound_path = input_root / f"{uuid4().hex}_{inbound_name}"
                await run_in_threadpool(os.replace, inbound_source_path, inbound_path)
                created_paths.append(inbound_path)
            else:
                inbound_path = inbound_source_path

            session.add_all(
                [
                    BatchFile(
                        batch_id=batch.id,
                        original_name=delivery_name,
                        storage_path=str(delivery_path),
                        file_order=file_order,
                    )
                    for file_order, (delivery_name, delivery_path) in enumerate(
                        zip(delivery_names, delivery_paths, strict=True),
                        start=1,
                    )
                ]
            )
            session.add(
                SelfOperatedBatch(
                    batch_id=batch.id,
                    template_version_id=active_versions["inbound_template"].id,
                    rule_version_id=(
                        active_rule.id if active_rule is not None else None
                    ),
                    inbound_original_name=inbound_name,
                    inbound_storage_path=str(inbound_path),
                )
            )
            self.audit(
                session,
                user_id,
                "create_self_operated_batch",
                "batch",
                batch.id,
                {
                    "rule_version_id": (
                        active_rule.id if active_rule is not None else None
                    ),
                    "template_version_id": active_versions["inbound_template"].id,
                    "delivery_file": delivery_names[0],
                    "delivery_files": delivery_names,
                    "inbound_file": inbound_name,
                    "inbound_version_id": (
                        cast(InputVersion, api_inbound_version).id
                        if inbound_file is None
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
                    detail=f"自营仓文件校验失败：{error}",
                ) from error
            raise
        finally:
            for temporary_delivery in temporary_deliveries:
                await run_in_threadpool(temporary_delivery.unlink, missing_ok=True)
            if temporary_inbound is not None:
                await run_in_threadpool(temporary_inbound.unlink, missing_ok=True)
        return batch_json(batch, session)
