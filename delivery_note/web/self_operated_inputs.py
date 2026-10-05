"""自营批次名称、上传文件和 API 入库来源校验。"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import FastAPI, HTTPException, Request, UploadFile, status
from starlette.concurrency import run_in_threadpool

from ..excel_io import read_self_operated_inbound_workbook
from .batch_creation import validated_batch_name
from .models import InputVersion
from .uploads import UploadParser, _safe_filename, _save_upload


@dataclass
class SelfOperatedFiles:
    delivery_names: list[str]
    inbound_name: str
    inbound_file: UploadFile | None
    api_version: InputVersion | None


async def self_operated_batch_name(request: Request, name: str | None) -> str:
    if name is None:
        try:
            name = str((await request.json()).get("name") or "")
        except ValueError:
            name = ""
    return validated_batch_name(name)


async def _close_uploads(
    files: list[UploadFile], inbound_file: UploadFile | None
) -> None:
    for upload in files:
        await upload.close()
    if inbound_file is not None:
        await inbound_file.close()


async def prepare_self_operated_files(
    delivery_files: list[UploadFile],
    inbound_file: UploadFile | None,
    active_versions: dict[str, InputVersion],
    app: FastAPI,
) -> SelfOperatedFiles:
    if not delivery_files:
        raise HTTPException(status_code=400, detail="缺少质检交货单")
    if len(delivery_files) > app.state.max_batch_upload_files:
        await _close_uploads(delivery_files, inbound_file)
        max_files = app.state.max_batch_upload_files
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(f"单批次最多上传 {max_files} 份质检交货单"),
        )
    api_inbound_version = active_versions.get("self_operated_inbound")
    if inbound_file is None and api_inbound_version is None:
        raise HTTPException(
            status_code=409,
            detail="缺少启用的待入库 API 数据",
        )
    delivery_names = [
        _safe_filename(upload.filename or "") for upload in delivery_files
    ]
    if len(delivery_names) != len(set(delivery_names)):
        await _close_uploads(delivery_files, inbound_file)
        raise HTTPException(status_code=409, detail="同一批次不可上传同名文件")
    inbound_name = (
        _safe_filename(inbound_file.filename or "")
        if inbound_file is not None
        else cast(InputVersion, api_inbound_version).original_name
    )
    if any(
        Path(delivery_name).suffix.lower() not in {".xls", ".xlsx"}
        for delivery_name in delivery_names
    ):
        raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
    if inbound_file is not None and Path(inbound_name).suffix.lower() not in {
        ".xls",
        ".xlsx",
    }:
        raise HTTPException(status_code=400, detail="仅支持 Excel 文件")

    return SelfOperatedFiles(
        delivery_names, inbound_name, inbound_file, api_inbound_version
    )


async def validated_inbound_source(
    files: SelfOperatedFiles,
    temporary_inbound: Path | None,
    parse_workbook: UploadParser,
    app: FastAPI,
) -> Path:
    if files.inbound_file is not None and temporary_inbound is not None:
        await _save_upload(
            files.inbound_file,
            temporary_inbound,
            app.state.max_upload_bytes,
        )
        await parse_workbook(
            read_self_operated_inbound_workbook,
            temporary_inbound,
        )
        inbound_source_path = temporary_inbound
    else:
        inbound_source_path = Path(cast(InputVersion, files.api_version).storage_path)
        if not await run_in_threadpool(inbound_source_path.is_file):
            raise ValueError("启用的待入库 API 数据文件不存在")
        await parse_workbook(
            read_self_operated_inbound_workbook,
            inbound_source_path,
        )

    return inbound_source_path
