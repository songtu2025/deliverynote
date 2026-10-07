"""只读验证完整备份及恢复镜像，不创建数据库或文件卷。"""

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, cast

from scripts.backup.archive import sha256, validate_data_archive
from scripts.backup.database import CRITICAL_TABLES
from scripts.backup.resources import ResourceReport
from scripts.backup.runtime import BackupError, Runner
from scripts.backup.services import IMAGE_ID_PATTERN


@dataclass(frozen=True)
class BackupManifest:
    source_project: str
    source_volume: str
    image_id: str
    storage_root: str
    counts: dict[str, int]
    resources: ResourceReport


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BackupError("备份元数据格式不完整")
    return cast(dict[str, Any], value)


def _nonnegative(value: Any) -> bool:
    return type(value) is int and value >= 0


def _counts(database: dict[str, Any]) -> dict[str, int]:
    counts = _object(database["source_row_counts"])
    verification = _object(database["restore_verification"])
    restored = _object(verification.get("restored_row_counts"))
    if (
        database["format"] != "postgresql_custom"
        or set(counts) != set(CRITICAL_TABLES)
        or not all(_nonnegative(value) for value in counts.values())
        or not all(_nonnegative(value) for value in restored.values())
        or verification.get("status") != "passed"
        or restored != counts
    ):
        raise BackupError("数据库恢复证据不完整或不一致")
    return cast(dict[str, int], counts)


def _resource_entry(value: Any) -> dict[str, Any]:
    entry = _object(value)
    if entry.get("recovery_source") not in {"data_volume", "application_image"}:
        raise BackupError("资源恢复证据缺少恢复来源")
    if entry.get("validation") == "absent":
        if entry["recovery_source"] != "data_volume":
            raise BackupError("内置模板不能缺失")
        return entry
    if (
        entry.get("validation") != "passed"
        or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
        or not all(_nonnegative(entry.get(key)) for key in ("mode", "uid", "gid"))
        or entry["mode"] > 0o777
    ):
        raise BackupError("资源恢复证据缺少哈希或权限归属")
    return entry


def _resources(value: Any) -> tuple[str, ResourceReport]:
    resources = _object(value)
    source = _object(resources.get("source"))
    if (
        resources.get("status") != "passed"
        or not source
        or resources.get("restored") != source
    ):
        raise BackupError("资源恢复证据不完整或不一致")
    configs = [path for path in source if path.endswith("/config/gerpgo.json")]
    if len(configs) != 1:
        raise BackupError("资源恢复证据缺少唯一配置目录")
    root = PurePosixPath(configs[0]).parent.parent
    if not root.is_relative_to("/data") or ".." in root.parts:
        raise BackupError("资源恢复证据的存储目录不在备份卷内")
    runtime = {
        str(root / "config/gerpgo.json"),
        str(root / "cache/purchase-details-v1.json"),
    }
    if not runtime.issubset(source):
        raise BackupError("资源恢复证据缺少配置或缓存记录")
    for name, value in source.items():
        entry = _resource_entry(value)
        path = PurePosixPath(name)
        if not path.is_absolute() or ".." in path.parts:
            raise BackupError("资源恢复证据包含不安全路径")
        if (name in runtime) != (entry["recovery_source"] == "data_volume"):
            raise BackupError("资源恢复证据的路径与恢复来源不匹配")
    return str(root), cast(ResourceReport, source)


def _files(directory: Path, metadata: dict[str, Any]) -> None:
    checksums = ""
    for key, name in (
        ("database", "database.dump"),
        ("data_archive", "delivery_data.tar.gz"),
    ):
        path = directory / name
        entry = _object(metadata[key])
        digest = sha256(path)
        if (
            entry.get("filename") != name
            or not _nonnegative(entry.get("bytes"))
            or entry["bytes"] != path.stat().st_size
            or entry.get("sha256") != digest
        ):
            raise BackupError(f"备份校验和或大小不一致：{name}")
        checksums += f"{digest}  {name}\n"
    if (directory / "SHA256SUMS").read_text(encoding="utf-8") != checksums:
        raise BackupError("备份校验和清单不一致")
    entries, files = validate_data_archive(directory / "delivery_data.tar.gz")
    archive = metadata["data_archive"]
    if archive.get("entries") != entries or archive.get("files") != files:
        raise BackupError("文件归档条目数量与元数据不一致")


def read_manifest(directory: Path) -> BackupManifest:
    try:
        if not (directory / "READY").is_file() or (directory / "FAILED.txt").exists():
            raise BackupError("完整备份完成标记缺失或包含失败标记")
        metadata = _object(
            json.loads((directory / "BACKUP-METADATA.json").read_text(encoding="utf-8"))
        )
        if (
            type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != 3
        ):
            raise BackupError("恢复预检只接受包含镜像与资源证据的 schema 3 备份")
        if metadata.get("status") != "complete":
            raise BackupError("完整备份完成标记或状态不匹配")
        image = _object(metadata["application_image"]).get("id")
        if not isinstance(image, str) or not IMAGE_ID_PATTERN.fullmatch(image):
            raise BackupError("备份缺少不可变应用镜像身份")
        project, volume = metadata["compose_project"], metadata["data_volume"]
        if not all(isinstance(value, str) and value for value in (project, volume)):
            raise BackupError("备份缺少来源项目或文件卷")
        counts = _counts(_object(metadata["database"]))
        root, resources = _resources(metadata["resources"])
        _files(directory, metadata)
        return BackupManifest(project, volume, image, root, counts, resources)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise BackupError("备份元数据格式不完整或备份文件不可读取") from error


def verify_image(manifest: BackupManifest, runner: Runner, image: str) -> str:
    resolved = runner.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image]
    ).strip()
    if resolved != manifest.image_id:
        raise BackupError("恢复镜像身份不匹配，拒绝恢复")
    return resolved
