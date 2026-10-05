from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Callable

from scripts.backup.archive import (
    create_data_archive,
    prune_completed_backups,
    sha256,
    validate_data_archive,
    write_private_text,
)
from scripts.backup.database import (
    create_database_dump,
    critical_table_counts,
    validate_database_restore,
)
from scripts.backup.runtime import (
    BackupConfig,
    BackupError,
    Runner,
    SubprocessRunner,
    compose,
    exclusive_lock,
    restricted_umask,
)
from scripts.backup.services import (
    WORKER_SERVICES,
    Environment,
    active_job_count,
    inspect_environment,
    resume_services,
    wait_for_jobs_to_drain,
)


@dataclass
class Snapshot:
    directory: Path
    started_at: datetime
    source_counts: dict[str, int] = field(default_factory=dict)
    restored_counts: dict[str, int] = field(default_factory=dict)
    archive_entries: int = 0
    archive_files: int = 0

    @property
    def database_path(self) -> Path:
        return self.directory / "database.dump"

    @property
    def archive_path(self) -> Path:
        return self.directory / "delivery_data.tar.gz"


def _prepare_snapshot(config: BackupConfig, started_at: datetime) -> Snapshot:
    config.destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.destination.chmod(0o700)
    backup_name = started_at.strftime("%Y%m%d-%H%M%S")
    if (config.destination / backup_name).exists():
        raise BackupError(f"目标备份目录已存在：{config.destination / backup_name}")
    directory = Path(
        tempfile.mkdtemp(prefix=f".incomplete-{backup_name}-", dir=config.destination)
    )
    directory.chmod(0o700)
    return Snapshot(directory, started_at)


def _take_snapshot(
    config: BackupConfig,
    runner: Runner,
    environment: Environment,
    snapshot: Snapshot,
    wait: Callable[[], None],
) -> None:
    primary_error: Exception | None = None
    try:
        runner.run(
            compose(
                config,
                "stop",
                "--timeout",
                str(config.stop_timeout_seconds),
                "web",
                "api",
            ),
            timeout_seconds=config.stop_timeout_seconds + 60,
        )
        wait()
        runner.run(
            compose(
                config,
                "stop",
                "--timeout",
                str(config.stop_timeout_seconds),
                *WORKER_SERVICES,
            ),
            timeout_seconds=config.stop_timeout_seconds + 60,
        )
        if active_job_count(config, runner) != 0:
            raise BackupError("Worker 停止后仍存在活动任务")
        snapshot.source_counts = critical_table_counts(config, runner, "delivery_note")
        create_database_dump(config, runner, snapshot.database_path)
        create_data_archive(
            runner,
            api_image=environment["api_image"],
            data_volume=environment["data_volume"],
            backup_directory=snapshot.directory,
            timeout_seconds=config.snapshot_timeout_seconds,
        )
    except Exception as error:
        primary_error = error
    finally:
        try:
            resume_services(
                config,
                runner,
                environment["service_containers"],
                health_url=environment["health_url"],
            )
        except Exception as resume_error:
            if primary_error is None:
                primary_error = resume_error
            else:
                primary_error = BackupError(
                    f"备份失败且服务恢复失败：{primary_error}; {resume_error}"
                )
    if primary_error is not None:
        raise primary_error


def _verify_snapshot(config: BackupConfig, runner: Runner, snapshot: Snapshot) -> None:
    snapshot.restored_counts = validate_database_restore(
        config,
        runner,
        database_path=snapshot.database_path,
        source_counts=snapshot.source_counts,
    )
    snapshot.archive_entries, snapshot.archive_files = validate_data_archive(
        snapshot.archive_path
    )


def _complete_backup(
    config: BackupConfig,
    environment: Environment,
    snapshot: Snapshot,
    completed_at: datetime,
) -> dict[str, object]:
    database_path = snapshot.database_path
    archive_path = snapshot.archive_path
    database_sha256 = sha256(database_path)
    archive_sha256 = sha256(archive_path)
    metadata = {
        "schema_version": 2,
        "status": "complete",
        "created_at": snapshot.started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "compose_project": config.project_name,
        "active_jobs_before_maintenance": environment["active_jobs"],
        "data_volume": environment["data_volume"],
        "database": {
            "filename": database_path.name,
            "format": "postgresql_custom",
            "bytes": database_path.stat().st_size,
            "sha256": database_sha256,
            "source_row_counts": snapshot.source_counts,
            "restore_verification": {
                "status": "passed",
                "restored_row_counts": snapshot.restored_counts,
            },
        },
        "data_archive": {
            "filename": archive_path.name,
            "bytes": archive_path.stat().st_size,
            "sha256": archive_sha256,
            "entries": snapshot.archive_entries,
            "files": snapshot.archive_files,
        },
    }
    write_private_text(
        snapshot.directory / "BACKUP-METADATA.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )
    write_private_text(
        snapshot.directory / "SHA256SUMS",
        f"{database_sha256}  database.dump\n{archive_sha256}  delivery_data.tar.gz\n",
    )
    write_private_text(snapshot.directory / "READY", f"{completed_at.isoformat()}\n")
    database_bytes = database_path.stat().st_size
    data_archive_bytes = archive_path.stat().st_size
    final_directory = config.destination / snapshot.started_at.strftime("%Y%m%d-%H%M%S")
    snapshot.directory.replace(final_directory)
    pruned = prune_completed_backups(config.destination, config.retention_count)
    return {
        "status": "complete",
        "backup_directory": str(final_directory),
        "database_bytes": database_bytes,
        "database_restore_verified": True,
        "data_archive_bytes": data_archive_bytes,
        "data_archive_files": snapshot.archive_files,
        "pruned_backups": pruned,
    }


def create_backup(
    config: BackupConfig,
    *,
    runner: Runner | None = None,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    runner = runner or SubprocessRunner()
    now = now or (lambda: datetime.now().astimezone())
    config.validate()
    with restricted_umask(0o077), exclusive_lock(config.lock_file):
        environment = inspect_environment(config, runner)
        snapshot = _prepare_snapshot(config, now())
        try:
            _take_snapshot(
                config,
                runner,
                environment,
                snapshot,
                partial(
                    wait_for_jobs_to_drain,
                    config,
                    runner,
                    sleep=sleep,
                    monotonic=monotonic,
                ),
            )
            _verify_snapshot(config, runner, snapshot)
        except Exception as error:
            write_private_text(
                snapshot.directory / "FAILED.txt",
                f"failed_at={now().isoformat()}\nerror={error}\n",
            )
            raise
        return _complete_backup(config, environment, snapshot, now())
