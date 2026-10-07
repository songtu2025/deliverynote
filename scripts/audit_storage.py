"""只读核对存储引用并输出 JSON；疑似遗留仅供复核，不执行清理。"""

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Iterator, TypedDict

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from delivery_note.web.batch_views import merged_export_path
from delivery_note.web.models import (
    Batch,
    BatchFile,
    InputVersion,
    Job,
    PurchaseSyncJob,
    SelfOperatedBatch,
    SelfOperatedInboundSyncJob,
)
from scripts.storage_paths import artifact_owner, path_state, scan_paths
from scripts.storage_resources import (
    ResourceDetails,
    builtin_reference_paths,
    inspect_resource,
    runtime_paths,
)


# 区分业务引用、遗留候选、运行文件及内置资源。
CATEGORIES = (
    "normal_reference",
    "missing_reference",
    "suspected_residue",
    "active_task",
    "unknown",
    "managed_runtime",
    "builtin_resource",
)
ACTIVE = ("queued", "running")


class AuditEntry(ResourceDetails):
    path: str
    category: str
    kind: str


class AuditReport(TypedDict):
    status: str
    counts: dict[str, int]
    entries: list[AuditEntry]
    note: str


@dataclass(frozen=True)
class ReferenceSnapshot:
    paths: frozenset[Path]
    active_batches: frozenset[int]
    active_purchase: frozenset[int]
    active_inbound: frozenset[int]
    builtin_paths: frozenset[Path]


@contextmanager
def read_session(database_url: str) -> Iterator[Session]:
    """以只读权限打开已有数据库，所有查询使用同一事务快照。"""
    url = make_url(database_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        filename = Path(url.database or "")
        if not filename.is_file():
            raise ValueError("SQLite 数据库文件不存在")
        url = url.set(
            database=filename.absolute().as_uri(),
            query={**url.query, "mode": "ro", "uri": "true"},
        )
    elif backend != "postgresql":
        raise ValueError("仅支持 PostgreSQL 和已有 SQLite 文件")
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            if backend == "postgresql":
                session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
            else:
                session.execute(text("PRAGMA query_only = ON"))
                # Python 3.11 的 SQLite 驱动不会为 SELECT 自动开启事务。
                session.execute(text("BEGIN"))
            yield session
    finally:
        engine.dispose()


def read_snapshot(database_url: str) -> ReferenceSnapshot:
    with read_session(database_url) as session:
        paths: set[Path] = set()
        for column in (
            InputVersion.storage_path,
            Batch.zip_path,
            BatchFile.storage_path,
            BatchFile.result_path,
            SelfOperatedBatch.inbound_storage_path,
            Job.output_path,
        ):
            paths.update(
                Path(value) for value in session.scalars(select(column)) if value
            )
        source_counts = Counter(session.scalars(select(BatchFile.batch_id)))
        for batch in session.scalars(select(Batch)):
            merged = merged_export_path(batch)
            if source_counts[batch.id] > 1 and merged is not None:
                paths.add(merged)
        return ReferenceSnapshot(
            frozenset(paths),
            frozenset(
                session.scalars(select(Job.batch_id).where(Job.status.in_(ACTIVE)))
            ),
            frozenset(
                session.scalars(
                    select(PurchaseSyncJob.id).where(PurchaseSyncJob.status.in_(ACTIVE))
                )
            ),
            frozenset(
                session.scalars(
                    select(SelfOperatedInboundSyncJob.id).where(
                        SelfOperatedInboundSyncJob.status.in_(ACTIVE)
                    )
                )
            ),
            builtin_reference_paths(session),
        )


def classify_path(
    path: Path, root: Path, snapshot: ReferenceSnapshot
) -> tuple[str, str]:
    mode, kind = path_state(path, root)
    if mode is None:
        category = (
            "missing_reference"
            if kind == "missing" and path in snapshot.paths
            else "unknown"
        )
        return category, kind
    if path in snapshot.paths:
        return ("normal_reference" if stat.S_ISREG(mode) else "missing_reference"), kind
    owner = artifact_owner(path, root)
    if (
        kind == "directory"
        and owner
        and any(path in value.parents for value in snapshot.paths)
    ):
        return "normal_reference", kind
    if not owner or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        return "unknown", kind
    active = {
        "batch": snapshot.active_batches,
        "purchase": snapshot.active_purchase,
        "self_operated_inbound": snapshot.active_inbound,
    }
    return (
        "active_task" if owner[1] in active[owner[0]] else "suspected_residue"
    ), kind


def report_entries(entries: list[AuditEntry], complete: bool) -> AuditReport:
    counts = Counter(entry["category"] for entry in entries)
    return {
        "status": "complete" if complete else "incomplete",
        "counts": {category: counts[category] for category in CATEGORIES},
        "entries": entries,
        "note": (
            "条目按文件及已知生成目录计数；引用为只读快照，扫描期间文件可能变化。"
            "疑似遗留需复核，不代表可以删除。"
        ),
    }


def audit_storage(database_url: str, storage_root: Path) -> AuditReport:
    root = Path(os.path.abspath(storage_root))
    try:
        if not root.is_dir() or any(
            path.is_symlink() for path in (root, *root.parents)
        ):
            raise ValueError("存储目录不可核验")
        snapshot = read_snapshot(database_url)
    except Exception:
        # 不输出连接地址、凭据或数据库异常原文。
        return report_entries(
            [{"path": ".", "category": "unknown", "kind": "unavailable"}], False
        )
    paths, unreadable = scan_paths(root)
    paths.update(path for path in runtime_paths(root) if os.path.lexists(path))
    entries: list[AuditEntry] = []
    complete = not unreadable
    for path in sorted(paths | set(snapshot.paths), key=str):
        category, kind = classify_path(path, root, snapshot)
        details: ResourceDetails = {}
        resource = inspect_resource(path, root, snapshot.builtin_paths)
        if resource is not None:
            category, kind, details = resource
        if path in unreadable:
            category, kind = "unknown", "unavailable"
        complete = complete and kind != "unavailable"
        entries.append(
            {
                "path": path.relative_to(root).as_posix()
                if path.is_relative_to(root)
                else path.as_posix(),
                "category": category,
                "kind": kind,
                **details,
            }
        )
    return report_entries(entries, complete)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="数据库连接地址，默认读取 DATABASE_URL",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=os.getenv("STORAGE_ROOT") or None,
        help="存储目录，默认读取 STORAGE_ROOT",
    )
    args = parser.parse_args()
    if args.database_url and args.storage_root:
        report = audit_storage(args.database_url, args.storage_root)
    else:
        report = report_entries(
            [{"path": ".", "category": "unknown", "kind": "unavailable"}], False
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
