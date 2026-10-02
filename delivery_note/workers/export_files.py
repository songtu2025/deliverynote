from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select

from ..web.database import Database
from ..web.models import AuditLog, Batch, BatchFile, Job
from .leases import JobContext, LostJobLeaseError

LOGGER = logging.getLogger("delivery_note.worker")


def _cleanup_previous_export_directories(
    database: Database,
    export_root: Path,
    current_published: Path,
    previous_paths: Sequence[str | Path],
) -> None:
    """尽力清理已失去数据库引用的上一代导出目录。"""
    try:
        resolved_root = export_root.resolve()
        resolved_current = current_published.resolve()
        candidates: set[Path] = set()
        for previous_path in previous_paths:
            parent = Path(previous_path).parent
            if parent.is_symlink():
                continue
            candidate = parent.resolve()
            if (
                candidate.parent == resolved_root
                and candidate.name.startswith("export-")
                and candidate != resolved_current
            ):
                candidates.add(candidate)
        if not candidates:
            return

        with database.session() as session:
            registered_paths = [
                *session.scalars(
                    select(Batch.zip_path).where(Batch.zip_path.is_not(None))
                ).all(),
                *session.scalars(
                    select(BatchFile.result_path).where(
                        BatchFile.result_path.is_not(None)
                    )
                ).all(),
                *session.scalars(
                    select(Job.output_path).where(Job.output_path.is_not(None))
                ).all(),
            ]
        registered = [Path(cast(str, path)).resolve() for path in registered_paths]
    except Exception:
        LOGGER.warning("无法确认旧导出目录引用，已跳过清理", exc_info=True)
        return

    for candidate in candidates:
        if any(
            output_path == candidate or candidate in output_path.parents
            for output_path in registered
        ):
            continue
        if not candidate.is_dir():
            continue
        try:
            shutil.rmtree(candidate)
        except Exception:
            LOGGER.warning("旧导出目录清理失败：%s", candidate, exc_info=True)


def _published_is_registered(
    database: Database,
    job_id: int,
    archive_path: Path,
) -> bool:
    try:
        with database.session() as session:
            job = session.get(Job, job_id)
            return (
                job is not None
                and job.status == "succeeded"
                and job.output_path == str(archive_path)
            )
    except Exception:
        # 数据库状态无法确认时保留文件，避免删除已成功提交的正式结果。
        return True


@dataclass(frozen=True)
class ExportPublication:
    """本次生成的目录、来源文件和对外下载入口。"""

    directory: Path
    source_names: dict[int, str]
    registered_path: Path
    self_operated: bool = False


def _export_workspace(storage_root: Path, batch_id: int) -> tuple[Path, Path, Path]:
    """创建独立临时目录，发布成功后再清理上一代结果。"""
    export_root = storage_root / "batches" / str(batch_id) / "exports"
    export_token = uuid4().hex
    temporary = export_root / f".tmp-{export_token}"
    published = export_root / f"export-{export_token}"
    temporary.mkdir(parents=True, exist_ok=False)
    return export_root, temporary, published


def _write_export_archive(
    temporary: Path,
    archive_name: str,
    sources: list[dict[str, Any]],
    output_names: dict[int, str],
) -> None:
    with ZipFile(temporary / archive_name, "w", ZIP_DEFLATED) as archive:
        for source in sources:
            output_name = output_names[source["id"]]
            archive.write(temporary / output_name, arcname=output_name)


def _register_export(
    context: JobContext, batch_id: int, publication: ExportPublication
) -> None:
    """持有有效租约时，原子登记全部导出路径和任务完成状态。"""
    with context.database.session() as session:
        job = session.scalar(
            select(Job).where(Job.id == context.job_id).with_for_update()
        )
        batch = session.get(Batch, batch_id)
        if (
            job is None
            or batch is None
            or job.status != "running"
            or job.claim_token != context.claim_token
        ):
            raise LostJobLeaseError("导出任务租约已失效")
        for source_id, output_name in publication.source_names.items():
            stored_source = session.get(BatchFile, source_id)
            if stored_source is None or stored_source.batch_id != batch.id:
                raise RuntimeError("批次来源文件已变化")
            stored_source.result_path = str(publication.directory / output_name)
        batch.zip_path = str(publication.registered_path)
        if publication.self_operated:
            batch.error_message = None
        job.status = "succeeded"
        job.finished_at = datetime.utcnow()
        job.heartbeat_at = job.finished_at
        job.error_message = None
        job.claim_token = None
        job.output_path = str(publication.registered_path)
        session.add(
            AuditLog(
                user_id=None,
                action="worker_self_operated_export_succeeded"
                if publication.self_operated
                else "worker_export_succeeded",
                entity_type="batch",
                entity_id=str(batch.id),
                details={
                    "file_count": len(publication.source_names),
                    "merged_workbook": len(publication.source_names) > 1,
                },
            )
        )
        session.commit()


def _discard_failed_export(
    database: Database,
    job_id: int,
    temporary: Path,
    published: Path,
    registered_path: Path,
) -> None:
    """只删除当前尝试尚未登记的结果，保留已经发布的下载文件。"""
    if temporary.exists():
        shutil.rmtree(temporary)
    if published.exists() and not _published_is_registered(
        database, job_id, registered_path
    ):
        shutil.rmtree(published)
