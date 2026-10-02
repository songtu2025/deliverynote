from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..pipeline import OverreceiptPolicy
from ..web.database import Database
from ..web.models import (
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    InputVersion,
    OverreceiptRuleVersion,
    SelfOperatedBatch,
    SelfOperatedOverreceiptRuleVersion,
    SelfOperatedSiteResolution,
)

from ..web.batch_versions import VERSION_FIELDS


@dataclass
class ComputeInputs:
    """计算开始前读取的锁定资料和有序来源快照。"""

    version_paths: dict[str, Path]
    sources: list[dict[str, Any]]
    overreceipt_policy: OverreceiptPolicy | None
    self_operated_data: dict[str, Any] | None


def _version_paths(
    session: Session,
    batch: Batch,
    kinds: tuple[str, ...] = tuple(VERSION_FIELDS),
) -> dict[str, Path]:
    result = {}
    for kind in kinds:
        version_id = getattr(batch, VERSION_FIELDS[kind])
        if version_id is None:
            raise RuntimeError(f"批次缺少锁定的 {kind} 输入版本")
        version = session.get(InputVersion, version_id)
        if version is None:
            raise RuntimeError(f"批次缺少锁定的 {kind} 输入版本")
        path = Path(version.storage_path)
        if not path.is_file():
            raise FileNotFoundError(f"批次输入版本文件不存在：{path}")
        result[kind] = path
    return result


def _load_compute_inputs(database: Database, batch_id: int) -> ComputeInputs:
    with database.session() as session:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise RuntimeError("批次不存在")
        profile = session.get(SelfOperatedBatch, batch.id)
        version_kinds = (
            ("product", "supplier") if profile is not None else tuple(VERSION_FIELDS)
        )
        version_paths = _version_paths(session, batch, version_kinds)
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        if not sources:
            raise RuntimeError("批次没有交货文件")
        source_data = [
            {
                "id": source.id,
                "path": Path(source.storage_path),
                "original_name": source.original_name,
                "file_order": source.file_order,
            }
            for source in sources
        ]
        overreceipt_policy: OverreceiptPolicy | None = None
        binding = session.get(BatchOverreceiptRule, batch.id)
        if binding is not None:
            rule = session.get(OverreceiptRuleVersion, binding.rule_version_id)
            if rule is None:
                raise RuntimeError("批次锁定的超收规则版本不存在")
            overreceipt_policy = OverreceiptPolicy(
                short_tail_limit=rule.short_tail_limit,
                medium_tail_limit=rule.medium_tail_limit,
                long_tail_limit=rule.long_tail_limit,
                allowed_warehouses=frozenset(rule.allowed_warehouses or []),
            )
        self_operated_data: dict[str, Any] | None = None
        if profile is not None:
            inbound_path = Path(profile.inbound_storage_path)
            if not profile.inbound_storage_path or not inbound_path.is_file():
                raise FileNotFoundError("自营仓收货入库单不存在")
            template = session.get(InputVersion, profile.template_version_id)
            if template is None or not Path(template.storage_path).is_file():
                raise FileNotFoundError("批次锁定的积加入库模板不存在")
            inbound_rule = (
                session.get(
                    SelfOperatedOverreceiptRuleVersion,
                    profile.rule_version_id,
                )
                if profile.rule_version_id is not None
                else None
            )
            resolutions = session.scalars(
                select(SelfOperatedSiteResolution).where(
                    SelfOperatedSiteResolution.batch_id == batch.id
                )
            ).all()
            self_operated_data = {
                "inbound_path": inbound_path,
                "template_path": Path(template.storage_path),
                "overreceipt_limit": inbound_rule.allowance
                if inbound_rule is not None
                else 0,
                "site_overrides": {
                    (resolution.sku, resolution.original_site): resolution.full_site
                    for resolution in resolutions
                },
            }
    return ComputeInputs(
        version_paths, source_data, overreceipt_policy, self_operated_data
    )
