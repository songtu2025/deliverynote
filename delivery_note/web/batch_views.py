"""共用批次数量统计，并组装列表和详情响应。"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.engine import Row

from .batch_queries import (
    VERSION_FIELDS,
    BatchMetadata,
    batch_jobs,
    batch_metadata,
    batch_metadata_by_id,
    batch_site_resolutions,
    batch_source_rows,
    batch_sources,
    batch_versions,
    exception_totals_by_source,
)
from .models import Batch, BatchFile
from .serializers import (
    job_json,
    overreceipt_rule_json,
    self_operated_overreceipt_rule_json,
    utc_isoformat,
    version_json,
)


@dataclass
class BatchTotals:
    file_count: int = 0
    delivery_total: int = 0
    import_total: int = 0
    manual_total: int = 0

    def summary(self) -> dict[str, int | bool]:
        return {
            "delivery_total": self.delivery_total,
            "import_total": self.import_total,
            "manual_total": self.manual_total,
            "conserved": self.delivery_total == self.import_total + self.manual_total,
        }


def _totals_by_batch(
    sources: Iterable[BatchFile | Row[int, int, int, int]],
    exception_totals: dict[int, tuple[int, int]],
) -> dict[int, BatchTotals]:
    """共用 ORM 文件和列表标量记录，统一计入已解决的拆分数量。"""
    result: dict[int, BatchTotals] = {}
    for source in sources:
        totals = result.setdefault(source.batch_id, BatchTotals())
        resolved, manual = exception_totals.get(source.id, (0, 0))
        totals.file_count += 1
        totals.delivery_total += source.delivery_total
        totals.import_total += source.import_total + resolved
        totals.manual_total += manual
    return result


def file_json(
    source: BatchFile,
    *,
    import_total: int | None = None,
    manual_total: int | None = None,
) -> dict[str, object]:
    return {
        "id": source.id,
        "batch_id": source.batch_id,
        "original_name": source.original_name,
        "file_order": source.file_order,
        "supplier_name": source.supplier_name,
        "supplier_code": source.supplier_code,
        "document_note": source.document_note,
        "delivery_total": source.delivery_total,
        "import_total": source.import_total if import_total is None else import_total,
        "manual_total": source.manual_total if manual_total is None else manual_total,
        "download_ready": bool(source.result_path),
    }


def merged_export_path(batch: Batch) -> Path | None:
    if not batch.zip_path:
        return None
    return Path(batch.zip_path).with_name(f"batch-{batch.id}-merged.xlsx")


def merged_export_ready(batch: Batch, source_count: int) -> bool:
    path = merged_export_path(batch)
    return source_count > 1 and path is not None and path.is_file()


def _version_ids(batch: Batch, metadata: BatchMetadata) -> dict[str, int | None]:
    versions: dict[str, int | None] = {
        kind: getattr(batch, field) for kind, field in VERSION_FIELDS.items()
    }
    if (
        metadata.self_operated is not None
        and metadata.self_operated.inbound_storage_path
    ):
        versions["self_operated_inbound"] = (
            metadata.inbound_source.id if metadata.inbound_source is not None else None
        )
    return versions


def _batch_base_json(
    batch: Batch, metadata: BatchMetadata, totals: BatchTotals
) -> dict[str, object]:
    self_operated = metadata.self_operated
    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "workflow": "self_operated_inbound"
        if self_operated is not None
        else "delivery",
        "created_by": batch.created_by,
        "version_ids": _version_ids(batch, metadata),
        "overreceipt_rule": (
            overreceipt_rule_json(metadata.overreceipt_rule)
            if metadata.overreceipt_rule is not None
            else None
        ),
        "self_operated_overreceipt_rule": (
            self_operated_overreceipt_rule_json(metadata.self_operated_rule)
            if metadata.self_operated_rule is not None
            else None
        ),
        "inbound_file": (
            {
                "original_name": self_operated.inbound_original_name,
                "uploaded": bool(self_operated.inbound_storage_path),
            }
            if self_operated is not None
            else None
        ),
        "error_message": batch.error_message,
        "download_ready": bool(batch.zip_path),
        "merged_download_ready": merged_export_ready(batch, totals.file_count),
        "created_at": utc_isoformat(batch.created_at),
        "updated_at": utc_isoformat(batch.updated_at),
        "file_count": totals.file_count,
        "summary": totals.summary(),
    }


def _batch_details(
    batch: Batch,
    metadata: BatchMetadata,
    sources: list[BatchFile],
    exception_totals: dict[int, tuple[int, int]],
    session: Session,
) -> dict[str, object]:
    return {
        "files": [
            file_json(
                source,
                import_total=source.import_total
                + exception_totals.get(source.id, (0, 0))[0],
                manual_total=exception_totals.get(source.id, (0, 0))[1],
            )
            for source in sources
        ],
        "versions": {
            kind: version_json(version)
            for kind, version in batch_versions(session, batch, metadata).items()
        },
        "jobs": {job.kind: job_json(job) for job in batch_jobs(session, batch.id)},
        "site_resolutions": [
            {
                "id": resolution.id,
                "sku": resolution.sku,
                "original_site": resolution.original_site,
                "full_site": resolution.full_site,
                "updated_at": utc_isoformat(resolution.updated_at),
            }
            for resolution in batch_site_resolutions(session, batch.id)
        ]
        if metadata.self_operated is not None
        else [],
    }


def batch_json(
    batch: Batch, session: Session, include_files: bool = True
) -> dict[str, object]:
    sources = batch_sources(session, batch.id)
    exception_totals = exception_totals_by_source(
        session, [source.id for source in sources]
    )
    totals = _totals_by_batch(sources, exception_totals).get(batch.id, BatchTotals())
    metadata = batch_metadata(session, batch.id)
    result = _batch_base_json(batch, metadata, totals)
    if include_files:
        result.update(
            _batch_details(batch, metadata, sources, exception_totals, session)
        )
    return result


def batch_list_json(
    batches: Sequence[Batch], session: Session
) -> list[dict[str, object]]:
    if not batches:
        return []
    batch_ids = [batch.id for batch in batches]
    sources = batch_source_rows(session, batch_ids)
    exception_totals = exception_totals_by_source(
        session, [source.id for source in sources]
    )
    totals = _totals_by_batch(sources, exception_totals)
    metadata = batch_metadata_by_id(session, batch_ids)
    return [
        _batch_base_json(
            batch,
            metadata.get(batch.id, BatchMetadata()),
            totals.get(batch.id, BatchTotals()),
        )
        for batch in batches
    ]
