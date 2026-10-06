from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


INPUT_KINDS = ("purchase", "product", "supplier", "position", "template")
SELF_OPERATED_INPUT_KINDS = ("product", "supplier", "inbound_template")
UPLOAD_INPUT_KINDS = (*INPUT_KINDS, "inbound_template")
POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL = (
    "库位资料已有正式版本，请使用“开始网页维护”通过草稿流程发布新版本"
)


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


def ensure_position_bootstrap_upload_allowed(session: Session) -> None:
    position_version_id = session.scalar(
        select(InputVersion.id).where(InputVersion.kind == "position")
    )
    if position_version_id is not None:
        raise HTTPException(
            status_code=409,
            detail=POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL,
        )


def validate_new_input_version(session: Session, kind: str, name: str) -> None:
    if session.scalar(
        select(InputVersion).where(
            InputVersion.kind == kind,
            InputVersion.name == name,
        )
    ):
        raise HTTPException(status_code=409, detail="版本名称已存在")
    if kind == "position":
        ensure_position_bootstrap_upload_allowed(session)


def register_uploaded_input_version(
    session: Session, version: InputVersion, _audit: Callable[..., None]
) -> None:
    try:
        if version.active:
            current_versions = list(
                session.scalars(
                    select(InputVersion)
                    .where(InputVersion.kind == version.kind)
                    .order_by(InputVersion.id)
                    .with_for_update()
                )
            )
            if version.kind == "position" and current_versions:
                raise HTTPException(
                    status_code=409, detail=POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL
                )
            for current in current_versions:
                current.active = False
            session.flush()
        session.add(version)
        session.flush()
        _audit(
            session,
            version.created_by,
            "upload_input_version",
            "input_version",
            version.id,
            {"kind": version.kind},
        )
        session.commit()
    except HTTPException:
        session.rollback()
        Path(version.storage_path).unlink(missing_ok=True)
        raise
    except IntegrityError as error:
        session.rollback()
        Path(version.storage_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=409, detail="输入版本发生并发冲突，请刷新后重试"
        ) from error


def activate_input_version_record(
    session: Session, version_id: int, admin_id: int, _audit: Callable[..., None]
) -> InputVersion:
    version = session.get(InputVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="输入版本不存在")
    try:
        current_versions = list(
            session.scalars(
                select(InputVersion)
                .where(InputVersion.kind == version.kind)
                .order_by(InputVersion.id)
                .with_for_update()
            )
        )
        if not Path(version.storage_path).is_file():
            raise HTTPException(status_code=409, detail="输入版本文件不存在")
        if version.kind == "position" and any(
            current.active and current.id != version.id for current in current_versions
        ):
            raise HTTPException(
                status_code=409,
                detail=POSITION_DRAFT_WORKFLOW_REQUIRED_DETAIL,
            )
        for current in current_versions:
            current.active = False
        session.flush()
        version.active = True
        _audit(
            session,
            admin_id,
            "activate_input_version",
            "input_version",
            version.id,
        )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="输入版本发生并发冲突，请刷新后重试",
        ) from error
    return version


def require_active_versions(
    session: Session, kinds: Sequence[str]
) -> dict[str, InputVersion]:
    active_versions = {
        version.kind: version
        for version in session.scalars(
            select(InputVersion).where(InputVersion.active.is_(True))
        )
    }
    missing = [kind for kind in kinds if kind not in active_versions]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"缺少启用的输入版本：{', '.join(missing)}",
        )
    return active_versions
