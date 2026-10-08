"""在任务排空后选择性发布后端，失败时恢复原镜像与入口。"""

from dataclasses import dataclass
import json
import time
from typing import Any, Callable

from scripts.backup.runtime import BackupError, Runner, compose, exclusive_lock
from scripts.backup.services import (
    WORKER_SERVICES,
    active_job_count,
    resume_services,
    wait_for_api,
    wait_for_jobs_to_drain,
)
from scripts.deployment_sources import (
    BACKEND_SERVICES,
    verify_backend_image,
    verify_schema_unchanged,
)
from scripts.deployment_verification import service_snapshot, verify_deployment
from scripts.release_common import (
    ReleaseConfig,
    previous_config,
    retain_images,
    update_services,
    verify_release_inputs,
    verify_unchanged,
)


@dataclass(frozen=True)
class BackendReleaseConfig(ReleaseConfig):
    services: tuple[str, ...] = ()
    job_drain_timeout_seconds: int = 1800
    job_poll_seconds: int = 5
    stop_timeout_seconds: int = 60


def selected_services(config: BackendReleaseConfig) -> tuple[str, ...]:
    selected = set(config.services)
    if (
        not selected
        or selected - BACKEND_SERVICES
        or len(selected) != len(config.services)
    ):
        raise BackupError("必须选择不重复的 API 或 Worker 服务")
    if selected & config.retained.keys():
        raise BackupError("更新服务不能同时声明为保留版本")
    if (
        min(
            config.job_drain_timeout_seconds,
            config.job_poll_seconds,
            config.stop_timeout_seconds,
        )
        <= 0
    ):
        raise BackupError("排空、轮询和停止时间必须为正数")
    # Worker 先切换，API 最后启动；入口在全部核验就绪后恢复。
    return tuple(name for name in (*WORKER_SERVICES, "api") if name in selected)


def preflight(
    config: BackendReleaseConfig, services: tuple[str, ...], runner: Runner
) -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], BackendReleaseConfig, dict[str, object]
]:
    candidate = verify_release_inputs(config, runner)
    before = service_snapshot(config, runner)
    previous = previous_config(config, before, services, runner)
    deployment = verify_deployment(previous, runner, records=before)
    verify_backend_image(config.root, candidate["Id"], config.revision, runner)
    revisions = {
        previous.retained.get(name, config.revision) for name in BACKEND_SERVICES
    }
    for revision in revisions:
        verify_schema_unchanged(config.root, revision, config.revision, runner)
    for service in services:
        target = before[service]["Config"]["Image"]
        if any(
            record["Config"]["Image"] == target
            for name, record in before.items()
            if name != service
        ):
            raise BackupError(f"服务镜像标签共用，无法独立发布：{service}")
    if "api" in services:
        document = json.loads(runner.run(compose(config, "config", "--format", "json")))
        automatic = (
            document["services"]["api"]
            .get("environment", {})
            .get("AUTO_MIGRATE_SCHEMA")
        )
        if str(automatic).lower() != "false":
            raise BackupError("API 发布必须关闭自动迁移，本入口不执行数据库结构升级")
    return candidate, before, previous, deployment


def restore_entry(
    config: BackendReleaseConfig, before: dict[str, dict[str, Any]], runner: Runner
) -> None:
    if "api" in config.services:
        api_id = runner.run(compose(config, "ps", "--quiet", "api")).strip()
    else:
        api_id = before["api"]["Id"]
        runner.run(
            ["docker", "start", api_id], timeout_seconds=config.wait_seconds + 60
        )
    wait_for_api(config, runner, api_id)
    runner.run(
        ["docker", "start", before["web"]["Id"]],
        timeout_seconds=config.wait_seconds + 60,
    )


def replace_images(
    config: BackendReleaseConfig,
    before: dict[str, dict[str, Any]],
    images: dict[str, str],
    runner: Runner,
) -> None:
    for service, image in images.items():
        runner.run(
            ["docker", "image", "tag", image, before[service]["Config"]["Image"]]
        )
        update_services(config, runner, (service,))


def verify_updated_images(
    records: dict[str, dict[str, Any]], images: dict[str, str]
) -> None:
    for service, image in images.items():
        if records[service]["Image"] != image:
            raise BackupError(f"发布或回退后的镜像不匹配：{service}")


def publish_backend(
    config: BackendReleaseConfig,
    *,
    runner: Runner,
    check_only: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    services = selected_services(config)
    with exclusive_lock(config.lock_file):
        candidate, before, previous, deployment = preflight(config, services, runner)
        active_jobs = active_job_count(config, runner)
        if check_only:
            return {
                "status": "ready",
                "revision": config.revision,
                "planned_services": list(services),
                "active_jobs": active_jobs,
                "candidate_image": candidate["Id"],
                "deployment": deployment,
            }
        changed_images = False
        original_images = {name: before[name]["Image"] for name in services}
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
            wait_for_jobs_to_drain(config, runner, sleep=sleep, monotonic=monotonic)
            workers = tuple(name for name in services if name in WORKER_SERVICES)
            if workers:
                runner.run(
                    compose(
                        config,
                        "stop",
                        "--timeout",
                        str(config.stop_timeout_seconds),
                        *workers,
                    ),
                    timeout_seconds=config.stop_timeout_seconds + 60,
                )
            if active_job_count(config, runner) != 0:
                raise BackupError("Worker 停止后仍存在活动任务")
            rollback_images = retain_images(config, before, services, runner)
            changed_images = True
            updated_images = {name: candidate["Id"] for name in services}
            replace_images(config, before, updated_images, runner)
            restore_entry(config, before, runner)
            after = service_snapshot(config, runner)
            verify_unchanged(before, after, set(services))
            verify_updated_images(after, updated_images)
            deployment = verify_deployment(config, runner, records=after)
        except Exception as failure:
            try:
                if changed_images:
                    replace_images(config, before, original_images, runner)
                    restore_entry(config, before, runner)
                else:
                    resume_services(
                        config,
                        runner,
                        {name: record["Id"] for name, record in before.items()},
                    )
                recovered = service_snapshot(config, runner)
                verify_unchanged(
                    before, recovered, set(services) if changed_images else set()
                )
                verify_updated_images(recovered, original_images)
                verify_deployment(previous, runner, records=recovered)
            except Exception as recovery:
                raise BackupError(
                    f"发布失败且回退未通过：{failure}; {recovery}"
                ) from recovery
            raise BackupError(f"发布失败，已恢复原镜像并验收：{failure}") from failure
        return {
            "status": "complete",
            "revision": config.revision,
            "updated_services": list(services),
            "active_jobs_before_maintenance": active_jobs,
            "rollback_images": rollback_images,
            "deployment": deployment,
        }
