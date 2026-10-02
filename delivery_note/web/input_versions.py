from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from ..config import validate_supplier_frame
from ..excel_io import (
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_supplier_workbook,
    validate_self_operated_template_workbook,
    validate_template_workbook,
)
from .database import Database
from .models import InputVersion, User


@dataclass(frozen=True)
class BuiltinTemplate:
    """系统内置模板的类型、名称及实际文件。"""

    kind: str
    name: str
    original_name: str
    path: Path


ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
BUILTIN_TEMPLATES = (
    BuiltinTemplate(
        "template",
        "系统内置交货导出模板",
        "交货导入模板.xlsx",
        ASSET_ROOT / "default_import_template.xlsx",
    ),
    BuiltinTemplate(
        "inbound_template",
        "系统内置积加入库模板",
        "积加批量入库模板.xlsx",
        ASSET_ROOT / "default_inbound_template.xlsx",
    ),
)


def _validate_input_version(kind: str, path: Path) -> None:
    if kind == "purchase":
        read_purchase_workbook(path)
    elif kind == "product":
        read_product_workbook(path)
    elif kind == "supplier":
        supplier_rows = read_supplier_workbook(path)
        issues = validate_supplier_frame(supplier_rows)
        if issues:
            details = "；".join(
                f"Excel 行 {', '.join(map(str, issue['row_numbers']))}："
                f"{issue['message']}"
                for issue in issues
            )
            raise ValueError(details)
    elif kind == "position":
        read_position_workbook(path)
    elif kind == "template":
        validate_template_workbook(path)
    elif kind == "inbound_template":
        validate_self_operated_template_workbook(path)
    else:
        raise ValueError(f"不支持的输入资料类型：{kind}")


def bootstrap_builtin_templates(database: Database) -> None:
    """首次启动时依次注册交货和待入库模板。"""
    for template in BUILTIN_TEMPLATES:
        with database.session() as session:
            existing_id = session.scalar(
                select(InputVersion.id).where(InputVersion.kind == template.kind)
            )
            if existing_id is not None:
                continue
            creator_id = session.scalar(
                select(User.id).where(User.role == "admin").order_by(User.id)
            )
            if creator_id is None:
                continue
            _validate_input_version(template.kind, template.path)
            session.add(
                InputVersion(
                    kind=template.kind,
                    name=template.name,
                    original_name=template.original_name,
                    storage_path=str(template.path),
                    active=True,
                    created_by=creator_id,
                )
            )
            session.commit()
