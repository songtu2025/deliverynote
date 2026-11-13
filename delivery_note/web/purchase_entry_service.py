"""采购单的资料版本选择及无持久化转换。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import FastAPI, HTTPException, UploadFile
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..purchase_entry import convert_purchase, export_purchase, validate_template
from ..purchase_entry.models import PurchaseConversion
from .models import InputVersion
from .uploads import UploadParser, _safe_filename, _save_upload

PURCHASE_INPUT_LABELS = {
    "supplier": "供应商资料",
    "product": "商品信息",
    "sku_warehouse": "SKU仓库资料",
    "purchase_template": "采购导出模板",
}


def purchase_versions(
    session: Session, version_ids: str | None = None
) -> dict[str, InputVersion]:
    """预览读取启用资料，导出严格读取调用方锁定的资料编号。"""
    if version_ids is None:
        versions = {
            version.kind: version
            for version in session.scalars(
                select(InputVersion).where(
                    InputVersion.active.is_(True),
                    InputVersion.kind.in_(PURCHASE_INPUT_LABELS),
                )
            )
        }
        missing = [
            label
            for kind, label in PURCHASE_INPUT_LABELS.items()
            if kind not in versions
        ]
        if missing:
            raise HTTPException(400, f"请先启用以下资料：{'、'.join(missing)}")
        return versions
    try:
        ids = json.loads(version_ids)
    except json.JSONDecodeError as error:
        raise HTTPException(400, "资料版本编号格式不正确，请重新预览") from error
    if (
        not isinstance(ids, dict)
        or set(ids) != set(PURCHASE_INPUT_LABELS)
        or any(type(value) is not int or value <= 0 for value in ids.values())
    ):
        raise HTTPException(400, "请提供预览时的完整资料版本编号")
    versions = {}
    for kind, label in PURCHASE_INPUT_LABELS.items():
        version = session.get(InputVersion, ids[kind])
        if version is None or version.kind != kind:
            raise HTTPException(400, f"{label}版本无效，请重新预览")
        versions[kind] = version
    return versions


def _convert(
    path: Path, filename: str, paths: dict[str, Path], mode: str | None
) -> tuple[PurchaseConversion, bytes | None]:
    """先验证模板，再完成整份文件的计算和导出。"""
    validate_template(paths["purchase_template"])
    result = convert_purchase(
        path,
        filename,
        paths["supplier"],
        paths["product"],
        paths["sku_warehouse"],
    )
    output = (
        None
        if mode is None
        else export_purchase(result, paths["purchase_template"], mode)
    )
    return result, output


class PurchaseEntryService:
    """复用上传限制与解析并发，只保留请求期间的临时来源文件。"""

    def __init__(self, app: FastAPI, storage: Path, parser: UploadParser) -> None:
        self.app = app
        self.temporary_root = storage / "purchase-entry"
        self.parser = parser

    async def process(
        self,
        file: UploadFile,
        versions: dict[str, InputVersion],
        mode: str | None = None,
    ) -> tuple[PurchaseConversion, bytes | None]:
        filename = _safe_filename(file.filename or "")
        if Path(filename).suffix.lower() != ".xlsx":
            raise HTTPException(400, "采购单仅支持 .xlsx 文件")
        paths = {kind: Path(version.storage_path) for kind, version in versions.items()}
        await run_in_threadpool(self.temporary_root.mkdir, parents=True, exist_ok=True)
        temporary = await run_in_threadpool(TemporaryDirectory, dir=self.temporary_root)
        try:
            path = Path(temporary.name) / "source.xlsx"
            await _save_upload(file, path, self.app.state.max_upload_bytes)
            return await self.parser(_convert, path, filename, paths, mode)
        except ValueError as error:
            message = str(error)
            for private_path in [Path(temporary.name), *paths.values()]:
                message = message.replace(str(private_path), "资料文件")
            raise HTTPException(400, f"采购单转换失败：{message}") from error
        except (BadZipFile, InvalidFileException, ParseError, EOFError) as error:
            raise HTTPException(
                400, "工作簿无法读取，请确认文件完整且为有效的 .xlsx 文件"
            ) from error
        except OSError as error:
            raise HTTPException(
                400, "采购单或资料文件无法读取，请重新上传或联系管理员"
            ) from error
        finally:
            await run_in_threadpool(temporary.cleanup)
