from __future__ import annotations

import re
from typing import Callable, TypedDict

from scripts.backup.runtime import BackupConfig, BackupError, Runner, compose


class Environment(TypedDict):
    running_services: list[str]
    active_jobs: int
    data_volume: str
    api_image: str
    service_containers: dict[str, str]


DOCKER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


WORKER_SERVICES = ("worker", "purchase-sync-worker", "inbound-sync-worker")


RESUMED_SERVICES = ("api", *WORKER_SERVICES, "web")


REQUIRED_SERVICES = frozenset({"db", "api", "web", *WORKER_SERVICES})


API_READINESS_PROBE = """\
import time
import urllib.request

deadline = time.monotonic() + {timeout}
while True:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/health", timeout=5
        ) as response:
            if response.status == 200:
                break
    except Exception:
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)
"""


def _running_services(config: BackupConfig, runner: Runner) -> set[str]:
    output = runner.run(compose(config, "ps", "--status", "running", "--services"))
    return {line.strip() for line in output.splitlines() if line.strip()}


def active_job_count(config: BackupConfig, runner: Runner) -> int:
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
    output = runner.run(compose(config, "images", "--quiet", service))
    return _single_output_line(output, f"{service} 镜像")


def _resolve_service_containers(
    config: BackupConfig,
    runner: Runner,
) -> dict[str, str]:
    containers = {}
    for service in RESUMED_SERVICES:
        output = runner.run(compose(config, "ps", "--quiet", service))
        containers[service] = _single_output_line(output, f"{service} 容器")
    return containers


def inspect_environment(config: BackupConfig, runner: Runner) -> Environment:
    config.validate()
    runner.run(compose(config, "config", "--quiet"))
    running = _running_services(config, runner)
    missing = sorted(REQUIRED_SERVICES - running)
    if missing:
        raise BackupError(f"以下服务未运行，拒绝开始备份：{', '.join(missing)}")
    runner.run(
        compose(
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
        "active_jobs": active_job_count(config, runner),
        "data_volume": _resolve_volume(config, runner),
        "api_image": _resolve_image(config, runner, "api"),
        "service_containers": _resolve_service_containers(config, runner),
    }


def wait_for_jobs_to_drain(
    config: BackupConfig,
    runner: Runner,
    *,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> None:
    deadline = monotonic() + config.job_drain_timeout_seconds
    while True:
        active_jobs = active_job_count(config, runner)
        if active_jobs == 0:
            return
        if monotonic() >= deadline:
            raise BackupError(f"等待活动任务排空超时，仍有 {active_jobs} 个任务")
        sleep(config.job_poll_seconds)


def resume_services(
    config: BackupConfig,
    runner: Runner,
    service_containers: dict[str, str],
) -> None:
    missing_containers = [
        service for service in RESUMED_SERVICES if service not in service_containers
    ]
    if missing_containers:
        raise BackupError(
            "缺少维护前容器标识：" + ", ".join(missing_containers)
        )
    container_ids = [
        service_containers[service] for service in RESUMED_SERVICES
    ]
    # 直接启动维护前解析出的容器，避免新版 Compose 的依赖图或尚未构建镜像
    # 阻断旧生产版本在备份窗口后的恢复。
    runner.run(
        ["docker", "start", *container_ids],
        timeout_seconds=config.service_wait_timeout_seconds + 60,
    )
    runner.run(
        [
            "docker",
            "exec",
            service_containers["api"],
            "python",
            "-c",
            API_READINESS_PROBE.format(
                timeout=config.service_wait_timeout_seconds
            ),
        ],
        timeout_seconds=config.service_wait_timeout_seconds + 10,
    )
    missing = sorted(REQUIRED_SERVICES - _running_services(config, runner))
    if missing:
        raise BackupError(f"备份后服务未全部恢复：{', '.join(missing)}")
