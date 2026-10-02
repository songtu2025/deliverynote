from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import PURCHASE_STATUSES, warehouse_sort_key
from ..excel_io import read_purchase_workbook
from .models import (
    InputVersion,
    OverreceiptRuleVersion,
    SelfOperatedOverreceiptRuleVersion,
)

Rule = TypeVar("Rule", OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion)


@dataclass(frozen=True)
class RuleContext:
    """规则变更共用的会话、操作者和审计记录。"""

    session: Session
    user_id: int
    audit: Callable[..., None]


@dataclass(frozen=True)
class RuleMessages:
    """两类规则各自的审计名称和既有错误提示。"""

    entity: str
    missing: str
    publish_conflict: str
    activate_conflict: str


RULE_MESSAGES = {
    OverreceiptRuleVersion: RuleMessages(
        "overreceipt_rule",
        "超收规则版本不存在",
        "超收规则发布发生并发冲突，请刷新后重试",
        "超收规则启用发生并发冲突，请刷新后重试",
    ),
    SelfOperatedOverreceiptRuleVersion: RuleMessages(
        "self_operated_overreceipt_rule",
        "自营仓超收规则版本不存在",
        "自营仓超收规则发布发生并发冲突，请重试",
        "自营仓超收规则启用发生并发冲突，请重试",
    ),
}


def validated_rule_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="规则版本名称不能为空")
    return name


def validated_warehouses(allowed_warehouses: list[str]) -> list[str]:
    warehouses = [warehouse.strip() for warehouse in allowed_warehouses]
    if any(not warehouse for warehouse in warehouses):
        raise HTTPException(status_code=400, detail="允许超收仓库不能为空")
    if len(set(warehouses)) != len(warehouses):
        raise HTTPException(status_code=400, detail="允许超收仓库不能重复")
    return sorted(warehouses, key=warehouse_sort_key)


def _locked_versions(session: Session, model: type[Rule]) -> list[Rule]:
    return list(session.scalars(select(model).order_by(model.id).with_for_update()))


def rename_rule(
    context: RuleContext, model: type[Rule], version_id: int, name: str
) -> Rule:
    session = context.session
    messages = RULE_MESSAGES[model]
    versions = _locked_versions(session, model)
    target = next((version for version in versions if version.id == version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=messages.missing)
    if target.name == name:
        return target
    if any(version.id != version_id and version.name == name for version in versions):
        raise HTTPException(status_code=409, detail="规则版本名称已存在")
    before = target.name
    target.name = name
    context.audit(
        session,
        context.user_id,
        f"rename_{messages.entity}",
        messages.entity,
        target.id,
        {"before": before, "after": name},
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="规则版本名称已存在") from error
    return target


def activate_rule(context: RuleContext, model: type[Rule], version_id: int) -> Rule:
    session = context.session
    messages = RULE_MESSAGES[model]
    versions = _locked_versions(session, model)
    target = next((version for version in versions if version.id == version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=messages.missing)
    if target.active:
        return target
    for version in versions:
        version.active = False
    session.flush()
    target.active = True
    context.audit(
        session,
        context.user_id,
        f"activate_{messages.entity}",
        messages.entity,
        target.id,
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail=messages.activate_conflict
        ) from error
    return target


def publish_rule(
    context: RuleContext, version: Rule, audit_details: dict[str, Any]
) -> None:
    session = context.session
    messages = RULE_MESSAGES[type(version)]
    current_versions = _locked_versions(session, type(version))
    if any(current.name == version.name for current in current_versions):
        raise HTTPException(status_code=409, detail="规则版本名称已存在")
    for current in current_versions:
        current.active = False
    session.flush()
    session.add(version)
    try:
        session.flush()
        context.audit(
            session,
            context.user_id,
            f"publish_{messages.entity}",
            messages.entity,
            version.id,
            audit_details,
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail=messages.publish_conflict
        ) from error


def purchase_warehouses(
    session: Session, cache: dict[int, tuple[str, ...]]
) -> list[str]:
    purchase_version = session.scalar(
        select(InputVersion).where(
            InputVersion.kind == "purchase",
            InputVersion.active.is_(True),
        )
    )
    if purchase_version is None:
        return []
    cached = cache.get(purchase_version.id)
    if cached is not None:
        return list(cached)
    try:
        purchases = read_purchase_workbook(Path(purchase_version.storage_path))
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=409,
            detail=f"启用的采购需求版本无法读取：{error}",
        ) from error
    active = purchases[purchases["单据状态"].isin(PURCHASE_STATUSES)]
    warehouses = {
        str(value).strip()
        for value in active["目的仓"]
        if not pd.isna(value) and str(value).strip()
    }
    sorted_warehouses = tuple(sorted(warehouses, key=warehouse_sort_key))
    cache[purchase_version.id] = sorted_warehouses
    return list(sorted_warehouses)
