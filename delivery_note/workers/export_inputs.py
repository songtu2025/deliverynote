from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..application import SplitPart
from ..web.database import Database
from ..web.models import Batch, BatchFile, ExceptionRecord, SplitRecord
from ..workers.compute_inputs import _version_paths
from .export_rows import _exception_dict


def _load_export_inputs(
    database: Database, batch_id: int
) -> tuple[dict[str, Path], list[dict[str, Any]], list[str]]:
    with database.session() as session:
        batch = session.get(Batch, batch_id)
        if batch is None or batch.status != "succeeded":
            raise RuntimeError("批次尚未计算成功")
        version_paths = _version_paths(session, batch)
        sources = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch.id)
            .order_by(BatchFile.file_order)
        ).all()
        previous_export_paths = [
            path
            for path in [
                batch.zip_path,
                *(source.result_path for source in sources),
            ]
            if path
        ]
        source_ids = [source.id for source in sources]
        exceptions = (
            session.scalars(
                select(ExceptionRecord)
                .where(ExceptionRecord.batch_file_id.in_(source_ids))
                .order_by(
                    ExceptionRecord.batch_file_id,
                    ExceptionRecord.id,
                )
            ).all()
            if source_ids
            else []
        )
        exception_ids = [exception.id for exception in exceptions]
        parts = (
            session.scalars(
                select(SplitRecord)
                .where(SplitRecord.exception_id.in_(exception_ids))
                .order_by(SplitRecord.exception_id, SplitRecord.id)
            ).all()
            if exception_ids
            else []
        )
        exceptions_by_source: dict[int, list[ExceptionRecord]] = {}
        for exception in exceptions:
            exceptions_by_source.setdefault(
                exception.batch_file_id,
                [],
            ).append(exception)
        parts_by_exception: dict[int, list[SplitRecord]] = {}
        for part in parts:
            parts_by_exception.setdefault(part.exception_id, []).append(part)
        payloads = []
        for source in sources:
            exception_payloads = []
            for exception in exceptions_by_source.get(source.id, []):
                exception_payloads.append(
                    {
                        "row": _exception_dict(exception),
                        "parts": [
                            SplitPart(
                                quantity=part.quantity,
                                destination=part.destination,
                                site=part.site,
                                supplier_code=part.supplier_code,
                                sku=part.sku,
                                delivery_note=part.delivery_note,
                                resolved=part.resolved,
                            )
                            for part in parts_by_exception.get(
                                exception.id,
                                [],
                            )
                        ],
                    }
                )
            payloads.append(
                {
                    "id": source.id,
                    "original_name": source.original_name,
                    "file_order": source.file_order,
                    "supplier_code": source.supplier_code,
                    "document_note": source.document_note,
                    "delivery_total": source.delivery_total,
                    "import_rows": source.import_rows or [],
                    "exceptions": exception_payloads,
                }
            )
    return version_paths, payloads, previous_export_paths
