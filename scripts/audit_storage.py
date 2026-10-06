"""只读核对存储引用并输出 JSON；疑似遗留仅供复核，不执行清理。"""

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
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

# 分别对应正常引用、引用缺失、疑似遗留、活动任务相关及无法判断。
CATEGORIES = (
    "normal_reference",
    "missing_reference",
    "suspected_residue",
    "active_task",
    "unknown",
)
ACTIVE = ("queued", "running")
EXPORT_DIRECTORY = re.compile(r"(?:export-|\.tmp-)[0-9a-f]{32}")
CANDIDATES = {
    "purchase": re.compile(r"purchase_sync_([1-9]\d*)_积加采购数据_\d{8}_\d{6}\.xlsx"),
    "self_operated_inbound": re.compile(
        r"self_operated_inbound_sync_([1-9]\d*)_积加待入库数据_\d{8}_\d{6}\.xlsx"
    ),
}


class AuditEntry(TypedDict):
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
        )


def artifact_owner(path: Path, root: Path) -> tuple[str, int] | None:
    """只识别当前实现实际生成的导出目录和同步候选命名。"""
    if not path.is_relative_to(root):
        return None
    parts = path.relative_to(root).parts
    if (
        len(parts) in (4, 5)
        and parts[0] == "batches"
        and re.fullmatch(r"[1-9][0-9]*", parts[1])
        and parts[2] == "exports"
        and EXPORT_DIRECTORY.fullmatch(parts[3])
        and (len(parts) == 4 or path.suffix in (".xlsx", ".zip"))
    ):
        return "batch", int(parts[1])
    if len(parts) == 3 and parts[0] == "master" and parts[1] in CANDIDATES:
        match = CANDIDATES[parts[1]].fullmatch(parts[2])
        if match:
            return parts[1], int(match[1])
    return None


def scan_paths(root: Path) -> tuple[set[Path], set[Path]]:
    paths: set[Path] = set()
    unreadable: set[Path] = set()

    def failed(error: OSError) -> None:
        unreadable.add(Path(error.filename) if error.filename else root)

    for directory, names, files in os.walk(root, followlinks=False, onerror=failed):
        parent = Path(directory)
        paths.update(parent / name for name in files)
        for name in names:
            path = parent / name
            if path.is_symlink() or artifact_owner(path, root):
                paths.add(path)
    return paths | unreadable, unreadable


def path_state(path: Path, root: Path) -> tuple[int | None, str]:
    if not path.is_absolute() or not path.is_relative_to(root):
        return None, "outside_or_relative"
    try:
        if any(
            parent.is_symlink()
            for parent in (path, *path.parents)
            if parent.is_relative_to(root)
        ):
            return None, "symlink"
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unavailable"
    return mode, "directory" if stat.S_ISDIR(mode) else "file"


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
    entries: list[AuditEntry] = []
    complete = not unreadable
    for path in sorted(paths | set(snapshot.paths), key=str):
        category, kind = classify_path(path, root, snapshot)
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
