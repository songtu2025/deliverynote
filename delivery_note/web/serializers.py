"""用户、基础资料、规则和任务的响应字段。"""

from datetime import datetime, timezone

from ..gerpgo import GerpgoSettings
from .models import (
    InputVersion,
    ExceptionRecord,
    Job,
    OverreceiptRuleVersion,
    SelfOperatedOverreceiptRuleVersion,
    User,
)


def utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _masked_identifier(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def gerpgo_config_json(settings: GerpgoSettings) -> dict[str, object]:
    return {
        "configured": True,
        "base_url": settings.base_url,
        "app_id_hint": _masked_identifier(settings.app_id),
        "has_app_id": True,
        "has_app_key": True,
        "source": settings.source,
    }


def user_json(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "active": user.active,
    }


def version_json(version: InputVersion) -> dict[str, object]:
    return {
        "id": version.id,
        "kind": version.kind,
        "name": version.name,
        "original_name": version.original_name,
        "active": version.active,
        "created_by": version.created_by,
        "created_at": utc_isoformat(version.created_at),
    }


def overreceipt_rule_json(version: OverreceiptRuleVersion) -> dict[str, object]:
    return {
        "id": version.id,
        "name": version.name,
        "short_tail_limit": version.short_tail_limit,
        "medium_tail_limit": version.medium_tail_limit,
        "long_tail_limit": version.long_tail_limit,
        "allowed_warehouses": version.allowed_warehouses,
        "active": version.active,
        "created_by": version.created_by,
        "created_at": utc_isoformat(version.created_at),
    }


def self_operated_overreceipt_rule_json(
    version: SelfOperatedOverreceiptRuleVersion,
) -> dict[str, object]:
    return {
        "id": version.id,
        "name": version.name,
        "allowance": version.allowance,
        "active": version.active,
        "created_by": version.created_by,
        "created_at": utc_isoformat(version.created_at),
    }


def exception_row(exception: ExceptionRecord) -> dict[str, object]:
    """审校与导出共用的待处理记录投影，保留业务列顺序。"""
    return {
        "SKU": exception.sku,
        "原始站点": exception.original_site,
        "完整站点": exception.full_site,
        "目的仓": exception.destination,
        "交货量": exception.delivery_quantity,
        "已自动分配量": exception.allocated_quantity,
        "人工处理量": exception.manual_quantity,
        "异常原因": exception.reason,
    }


def job_json(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "error_message": job.error_message,
        "download_ready": bool(job.output_path),
        "created_at": utc_isoformat(job.created_at),
        "claimed_at": utc_isoformat(job.claimed_at) if job.claimed_at else None,
        "heartbeat_at": utc_isoformat(job.heartbeat_at) if job.heartbeat_at else None,
        "finished_at": utc_isoformat(job.finished_at) if job.finished_at else None,
    }
