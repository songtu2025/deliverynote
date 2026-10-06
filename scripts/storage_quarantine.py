"""按明确清单隔离历史批次导出；保留全部内容，不修改数据库。"""

import argparse
import json
import os
from pathlib import Path
from typing import TypedDict, cast

from scripts.audit_storage import artifact_owner, audit_storage
from scripts.backup.archive import write_private_text
from scripts.backup.runtime import DEFAULT_LOCK_FILE, exclusive_lock
from scripts.quarantine_files import (
    FileState,
    inventory,
    move_without_replace,
    safe_path,
)


class QuarantineEntry(TypedDict):
    path: str
    members: dict[str, FileState]


class QuarantinePlan(TypedDict):
    storage_root: str
    entries: list[QuarantineEntry]


def _roots(root: Path, directory: Path) -> tuple[Path, Path]:
    root, directory = root.absolute(), directory.absolute()
    if root.resolve() != root or directory.resolve() != directory:
        raise ValueError("业务或隔离目录包含符号链接")
    if directory.is_relative_to(root) or root.is_relative_to(directory):
        raise ValueError("隔离目录必须在业务存储之外")
    if not root.is_dir():
        raise ValueError("业务存储目录不存在")
    parent = directory
    while not parent.exists():
        parent = parent.parent
    if root.stat().st_dev != parent.stat().st_dev:
        raise ValueError("隔离必须使用同一文件系统")
    return root, directory


def _validate_unreferenced(
    database_url: str, root: Path, entries: list[QuarantineEntry]
) -> None:
    report = audit_storage(database_url, root)
    if report["status"] != "complete":
        raise ValueError("存储审计未完成，拒绝移动")
    categories = {entry["path"]: entry["category"] for entry in report["entries"]}
    for entry in entries:
        source = safe_path(root, entry["path"])
        owner = artifact_owner(source, root)
        if owner is None or owner[0] != "batch":
            raise ValueError("只允许已知批次导出目录或文件")
        for relative in entry["members"]:
            member = source if relative == "." else safe_path(source, relative)
            if (
                categories.get(member.relative_to(root).as_posix())
                != "suspected_residue"
            ):
                raise ValueError("清单对象存在引用、活动任务或无法判断项")


def prepare_quarantine(
    database_url: str, storage_root: Path, paths: list[str], directory: Path
) -> QuarantinePlan:
    """生成不可覆盖的执行清单；业务数据和数据库保持只读。"""
    root, directory = _roots(storage_root, directory)
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("清单必须非空且路径不能重复")
    sources = [safe_path(root, path) for path in sorted(paths)]
    if any(source in other.parents for source in sources for other in sources):
        raise ValueError("清单不能同时选择目录及其子项")
    entries = [
        QuarantineEntry(
            path=source.relative_to(root).as_posix(), members=inventory(source)
        )
        for source in sources
    ]
    _validate_unreferenced(database_url, root, entries)
    plan = QuarantinePlan(storage_root=str(root), entries=entries)
    directory.mkdir(parents=True, mode=0o700)
    write_private_text(
        directory / "manifest.json", json.dumps(plan, ensure_ascii=False)
    )
    return plan


def _locations(
    root: Path, directory: Path, entry: QuarantineEntry
) -> tuple[Path, Path]:
    source = safe_path(root, entry["path"])
    target = safe_path(directory / "artifacts", entry["path"])
    exists = [os.path.lexists(path) for path in (source, target)]
    if exists.count(True) != 1:
        raise ValueError("对象必须只存在于原目录或隔离目录，不能覆盖或猜测")
    actual = inventory(source if exists[0] else target)
    if actual != entry["members"]:
        raise ValueError("对象内容、成员或权限已变化")
    return source, target


def transition_quarantine(
    database_url: str, storage_root: Path, directory: Path, *, restore: bool = False
) -> dict[str, int]:
    """调用方须持有共享运维锁；中断后可继续执行或按原清单恢复。"""
    root, directory = _roots(storage_root, directory)
    manifest = safe_path(directory, "manifest.json")
    plan = cast(QuarantinePlan, json.loads(manifest.read_text(encoding="utf-8")))
    if plan["storage_root"] != str(root) or not plan["entries"]:
        raise ValueError("清单与业务根目录不一致或为空")
    entries = plan["entries"]
    locations = [_locations(root, directory, entry) for entry in entries]
    # 执行前检查整份清单，避免后面出现冲突时才发现前面的对象已移动。
    if not restore:
        _validate_unreferenced(
            database_url,
            root,
            [
                entry
                for entry, (source, _) in zip(entries, locations)
                if source.exists()
            ],
        )
    moved = 0
    for entry in entries:
        source, target = _locations(root, directory, entry)
        start, end = (target, source) if restore else (source, target)
        if not start.exists():
            continue
        if restore:
            if not end.parent.is_dir():
                raise ValueError("原父目录已变化，拒绝猜测目录权限")
        else:
            _validate_unreferenced(database_url, root, [entry])
            end.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        move_without_replace(start, end)
        moved += 1
        _locations(root, directory, entry)
    file_count = sum(
        member["kind"] == "file"
        for entry in entries
        for member in entry["members"].values()
    )
    return {
        "moved_objects": moved,
        "selected_objects": len(entries),
        "preserved_files": file_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "apply", "restore"):
        operations.add_argument("--" + name, action="store_true")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--storage-root", type=Path, default=os.getenv("STORAGE_ROOT"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    args = parser.parse_args()
    if not args.database_url or args.storage_root is None:
        parser.error("必须提供数据库和业务存储目录")
    result: QuarantinePlan | dict[str, int]
    with exclusive_lock(args.lock_file):
        if args.prepare:
            result = prepare_quarantine(
                args.database_url, args.storage_root, args.path, args.directory
            )
        else:
            result = transition_quarantine(
                args.database_url,
                args.storage_root,
                args.directory,
                restore=args.restore,
            )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
