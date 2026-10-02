from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import cast

from sqlalchemy import select

from ..web.database import Database
from ..web.models import Batch, BatchFile, Job

LOGGER = logging.getLogger("delivery_note.worker")


def _cleanup_previous_export_directories(
    database: Database,
    export_root: Path,
    current_published: Path,
    previous_paths: list[str | Path],
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
