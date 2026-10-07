"""复用存储路径识别和不跟随符号链接的文件状态检查。"""

import os
from pathlib import Path
import re
import stat


EXPORT_DIRECTORY = re.compile(r"(?:export-|\.tmp-)[0-9a-f]{32}")
CANDIDATES = {
    "purchase": re.compile(r"purchase_sync_([1-9]\d*)_积加采购数据_\d{8}_\d{6}\.xlsx"),
    "self_operated_inbound": re.compile(
        r"self_operated_inbound_sync_([1-9]\d*)_积加待入库数据_\d{8}_\d{6}\.xlsx"
    ),
}


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
