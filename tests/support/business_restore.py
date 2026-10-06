"""将完整备份恢复到测试生成的独立空环境。"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.backup.archive import sha256, validate_data_archive
from scripts.backup.database import _restore_database, critical_table_counts
from scripts.backup.runtime import BackupError, SubprocessRunner

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
    metadata = json.loads((directory / "BACKUP-METADATA.json").read_text())
    if (
        not (directory / "READY").is_file()
        or metadata["status"] != "complete"
        or metadata["compose_project"] != source.project
        or metadata["data_volume"] != source.volume
    ):
        raise BackupError("完整备份标记或来源不匹配")
    checksums = ""
    for key, name in (
        ("database", "database.dump"),
        ("data_archive", "delivery_data.tar.gz"),
    ):
        path = directory / name
        entry = metadata[key]
        digest = sha256(path)
        if (
            entry["filename"] != name
            or entry["bytes"] != path.stat().st_size
            or entry["sha256"] != digest
        ):
            raise BackupError(f"备份校验和或大小不一致：{name}")
        checksums += f"{digest}  {name}\n"
    if (directory / "SHA256SUMS").read_text() != checksums:
        raise BackupError("备份校验和清单不一致")
    validate_data_archive(directory / "delivery_data.tar.gz")
    if target.database_query(
        "SELECT datname FROM pg_database WHERE datname='delivery_note'", "postgres"
    ):
        raise BackupError("恢复目标数据库必须为空")
    runner = SubprocessRunner()
    _restore_database(
        target.config, runner, directory / "database.dump", "delivery_note"
    )
    with (directory / "delivery_data.tar.gz").open("rb") as archive:
        runner.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--volume",
                f"{target.volume}:/target",
                target.api_image,
                "tar",
                "-xzf",
                "-",
                "-C",
                "/target",
            ],
            stdin=archive,
        )
    if (
        critical_table_counts(target.config, runner, "delivery_note")
        != metadata["database"]["source_row_counts"]
    ):
        raise BackupError("恢复目标关键表行数不一致")
