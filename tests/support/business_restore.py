"""将完整备份恢复到测试生成的独立空环境。"""

from pathlib import Path
from typing import TYPE_CHECKING

from scripts.backup.database import _restore_database
from scripts.backup.manifest import read_manifest, verify_image
from scripts.backup.resources import (
    container_resource_context,
    extract_resource_archive,
)
from scripts.backup.restore_checks import check_empty_target, check_restored_target
from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.backup.services import resolve_container_image

if TYPE_CHECKING:
    from tests.support.business_docker import BusinessDockerFixture


def restore_business_backup(
    source: "BusinessDockerFixture",
    target: "BusinessDockerFixture",
    directory: Path,
) -> None:
    if (
        not target.restore_target
        or source.project == target.project
        or source.volume == target.volume
    ):
        raise BackupError("恢复目标必须是不同项目的独立空环境")
    manifest = read_manifest(directory)
    if (
        manifest.source_project != source.project
        or manifest.source_volume != source.volume
    ):
        raise BackupError("完整备份标记或来源不匹配")
    runner = SubprocessRunner()
    container = target.compose("ps", "--all", "--quiet", "api")
    image = verify_image(manifest, runner, resolve_container_image(runner, container))
    context = container_resource_context(runner, container, image)
    if context.root != manifest.storage_root:
        raise BackupError("恢复目标存储目录与备份不匹配")
    check_empty_target(target.config, runner, target.volume, image)
    _restore_database(
        target.config, runner, directory / "database.dump", "delivery_note"
    )
    extract_resource_archive(
        target.config, runner, image, directory / "delivery_data.tar.gz", target.volume
    )
    check_restored_target(target.config, runner, manifest, context, target.volume)
