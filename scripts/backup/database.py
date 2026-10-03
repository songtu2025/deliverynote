from __future__ import annotations

import re
import secrets
from pathlib import Path

from scripts.backup.runtime import BackupConfig, BackupError, Runner, compose


RESTORE_DATABASE_PATTERN = re.compile(r"^delivery_note_restore_[0-9a-f]{16}$")


CRITICAL_TABLES = ("users", "input_versions", "batches", "batch_files", "jobs")


CRITICAL_TABLE_COUNTS_SQL = "\nUNION ALL\n".join(
    f"SELECT '{table}', count(*) FROM public.{table}" for table in CRITICAL_TABLES
)


def critical_table_counts(
    config: BackupConfig,
    runner: Runner,
    database_name: str,
) -> dict[str, int]:
    if database_name != "delivery_note" and not RESTORE_DATABASE_PATTERN.fullmatch(
        database_name
    ):
        raise BackupError("临时恢复数据库名称不安全")
    output = runner.run(
        compose(
            config,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "delivery_note",
            "-d",
            database_name,
            "-Atq",
            "-F",
            "=",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            CRITICAL_TABLE_COUNTS_SQL,
        )
    )
    counts: dict[str, int] = {}
    try:
        for line in output.splitlines():
            table, value = line.strip().split("=", 1)
            if table not in CRITICAL_TABLES or table in counts:
                raise ValueError
            count = int(value)
            if count < 0:
                raise ValueError
            counts[table] = count
    except ValueError as error:
        raise BackupError("无法解析关键表行数") from error
    if set(counts) != set(CRITICAL_TABLES):
        missing = ", ".join(sorted(set(CRITICAL_TABLES) - set(counts)))
        raise BackupError(f"关键表计数输出不完整：{missing}")
    return counts


def create_database_dump(
    config: BackupConfig,
    runner: Runner,
    target: Path,
) -> None:
    with target.open("xb") as output:
        runner.run(
            compose(
                config,
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                "delivery_note",
                "-d",
                "delivery_note",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
            ),
            stdout=output,
            timeout_seconds=config.snapshot_timeout_seconds,
        )
    target.chmod(0o600)
    if target.stat().st_size == 0:
        raise BackupError("数据库备份为空")


def _temporary_restore_database_name() -> str:
    database_name = f"delivery_note_restore_{secrets.token_hex(8)}"
    if not RESTORE_DATABASE_PATTERN.fullmatch(database_name):
        raise BackupError("生成的临时恢复数据库名称不安全")
    return database_name


def validate_database_restore(
    config: BackupConfig,
    runner: Runner,
    *,
    database_path: Path,
    source_counts: dict[str, int],
) -> dict[str, int]:
    database_name = _temporary_restore_database_name()
    primary_error: Exception | None = None
    restored_counts: dict[str, int] = {}
    try:
        runner.run(
            compose(
                config,
                "exec",
                "-T",
                "db",
                "createdb",
                "-U",
                "delivery_note",
                "--maintenance-db=postgres",
                "--owner=delivery_note",
                database_name,
            )
        )
        with database_path.open("rb") as source:
            runner.run(
                compose(
                    config,
                    "exec",
                    "-T",
                    "db",
                    "pg_restore",
                    "-U",
                    "delivery_note",
                    "-d",
                    database_name,
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                ),
                stdin=source,
                timeout_seconds=config.snapshot_timeout_seconds,
            )
        restored_counts = critical_table_counts(config, runner, database_name)
        if restored_counts != source_counts:
            differences = ", ".join(
                f"{table}: 源库={source_counts[table]}, 恢复库={restored_counts[table]}"
                for table in CRITICAL_TABLES
                if source_counts[table] != restored_counts[table]
            )
            raise BackupError(f"恢复库关键表行数与快照不一致：{differences}")
    except Exception as error:
        primary_error = error
    finally:
        try:
            runner.run(
                compose(
                    config,
                    "exec",
                    "-T",
                    "db",
                    "dropdb",
                    "-U",
                    "delivery_note",
                    "--maintenance-db=postgres",
                    "--if-exists",
                    "--force",
                    database_name,
                )
            )
        except Exception as cleanup_error:
            if primary_error is None:
                primary_error = BackupError(f"临时恢复数据库清理失败：{cleanup_error}")
            else:
                primary_error = BackupError(
                    "数据库恢复验证失败且临时恢复数据库清理失败："
                    f"{primary_error}; {cleanup_error}"
                )
    if primary_error is not None:
        raise primary_error
    return restored_counts
