from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from scripts.backup.runtime import BackupError, Runner


BACKUP_NAME_PATTERN = re.compile(r"^\d{8}-\d{6}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_private_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def create_data_archive(
    runner: Runner,
    *,
    api_image: str,
    data_volume: str,
    backup_directory: Path,
    timeout_seconds: int,
) -> Path:
    target = backup_directory / "delivery_data.tar.gz"
    # 容器读取私有文件，宿主执行者拥有归档，不放宽源凭据权限。
    with target.open("xb") as output:
        target.chmod(0o600)
        runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0:0",
                "--network",
                "none",
                "--volume",
                f"{data_volume}:/source:ro",
                api_image,
                "tar",
                "--numeric-owner",
                "-czf",
                "-",
                "-C",
                "/source",
                ".",
            ],
            stdout=output,
            timeout_seconds=timeout_seconds,
        )
    if not target.is_file() or target.stat().st_size == 0:
        raise BackupError("文件卷备份为空或未生成")
    return target


def validate_data_archive(path: Path) -> tuple[int, int]:
    entries = 0
    files = 0
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise BackupError(f"文件卷归档包含不安全路径：{member.name}")
                if member.issym() or member.islnk():
                    link_path = PurePosixPath(member.linkname)
                    if link_path.is_absolute() or ".." in link_path.parts:
                        raise BackupError(
                            f"文件卷归档包含不安全链接：{member.name} -> "
                            f"{member.linkname}"
                        )
                entries += 1
                files += int(member.isfile())
    except (tarfile.TarError, OSError) as error:
        raise BackupError(f"文件卷归档校验失败：{error}") from error
    if entries == 0:
        raise BackupError("文件卷归档不包含任何条目")
    return entries, files


def prune_completed_backups(destination: Path, retention_count: int) -> list[str]:
    if retention_count == 0:
        return []
    completed = sorted(
        (
            item
            for item in destination.iterdir()
            if item.is_dir()
            and not item.is_symlink()
            and BACKUP_NAME_PATTERN.fullmatch(item.name)
            and (item / "READY").is_file()
        ),
        key=lambda item: item.name,
        reverse=True,
    )
    pruned = []
    for item in completed[retention_count:]:
        resolved = item.resolve()
        if (
            resolved.parent != destination.resolve()
            or not BACKUP_NAME_PATTERN.fullmatch(item.name)
        ):
            raise BackupError(f"拒绝清理非标准备份目录：{item}")
        shutil.rmtree(resolved)
        pruned.append(item.name)
    return pruned
