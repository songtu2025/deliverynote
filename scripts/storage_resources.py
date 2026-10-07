"""只识别明确的运行文件和已登记内置模板，不输出业务内容与凭据。"""

import json
import os
from pathlib import Path
import stat
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from delivery_note.excel_io import (
    validate_self_operated_template_workbook,
    validate_template_workbook,
)
from delivery_note.gerpgo import (
    GerpgoSettings,
    gerpgo_config_path,
    load_gerpgo_settings,
)
from delivery_note.purchase_detail_cache import (
    CACHE_SCHEMA_VERSION,
    load_purchase_detail_cache_state,
    purchase_cache_source_identity,
    purchase_detail_cache_path,
)
from delivery_note.web.input_versions import BUILTIN_TEMPLATES
from delivery_note.web.models import InputVersion
from scripts.backup.archive import sha256
from scripts.storage_paths import path_state


class ResourceDetails(TypedDict, total=False):
    purpose: str
    validation: str
    recovery_source: str
    reason: str
    sha256: str
    valid_entries: int


def runtime_paths(root: Path) -> dict[Path, str]:
    return {
        gerpgo_config_path(root): "积加接口配置",
        purchase_detail_cache_path(root): "采购详情缓存",
    }


def builtin_reference_paths(session: Session) -> frozenset[Path]:
    """内置资源必须同时匹配程序定义及数据库登记的类型与路径。"""
    known = {(template.kind, str(template.path)) for template in BUILTIN_TEMPLATES}
    return frozenset(
        Path(path)
        for kind, path in session.execute(
            select(InputVersion.kind, InputVersion.storage_path)
        )
        if (kind, path) in known
    )


def _settings(root: Path) -> GerpgoSettings:
    config = gerpgo_config_path(root)
    if os.path.lexists(config):
        mode, _ = path_state(config, root)
        if mode is None or not stat.S_ISREG(mode):
            raise ValueError("配置文件不可核验")
    return load_gerpgo_settings(root)


def _validate_cache(path: Path, root: Path) -> int:
    settings = _settings(root)
    identity = purchase_cache_source_identity(settings.base_url, settings.app_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != CACHE_SCHEMA_VERSION
        or payload.get("source_identity") != identity
        or not isinstance(payload.get("orders"), dict)
    ):
        raise ValueError("缓存格式或来源不匹配")
    state = load_purchase_detail_cache_state(path, identity)
    if (
        len(state.orders) != len(payload["orders"])
        or state.last_full_verified_at is None
    ):
        raise ValueError("缓存存在无效记录或校验时间")
    return len(state.orders)


def inspect_resource(
    path: Path, root: Path, builtin_paths: frozenset[Path]
) -> tuple[str, str, ResourceDetails] | None:
    """未识别路径交回普通审计；校验失败仍保留未知或引用缺失状态。"""
    builtin = (
        next(
            (template for template in BUILTIN_TEMPLATES if template.path == path), None
        )
        if path in builtin_paths
        else None
    )
    purposes = runtime_paths(root)
    if path not in purposes and builtin is None:
        return None
    details: ResourceDetails = {
        "purpose": builtin.name if builtin else purposes[path],
        "recovery_source": "application_image" if builtin else "data_volume",
        "validation": "failed",
    }
    # 内置资源位于存储卷外，但仍逐层拒绝链接，不放宽其他外部引用。
    mode, kind = path_state(path, Path(path.anchor) if builtin else root)
    if mode is None or not stat.S_ISREG(mode):
        details["reason"] = "资源不存在、不可读取或不是普通文件"
        return (
            "missing_reference" if builtin and kind == "missing" else "unknown",
            kind,
            details,
        )
    try:
        if builtin:
            validator = (
                validate_template_workbook
                if builtin.kind == "template"
                else validate_self_operated_template_workbook
            )
            validator(path)
            details["sha256"] = sha256(path)
        elif path == gerpgo_config_path(root):
            _settings(root)
        else:
            details["valid_entries"] = _validate_cache(path, root)
    except Exception:
        # 异常原文可能含凭据、业务数据或文件内容，统一使用固定原因。
        details["reason"] = "资源校验失败，请复核配置、缓存来源或模板格式"
        return "unknown", kind, details
    details["validation"] = "passed"
    return "builtin_resource" if builtin else "managed_runtime", kind, details
