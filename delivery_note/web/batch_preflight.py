"""批次预检与验证前后输入快照核对。"""

from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import resolve_supplier
from ..excel_io import (
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
    read_supplier_workbook,
    validate_self_operated_template_workbook,
    validate_template_workbook,
)
from .batch_queries import VERSION_FIELDS
from .batch_views import batch_json
from .dependencies import BatchLookup
from .input_versions import INPUT_KINDS
from .models import Batch, BatchFile, InputVersion, SelfOperatedBatch


def _batch_input_signature(
    batch: Batch,
    sources: Sequence[BatchFile],
    self_operated: SelfOperatedBatch | None,
) -> tuple:
    return (
        tuple(getattr(batch, VERSION_FIELDS[kind]) for kind in INPUT_KINDS),
        tuple(
            (source.id, source.storage_path, source.original_name, source.file_order)
            for source in sources
        ),
        (
            self_operated.template_version_id,
            self_operated.rule_version_id,
            self_operated.inbound_storage_path,
        )
        if self_operated is not None
        else None,
    )


def _validate_workbooks(
    session: Session,
    versions: dict[str, Path],
    sources: Sequence[BatchFile],
    self_operated: SelfOperatedBatch | None,
) -> None:
    supplier_rows = read_supplier_workbook(versions["supplier"])
    read_product_workbook(versions["product"])
    if self_operated is not None:
        inbound_path = Path(self_operated.inbound_storage_path)
        if not self_operated.inbound_storage_path or not inbound_path.is_file():
            raise ValueError("尚未上传自营仓收货入库单")
        template = session.get(
            InputVersion,
            self_operated.template_version_id,
        )
        if template is None or not Path(template.storage_path).is_file():
            raise ValueError("批次锁定的积加入库模板不存在")
        read_self_operated_inbound_workbook(inbound_path)
        validate_self_operated_template_workbook(Path(template.storage_path))
        for source in sources:
            try:
                read_self_operated_delivery_workbook(Path(source.storage_path))
                resolve_supplier(Path(source.original_name), supplier_rows)
            except Exception as error:
                raise ValueError(f"{source.original_name}：{error}") from error
    else:
        read_purchase_workbook(versions["purchase"])
        read_position_workbook(versions["position"])
        validate_template_workbook(versions["template"])
        for source in sources:
            read_delivery_workbook(Path(source.storage_path))
            resolve_supplier(Path(source.original_name), supplier_rows)


def preflight_batch_record(
    session: Session,
    batch_id: int,
    user_id: int,
    get_batch_or_404: BatchLookup,
    audit: Callable,
) -> dict:
    batch = get_batch_or_404(batch_id, session)
    if batch.status not in {"draft", "failed"}:
        raise HTTPException(status_code=409, detail="当前批次状态不可预检")
    sources = session.scalars(
        select(BatchFile)
        .where(BatchFile.batch_id == batch.id)
        .order_by(BatchFile.file_order)
    ).all()
    if not sources:
        raise HTTPException(status_code=400, detail="批次至少需要一个交货文件")
    self_operated = session.get(SelfOperatedBatch, batch.id)
    input_signature = _batch_input_signature(batch, sources, self_operated)
    versions = {}
    version_kinds = (
        ("product", "supplier") if self_operated is not None else INPUT_KINDS
    )
    for kind in version_kinds:
        version_id = getattr(batch, VERSION_FIELDS[kind])
        if version_id is None:
            raise HTTPException(
                status_code=400,
                detail="批次锁定的输入文件不完整",
            )
        version = session.get(InputVersion, version_id)
        if version is None or not Path(version.storage_path).is_file():
            raise HTTPException(status_code=400, detail="批次锁定的输入文件不完整")
        versions[kind] = Path(version.storage_path)
    if any(not Path(source.storage_path).is_file() for source in sources):
        raise HTTPException(status_code=400, detail="批次锁定的输入文件不完整")

    validation_error = None
    try:
        _validate_workbooks(session, versions, sources, self_operated)
    except Exception as error:
        validation_error = error
    batch = get_batch_or_404(batch_id, session, for_update=True)
    current_sources = session.scalars(
        select(BatchFile)
        .where(BatchFile.batch_id == batch_id)
        .order_by(BatchFile.file_order)
        .execution_options(populate_existing=True)
    ).all()
    current_self_operated = session.scalar(
        select(SelfOperatedBatch)
        .where(SelfOperatedBatch.batch_id == batch_id)
        .execution_options(populate_existing=True)
    )
    if (
        batch.status not in {"draft", "failed"}
        or _batch_input_signature(batch, current_sources, current_self_operated)
        != input_signature
    ):
        raise HTTPException(
            status_code=409,
            detail="预检期间批次输入已变更，请重新执行预检",
        )
    if validation_error is not None:
        raise HTTPException(
            status_code=400,
            detail=f"预检失败：{validation_error}",
        ) from validation_error
    batch.status = "preflight_ready"
    batch.error_message = None
    audit(session, user_id, "preflight_batch", "batch", batch.id)
    session.commit()
    return batch_json(batch, session)
