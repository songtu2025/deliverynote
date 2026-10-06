"""记录文件内容与权限，并在同一文件系统内执行不覆盖的原子移动。"""

import ctypes
import os
from pathlib import Path
import stat
from typing import TypedDict

from scripts.audit_storage import path_state
from scripts.backup.archive import sha256


class FileState(TypedDict):
    kind: str
    size: int
    sha256: str
    mode: int
    uid: int
    gid: int
    mtime_ns: int


def safe_path(root: Path, relative: str) -> Path:
    """清单只允许根目录内的相对路径，拒绝路径穿越和符号链接。"""
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise ValueError("清单路径必须是根目录内的相对路径")
    target = root / value
    if path_state(target, root)[1] == "symlink":
        raise ValueError("清单路径包含符号链接")
    return target


def inventory(path: Path) -> dict[str, FileState]:
    """快照包含目录本身和全部成员，拒绝链接及特殊文件。"""
    result: dict[str, FileState] = {}
    paths = [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]
    for member in paths:
        info = member.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("隔离对象包含链接或特殊文件")
        directory = stat.S_ISDIR(info.st_mode)
        result[member.relative_to(path).as_posix()] = {
            "kind": "directory" if directory else "file",
            "size": 0 if directory else info.st_size,
            "sha256": "" if directory else sha256(member),
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mtime_ns": info.st_mtime_ns,
        }
    return result


def move_without_replace(source: Path, target: Path) -> None:
    """移动整个对象，保留内容与元数据，目标出现时原子拒绝覆盖。"""
    if os.name == "nt":
        os.rename(source, target)
        return
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    # Linux 的 RENAME_NOREPLACE 同时保护文件和目录；跨文件系统会失败。
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))
