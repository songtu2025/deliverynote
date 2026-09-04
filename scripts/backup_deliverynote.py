from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Iterator, Protocol, Sequence


BACKUP_NAME_PATTERN = re.compile(r"^\d{8}-\d{6}$")
PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DOCKER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
RESTORE_DATABASE_PATTERN = re.compile(
    r"^delivery_note_restore_[0-9a-f]{16}$"
)
CRITICAL_TABLES = ("users", "input_versions", "batches", "batch_files", "jobs")
CRITICAL_TABLE_COUNTS_SQL = "\nUNION ALL\n".join(
    f"SELECT '{table}', count(*) FROM public.{table}" for table in CRITICAL_TABLES
)
WORKER_SERVICES = ("worker", "purchase-sync-worker", "inbound-sync-worker")
REQUIRED_SERVICES = frozenset({"db", "api", "web", *WORKER_SERVICES})


class BackupError(RuntimeError):
    pass


class Runner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        timeout_seconds: int = 300,
    ) -> str: ...


class SubprocessRunner:
    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        timeout_seconds: int = 300,
    ) -> str:
        try:
            completed = subprocess.run(
                list(arguments),
                check=False,
                stdin=stdin,
                stdout=stdout if stdout is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=stdout is None,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise BackupError(
                f"命令执行超过 {timeout_seconds} 秒：{' '.join(arguments)}"
            ) from error
        if completed.returncode != 0:
            stderr = completed.stderr
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            detail = (stderr or "命令执行失败").strip()
            raise BackupError(
                f"命令失败（{completed.returncode}）：{' '.join(arguments)}\n{detail}"
            )
        return "" if stdout is not None else str(completed.stdout or "")


@dataclass(frozen=True)
class BackupConfig:
    compose_file: Path
    env_file: Path
    project_name: str
    destination: Path
    lock_file: Path
    stop_timeout_seconds: int = 60
    job_drain_timeout_seconds: int = 1800
    job_poll_seconds: int = 5
    service_wait_timeout_seconds: int = 120
    snapshot_timeout_seconds: int = 3600
    retention_count: int = 0

    def validate(self) -> None:
        if not self.compose_file.is_file():
            raise BackupError(f"Compose 文件不存在：{self.compose_file}")
        if not self.env_file.is_file():
            raise BackupError(f"环境文件不存在：{self.env_file}")
        if not PROJECT_NAME_PATTERN.fullmatch(self.project_name):
            raise BackupError("Compose 项目名只能包含小写字母、数字、下划线和连字符")
        if self.destination.resolve() == Path("/"):
            raise BackupError("备份目标不能是文件系统根目录")
        for value, label in (
            (self.stop_timeout_seconds, "停止超时"),
            (self.job_drain_timeout_seconds, "任务排空超时"),
            (self.job_poll_seconds, "任务轮询间隔"),
            (self.service_wait_timeout_seconds, "服务恢复超时"),
            (self.snapshot_timeout_seconds, "快照命令超时"),
        ):
            if value <= 0:
                raise BackupError(f"{label}必须大于 0")
        if self.retention_count < 0:
            raise BackupError("保留数量不能小于 0")


def _compose(config: BackupConfig, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--file",
        str(config.compose_file),
        "--env-file",
        str(config.env_file),
        "--project-name",
        config.project_name,
        *arguments,
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_private_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupError(f"已有备份任务正在运行：{path}") from error
        yield


@contextmanager
def _restricted_umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


def _running_services(config: BackupConfig, runner: Runner) -> set[str]:
    output = runner.run(_compose(config, "ps", "--status", "running", "--services"))
    return {line.strip() for line in output.splitlines() if line.strip()}


def _active_job_count(config: BackupConfig, runner: Runner) -> int:
    output = runner.run(
        _compose(
            config,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "delivery_note",
            "-d",
            "delivery_note",
            "-Atq",
            "-c",
            "SELECT count(*) FROM jobs WHERE status IN ('queued','running');",
        )
    ).strip()
    try:
        return int(output)
    except ValueError as error:
        raise BackupError(f"无法解析活动任务数量：{output!r}") from error


def _critical_table_counts(
    config: BackupConfig,
    runner: Runner,
    database_name: str,
) -> dict[str, int]:
    if database_name != "delivery_note" and not RESTORE_DATABASE_PATTERN.fullmatch(
        database_name
    ):
        raise BackupError("临时恢复数据库名称不安全")
    output = runner.run(
        _compose(
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


def _single_output_line(output: str, label: str) -> str:
    values = [line.strip() for line in output.splitlines() if line.strip()]
    if len(values) != 1 or not DOCKER_NAME_PATTERN.fullmatch(values[0]):
        raise BackupError(f"无法唯一确定{label}：{values}")
    return values[0]


def _resolve_volume(config: BackupConfig, runner: Runner) -> str:
    output = runner.run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={config.project_name}",
            "--filter",
            "label=com.docker.compose.volume=delivery_data",
        ]
    )
    return _single_output_line(output, "delivery_data 卷")


def _resolve_image(config: BackupConfig, runner: Runner, service: str) -> str:
    output = runner.run(_compose(config, "images", "--quiet", service))
    return _single_output_line(output, f"{service} 镜像")


def inspect_environment(config: BackupConfig, runner: Runner) -> dict:
    config.validate()
    runner.run(_compose(config, "config", "--quiet"))
    running = _running_services(config, runner)
    missing = sorted(REQUIRED_SERVICES - running)
    if missing:
        raise BackupError(f"以下服务未运行，拒绝开始备份：{', '.join(missing)}")
    runner.run(
        _compose(
            config,
            "exec",
            "-T",
            "db",
            "pg_isready",
            "-U",
            "delivery_note",
            "-d",
            "delivery_note",
        )
    )
    return {
        "running_services": sorted(running),
        "active_jobs": _active_job_count(config, runner),
        "data_volume": _resolve_volume(config, runner),
        "api_image": _resolve_image(config, runner, "api"),
    }


def _wait_for_jobs_to_drain(
    config: BackupConfig,
    runner: Runner,
    *,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> None:
    deadline = monotonic() + config.job_drain_timeout_seconds
    while True:
        active_jobs = _active_job_count(config, runner)
        if active_jobs == 0:
            return
        if monotonic() >= deadline:
            raise BackupError(f"等待活动任务排空超时，仍有 {active_jobs} 个任务")
        sleep(config.job_poll_seconds)


def _create_database_dump(
    config: BackupConfig,
    runner: Runner,
    target: Path,
) -> None:
    with target.open("xb") as output:
        runner.run(
            _compose(
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


def _create_data_archive(
    runner: Runner,
    *,
    api_image: str,
    data_volume: str,
    backup_directory: Path,
    timeout_seconds: int,
) -> Path:
    runner.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--volume",
            f"{data_volume}:/source:ro",
            "--volume",
            f"{backup_directory.resolve()}:/backup",
            api_image,
            "tar",
            "--numeric-owner",
            "-czf",
            "/backup/delivery_data.tar.gz",
            "-C",
            "/source",
            ".",
        ],
        timeout_seconds=timeout_seconds,
    )
    target = backup_directory / "delivery_data.tar.gz"
    if not target.is_file() or target.stat().st_size == 0:
        raise BackupError("文件卷备份为空或未生成")
    target.chmod(0o600)
    return target


def _temporary_restore_database_name() -> str:
    database_name = f"delivery_note_restore_{secrets.token_hex(8)}"
    if not RESTORE_DATABASE_PATTERN.fullmatch(database_name):
        raise BackupError("生成的临时恢复数据库名称不安全")
    return database_name


def _validate_database_restore(
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
            _compose(
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
                _compose(
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
        restored_counts = _critical_table_counts(config, runner, database_name)
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
                _compose(
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
                primary_error = BackupError(
                    f"临时恢复数据库清理失败：{cleanup_error}"
                )
            else:
                primary_error = BackupError(
                    "数据库恢复验证失败且临时恢复数据库清理失败："
                    f"{primary_error}; {cleanup_error}"
                )
    if primary_error is not None:
        raise primary_error
    return restored_counts


def _validate_data_archive(path: Path) -> tuple[int, int]:
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


def _resume_services(config: BackupConfig, runner: Runner) -> None:
    runner.run(
        _compose(
            config,
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(config.service_wait_timeout_seconds),
            "api",
            *WORKER_SERVICES,
            "web",
        ),
        timeout_seconds=config.service_wait_timeout_seconds + 60,
    )
    missing = sorted(REQUIRED_SERVICES - _running_services(config, runner))
    if missing:
        raise BackupError(f"备份后服务未全部恢复：{', '.join(missing)}")


def _prune_completed_backups(destination: Path, retention_count: int) -> list[str]:
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


def create_backup(
    config: BackupConfig,
    *,
    runner: Runner | None = None,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    runner = runner or SubprocessRunner()
    now = now or (lambda: datetime.now().astimezone())
    config.validate()

    with _restricted_umask(0o077), _exclusive_lock(config.lock_file):
        environment = inspect_environment(config, runner)
        config.destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.destination.chmod(0o700)

        started_at = now()
        backup_name = started_at.strftime("%Y%m%d-%H%M%S")
        final_directory = config.destination / backup_name
        if final_directory.exists():
            raise BackupError(f"目标备份目录已存在：{final_directory}")
        temporary_directory = Path(
            tempfile.mkdtemp(
                prefix=f".incomplete-{backup_name}-", dir=config.destination
            )
        )
        temporary_directory.chmod(0o700)
        maintenance_started = False
        primary_error: Exception | None = None
        database_path = temporary_directory / "database.dump"
        archive_path = temporary_directory / "delivery_data.tar.gz"
        source_counts: dict[str, int] = {}
        restored_counts: dict[str, int] = {}
        archive_entries = 0
        archive_files = 0

        try:
            maintenance_started = True
            runner.run(
                _compose(
                    config,
                    "stop",
                    "--timeout",
                    str(config.stop_timeout_seconds),
                    "web",
                    "api",
                ),
                timeout_seconds=config.stop_timeout_seconds + 60,
            )
            _wait_for_jobs_to_drain(
                config,
                runner,
                sleep=sleep,
                monotonic=monotonic,
            )
            runner.run(
                _compose(
                    config,
                    "stop",
                    "--timeout",
                    str(config.stop_timeout_seconds),
                    *WORKER_SERVICES,
                ),
                timeout_seconds=config.stop_timeout_seconds + 60,
            )
            if _active_job_count(config, runner) != 0:
                raise BackupError("Worker 停止后仍存在活动任务")

            source_counts = _critical_table_counts(
                config,
                runner,
                "delivery_note",
            )
            _create_database_dump(config, runner, database_path)
            _create_data_archive(
                runner,
                api_image=environment["api_image"],
                data_volume=environment["data_volume"],
                backup_directory=temporary_directory,
                timeout_seconds=config.snapshot_timeout_seconds,
            )
        except Exception as error:
            primary_error = error
        finally:
            if maintenance_started:
                try:
                    _resume_services(config, runner)
                except Exception as resume_error:
                    if primary_error is None:
                        primary_error = resume_error
                    else:
                        primary_error = BackupError(
                            f"备份失败且服务恢复失败：{primary_error}; {resume_error}"
                        )

        if primary_error is None:
            try:
                restored_counts = _validate_database_restore(
                    config,
                    runner,
                    database_path=database_path,
                    source_counts=source_counts,
                )
                archive_entries, archive_files = _validate_data_archive(archive_path)
            except Exception as error:
                primary_error = error

        if primary_error is not None:
            _write_private_text(
                temporary_directory / "FAILED.txt",
                f"failed_at={now().isoformat()}\nerror={primary_error}\n",
            )
            raise primary_error

        completed_at = now()
        database_sha256 = _sha256(database_path)
        archive_sha256 = _sha256(archive_path)
        metadata = {
            "schema_version": 2,
            "status": "complete",
            "created_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "compose_project": config.project_name,
            "active_jobs_before_maintenance": environment["active_jobs"],
            "data_volume": environment["data_volume"],
            "database": {
                "filename": database_path.name,
                "format": "postgresql_custom",
                "bytes": database_path.stat().st_size,
                "sha256": database_sha256,
                "source_row_counts": source_counts,
                "restore_verification": {
                    "status": "passed",
                    "restored_row_counts": restored_counts,
                },
            },
            "data_archive": {
                "filename": archive_path.name,
                "bytes": archive_path.stat().st_size,
                "sha256": archive_sha256,
                "entries": archive_entries,
                "files": archive_files,
            },
        }
        _write_private_text(
            temporary_directory / "BACKUP-METADATA.json",
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )
        _write_private_text(
            temporary_directory / "SHA256SUMS",
            f"{database_sha256}  database.dump\n"
            f"{archive_sha256}  delivery_data.tar.gz\n",
        )
        _write_private_text(
            temporary_directory / "READY", f"{completed_at.isoformat()}\n"
        )
        database_bytes = database_path.stat().st_size
        data_archive_bytes = archive_path.stat().st_size
        temporary_directory.replace(final_directory)
        pruned = _prune_completed_backups(config.destination, config.retention_count)
        return {
            "status": "complete",
            "backup_directory": str(final_directory),
            "database_bytes": database_bytes,
            "database_restore_verified": True,
            "data_archive_bytes": data_archive_bytes,
            "data_archive_files": archive_files,
            "pruned_backups": pruned,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在短暂维护窗口内生成 DeliveryNote PostgreSQL 与文件卷的成对备份。"
    )
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--project-name", default="deliverynote")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path("/run/lock/deliverynote-backup.lock"),
    )
    parser.add_argument("--stop-timeout-seconds", type=int, default=60)
    parser.add_argument("--job-drain-timeout-seconds", type=int, default=1800)
    parser.add_argument("--job-poll-seconds", type=int, default=5)
    parser.add_argument("--service-wait-timeout-seconds", type=int, default=120)
    parser.add_argument("--snapshot-timeout-seconds", type=int, default=3600)
    parser.add_argument(
        "--retention-count",
        type=int,
        default=0,
        help="保留最近 N 个完整备份；0 表示不自动删除任何备份。",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只检查 Compose、服务、活动任务、卷和镜像，不停止服务或创建备份。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    config = BackupConfig(
        compose_file=arguments.compose_file.resolve(),
        env_file=arguments.env_file.resolve(),
        project_name=arguments.project_name,
        destination=arguments.destination.resolve(),
        lock_file=arguments.lock_file.resolve(),
        stop_timeout_seconds=arguments.stop_timeout_seconds,
        job_drain_timeout_seconds=arguments.job_drain_timeout_seconds,
        job_poll_seconds=arguments.job_poll_seconds,
        service_wait_timeout_seconds=arguments.service_wait_timeout_seconds,
        snapshot_timeout_seconds=arguments.snapshot_timeout_seconds,
        retention_count=arguments.retention_count,
    )
    try:
        if arguments.check_only:
            result = inspect_environment(config, SubprocessRunner())
            result["status"] = "ready"
        else:
            result = create_backup(config)
    except (BackupError, OSError) as error:
        print(f"备份失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
