"""检查隔离恢复目标和恢复后的实际结果，不启动应用或执行迁移。"""

from scripts.backup.database import critical_table_counts
from scripts.backup.manifest import BackupManifest
from scripts.backup.resources import (
    ResourceContext,
    probe_resources,
    resource_references,
)
from scripts.backup.runtime import BackupConfig, BackupError, Runner, compose


def check_empty_target(
    config: BackupConfig, runner: Runner, volume: str, image: str
) -> None:
    running = runner.run(compose(config, "ps", "--status", "running", "--services"))
    if set(running.split()) != {"db"}:
        raise BackupError("恢复目标只能运行独立数据库，业务服务必须停止")
    existing = runner.run(
        compose(
            config,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "delivery_note",
            "-d",
            "postgres",
            "-Atq",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT datname FROM pg_database WHERE datname='delivery_note'",
        )
    )
    if existing.strip():
        raise BackupError("恢复目标数据库必须为空")
    # 先确认卷存在，避免只读挂载隐式创建未存在的卷。
    actual = runner.run(
        ["docker", "volume", "inspect", "--format", "{{.Name}}", volume]
    )
    if actual.strip() != volume:
        raise BackupError("无法确认恢复目标文件卷")
    contents = runner.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--network",
            "none",
            "--read-only",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--mount",
            f"type=volume,source={volume},target=/target,readonly",
            image,
            "python",
            "-c",
            "from pathlib import Path; "
            "print('nonempty' if any(Path('/target').iterdir()) else 'empty')",
        ]
    )
    if contents.strip() != "empty":
        raise BackupError("恢复目标文件卷必须为空")


def check_restored_target(
    config: BackupConfig,
    runner: Runner,
    manifest: BackupManifest,
    context: ResourceContext,
    volume: str,
) -> None:
    if critical_table_counts(config, runner, "delivery_note") != manifest.counts:
        raise BackupError("恢复目标关键表行数不一致")
    references = resource_references(config, runner, "delivery_note")
    restored = probe_resources(config, runner, context, volume, references)
    if restored != manifest.resources:
        raise BackupError("恢复目标运行资源与备份证据不一致，拒绝启动服务")
