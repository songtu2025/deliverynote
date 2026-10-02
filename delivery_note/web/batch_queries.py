"""批次详情和列表的数据读取，不修改业务状态。"""

from dataclasses import dataclass
from sqlalchemy import and_, case, func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, load_only

from .models import (
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputVersion,
    Job,
    OverreceiptRuleVersion,
    SelfOperatedBatch,
    SelfOperatedOverreceiptRuleVersion,
    SelfOperatedSiteResolution,
    SplitRecord,
)


VERSION_FIELDS = {
    "purchase": "purchase_version_id",
    "product": "product_version_id",
    "supplier": "supplier_version_id",
    "position": "position_version_id",
    "template": "template_version_id",
}


@dataclass
class BatchMetadata:
    """保存当前会话读取的锁定规则和自营仓来源。"""

    overreceipt_rule: OverreceiptRuleVersion | None = None
    self_operated: SelfOperatedBatch | None = None
    self_operated_rule: SelfOperatedOverreceiptRuleVersion | None = None
    inbound_source: InputVersion | None = None


def batch_sources(session: Session, batch_id: int) -> list[BatchFile]:
    """按文件顺序读取详情所需字段，不加载计算结果明细。"""
    return list(
        session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch_id)
            .order_by(BatchFile.file_order)
            .options(
                load_only(
                    BatchFile.id,
                    BatchFile.batch_id,
                    BatchFile.original_name,
                    BatchFile.file_order,
                    BatchFile.supplier_name,
                    BatchFile.supplier_code,
                    BatchFile.document_note,
                    BatchFile.delivery_total,
                    BatchFile.import_total,
                    BatchFile.manual_total,
                    BatchFile.result_path,
                )
            )
        ).all()
    )


def batch_source_rows(
    session: Session, batch_ids: list[int]
) -> list[Row[tuple[int, int, int, int]]]:
    return list(
        session.execute(
            select(
                BatchFile.id,
                BatchFile.batch_id,
                BatchFile.delivery_total,
                BatchFile.import_total,
            ).where(BatchFile.batch_id.in_(batch_ids))
        ).all()
    )


def exception_totals_by_source(
    session: Session, source_ids: list[int]
) -> dict[int, tuple[int, int]]:
    if not source_ids:
        return {}
    return {
        source_id: (resolved_total or 0, manual_total or 0)
        for source_id, resolved_total, manual_total in session.execute(
            select(
                ExceptionRecord.batch_file_id,
                func.sum(
                    case(
                        (SplitRecord.resolved.is_(True), SplitRecord.quantity),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (SplitRecord.id.is_(None), ExceptionRecord.manual_quantity),
                        (SplitRecord.resolved.is_(False), SplitRecord.quantity),
                        else_=0,
                    )
                ),
            )
            .outerjoin(SplitRecord, SplitRecord.exception_id == ExceptionRecord.id)
            .where(ExceptionRecord.batch_file_id.in_(source_ids))
            .group_by(ExceptionRecord.batch_file_id)
        )
    }


def batch_metadata(session: Session, batch_id: int) -> BatchMetadata:
    binding = session.get(BatchOverreceiptRule, batch_id)
    overreceipt_rule = (
        session.get(OverreceiptRuleVersion, binding.rule_version_id)
        if binding is not None
        else None
    )
    self_operated = session.get(SelfOperatedBatch, batch_id)
    self_operated_rule = (
        session.get(SelfOperatedOverreceiptRuleVersion, self_operated.rule_version_id)
        if self_operated is not None and self_operated.rule_version_id is not None
        else None
    )
    inbound_source = None
    if self_operated is not None and self_operated.inbound_storage_path:
        inbound_source = session.scalar(
            select(InputVersion).where(
                InputVersion.kind == "self_operated_inbound",
                InputVersion.storage_path == self_operated.inbound_storage_path,
            )
        )
    return BatchMetadata(
        overreceipt_rule,
        self_operated,
        self_operated_rule,
        inbound_source,
    )


def _self_operated_metadata_rows(
    session: Session, batch_ids: list[int]
) -> list[
    Row[
        tuple[
            SelfOperatedBatch,
            SelfOperatedOverreceiptRuleVersion | None,
            InputVersion | None,
        ]
    ]
]:
    return list(
        session.execute(
            select(SelfOperatedBatch, SelfOperatedOverreceiptRuleVersion, InputVersion)
            .select_from(SelfOperatedBatch)
            .outerjoin(
                SelfOperatedOverreceiptRuleVersion,
                SelfOperatedOverreceiptRuleVersion.id
                == SelfOperatedBatch.rule_version_id,
            )
            .outerjoin(
                InputVersion,
                and_(
                    SelfOperatedBatch.inbound_storage_path != "",
                    InputVersion.kind == "self_operated_inbound",
                    InputVersion.storage_path == SelfOperatedBatch.inbound_storage_path,
                ),
            )
            .where(SelfOperatedBatch.batch_id.in_(batch_ids))
            .order_by(SelfOperatedBatch.batch_id, InputVersion.id)
        ).all()
    )


def batch_metadata_by_id(
    session: Session, batch_ids: list[int]
) -> dict[int, BatchMetadata]:
    """列表批量加载锁定规则，保持查询次数与批次数量无关。"""
    metadata: dict[int, BatchMetadata] = {}
    bindings = session.execute(
        select(BatchOverreceiptRule, OverreceiptRuleVersion)
        .join(
            OverreceiptRuleVersion,
            OverreceiptRuleVersion.id == BatchOverreceiptRule.rule_version_id,
        )
        .where(BatchOverreceiptRule.batch_id.in_(batch_ids))
    ).all()
    for binding, rule in bindings:
        metadata.setdefault(binding.batch_id, BatchMetadata()).overreceipt_rule = rule
    for self_operated, rule, inbound_source in _self_operated_metadata_rows(
        session, batch_ids
    ):
        entry = metadata.setdefault(self_operated.batch_id, BatchMetadata())
        if entry.self_operated is not None:
            continue
        entry.self_operated = self_operated
        entry.self_operated_rule = rule
        entry.inbound_source = inbound_source
    return metadata


def batch_versions(
    session: Session, batch: Batch, metadata: BatchMetadata
) -> dict[str, InputVersion]:
    versions = {
        kind: version
        for kind, field in VERSION_FIELDS.items()
        if (version_id := getattr(batch, field)) is not None
        if (version := session.get(InputVersion, version_id)) is not None
    }
    if metadata.self_operated is not None:
        template = session.get(InputVersion, metadata.self_operated.template_version_id)
        if template is not None:
            versions["inbound_template"] = template
        if metadata.inbound_source is not None:
            versions["self_operated_inbound"] = metadata.inbound_source
    return versions


def batch_jobs(session: Session, batch_id: int) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(Job.batch_id == batch_id).order_by(Job.id)
        ).all()
    )


def batch_site_resolutions(
    session: Session, batch_id: int
) -> list[SelfOperatedSiteResolution]:
    return list(
        session.scalars(
            select(SelfOperatedSiteResolution)
            .where(SelfOperatedSiteResolution.batch_id == batch_id)
            .order_by(SelfOperatedSiteResolution.id)
        ).all()
    )
