"""准备单个交货批次的合并表；显式发布只补缺失文件，不修改数据库。"""

import argparse
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from typing import Any, cast
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from delivery_note.excel_io import read_position_workbook
from delivery_note.web.batch_views import merged_export_path
from delivery_note.web.database import Database
from delivery_note.web.models import Batch, BatchFile, Job, SelfOperatedBatch
from delivery_note.workers.export_delivery import _write_merged_delivery
from delivery_note.workers.export_inputs import _load_export_inputs
from delivery_note.workers.export_rows import _prepare_export_result
from scripts.audit_storage import path_state, read_session
from scripts.backup.archive import sha256
from scripts.merged_export_checks import check_source_workbook


class _SnapshotDatabase:
    """让现有输入加载器共用当前只读事务，不创建或修改数据库。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def session(self) -> nullcontext[Session]:
        return nullcontext(self._session)


@dataclass
class ExportPlan:
    versions: dict[str, Path]
    sources: list[dict[str, Any]]
    results: list[Path]
    archive: Path
    target: Path
    digest: str


def read_plan(database_url: str, root: Path, batch_id: int) -> ExportPlan:
    with read_session(database_url) as session:
        batch = session.get(Batch, batch_id)
        jobs = session.scalars(select(Job).where(Job.batch_id == batch_id)).all()
        export = next((job for job in jobs if job.kind == "export"), None)
        if (
            batch is None
            or batch.status != "succeeded"
            or session.get(SelfOperatedBatch, batch_id) is not None
            or export is None
            or export.status != "succeeded"
            or any(job.status in ("queued", "running") for job in jobs)
        ):
            raise ValueError("仅支持没有活动任务且已成功导出的交货批次")
        target = merged_export_path(batch)
        if target is None or os.path.lexists(target):
            raise ValueError("目标合并文件已存在或无法定位")
        versions, sources, _ = _load_export_inputs(
            cast(Database, _SnapshotDatabase(session)), batch_id
        )
        stored = session.scalars(
            select(BatchFile)
            .where(BatchFile.batch_id == batch_id)
            .order_by(BatchFile.file_order)
        ).all()
        if len(stored) <= 1 or any(not source.result_path for source in stored):
            raise ValueError("批次必须具有多份完整的分文件导出")
        results = [Path(cast(str, source.result_path)) for source in stored]
        archive = Path(cast(str, batch.zip_path))
        paths = {*versions.values(), *results, archive}
        if any(path_state(path, root)[1] != "file" for path in paths):
            raise ValueError("锁定资料或历史结果缺失、越界或无法核验")
        if path_state(target.parent, root)[1] != "directory":
            raise ValueError("目标目录无法核验")
        state = {
            "batch": {
                column.name: getattr(batch, column.name)
                for column in Batch.__table__.columns
            },
            "sources": sources,
            "results": results,
            "jobs": [
                {
                    column.name: getattr(job, column.name)
                    for column in Job.__table__.columns
                }
                for job in jobs
            ],
            "files": {str(path): sha256(path) for path in sorted(paths)},
        }
        digest = hashlib.sha256(
            json.dumps(state, default=str, sort_keys=True).encode()
        ).hexdigest()
    return ExportPlan(versions, sources, results, archive, target, digest)


def prepare_export(
    database_url: str, storage_root: Path, batch_id: int, directory: Path
) -> dict[str, Any]:
    root = storage_root.absolute()
    directory = directory.resolve()
    if directory.is_relative_to(root) or root.is_relative_to(directory):
        raise ValueError("候选目录必须位于业务存储之外")
    plan = read_plan(database_url, root, batch_id)
    position = read_position_workbook(plan.versions["position"])
    frames = [_prepare_export_result(source, position) for source in plan.sources]
    checks = []
    with ZipFile(plan.archive) as archive:
        if archive.testzip() is not None or archive.namelist() != [
            path.name for path in plan.results
        ]:
            raise ValueError("原 ZIP 校验或来源顺序不一致")
        for path, (_, imported, pending) in zip(plan.results, frames):
            payload = archive.read(path.name)
            if payload != path.read_bytes():
                raise ValueError("原 ZIP 与登记的分文件结果不一致")
            checks.append(
                check_source_workbook(
                    payload, imported, pending, plan.versions["template"]
                )
            )
    directory.mkdir(parents=True, exist_ok=False)
    try:
        _write_merged_delivery(
            plan.versions["template"],
            directory,
            batch_id,
            plan.sources,
            ([value[1] for value in frames], [value[2] for value in frames]),
        )
        candidate = directory / plan.target.name
        if read_plan(database_url, root, batch_id).digest != plan.digest:
            raise ValueError("准备期间批次记录或引用文件已变化")
        report = {
            "batch_id": batch_id,
            "target": plan.target.relative_to(root).as_posix(),
            "state_sha256": plan.digest,
            "candidate_sha256": sha256(candidate),
            "source_count": len(plan.sources),
            "delivery_total": sum(value[0].delivery_total for value in frames),
            "import_total": sum(value[0].import_total for value in frames),
            "pending_total": sum(value[0].manual_total for value in frames),
            "legacy_layout_count": sum(value["legacy_layout"] for value in checks),
            "style_differences": sum(value["style_differences"] for value in checks),
        }
        (directory / "manifest.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(directory)
        raise
    return report


def publish_export(database_url: str, storage_root: Path, directory: Path) -> Path:
    """重新核验后原子补写缺失文件；硬链接确保不会覆盖并发出现的目标。"""
    root = storage_root.absolute()
    report = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    plan = read_plan(database_url, root, int(report["batch_id"]))
    candidate = directory / plan.target.name
    if (
        report["target"] != plan.target.relative_to(root).as_posix()
        or report["state_sha256"] != plan.digest
        or report["candidate_sha256"] != sha256(candidate)
    ):
        raise ValueError("候选或正式批次状态已变化，请重新准备并复核")
    handle = NamedTemporaryFile(
        dir=plan.target.parent, prefix=".merged-recovery-", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            with candidate.open("rb") as source:
                shutil.copyfileobj(source, handle)
            handle.flush()
            os.fsync(handle.fileno())
        if (
            sha256(temporary) != report["candidate_sha256"]
            or read_plan(database_url, root, int(report["batch_id"])).digest
            != plan.digest
        ):
            raise ValueError("发布前候选或批次状态已变化")
        os.link(temporary, plan.target)
    finally:
        temporary.unlink(missing_ok=True)
    return plan.target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--storage-root", type=Path, default=os.getenv("STORAGE_ROOT"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--batch-id", type=int)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="显式补写正式文件，执行前必须确认恢复结果",
    )
    args = parser.parse_args()
    if (
        not args.database_url
        or not args.storage_root
        or (not args.publish and not args.batch_id)
    ):
        parser.error("必须提供数据库、存储目录及准备阶段的批次 ID")
    try:
        result = (
            {
                "published": str(
                    publish_export(args.database_url, args.storage_root, args.directory)
                )
            }
            if args.publish
            else prepare_export(
                args.database_url, args.storage_root, args.batch_id, args.directory
            )
        )
    except Exception:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "message": "核验失败，未覆盖已有结果；请检查批次与候选状态",
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
