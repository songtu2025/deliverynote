from __future__ import annotations

import fcntl
import os
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol, Sequence


PROJECT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


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


def compose(config: BackupConfig, *arguments: str) -> list[str]:
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


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupError(f"已有备份任务正在运行：{path}") from error
        yield


@contextmanager
def restricted_umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)
