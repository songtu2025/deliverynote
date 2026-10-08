"""核验六个常驻服务，明确区分目标版本与声明保留的版本。"""

import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, cast

from scripts.backup.runtime import BackupError, ComposeConfig, Runner, compose
from scripts.backup.services import REQUIRED_SERVICES
from scripts.deployment_sources import (
    BACKEND_SERVICES,
    REVISION_LABEL,
    verify_backend_source,
)
from scripts.web_verification import WebVerificationConfig, verify_served_web


class DeploymentVerificationConfig(WebVerificationConfig, Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def revision(self) -> str: ...

    @property
    def retained(self) -> Mapping[str, str]: ...


def service_snapshot(
    config: ComposeConfig, runner: Runner
) -> dict[str, dict[str, Any]]:
    services = sorted(REQUIRED_SERVICES)
    identifiers = [
        runner.run(compose(config, "ps", "--quiet", service)).strip()
        for service in services
    ]
    if any(
        not identifier or len(identifier.splitlines()) != 1
        for identifier in identifiers
    ):
        raise BackupError("核验必须具备全部六个常驻服务，且每个服务只有一个容器")
    records = cast(
        list[dict[str, Any]],
        json.loads(runner.run(["docker", "inspect", *identifiers])),
    )
    result = dict(zip(services, records, strict=True))
    for service, record in result.items():
        state = record["State"]
        if (
            state["Status"] != "running"
            or record["RestartCount"] != 0
            or state.get("Health", {}).get("Status", "healthy") != "healthy"
        ):
            raise BackupError(f"服务状态未通过验收：{service}")
    return result


def verify_source_checkout(root: Path, revision: str, runner: Runner) -> None:
    head = runner.run(["git", "-C", str(root), "rev-parse", "HEAD"]).strip()
    dirty = runner.run(["git", "-C", str(root), "status", "--porcelain"]).strip()
    if head != revision or dirty:
        raise BackupError("正式源码提交不匹配或工作区存在未提交修改")


def verify_deployment(
    config: DeploymentVerificationConfig,
    runner: Runner,
    *,
    records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, object]:
    application_services = BACKEND_SERVICES | {"web"}
    if set(config.retained) - application_services:
        raise BackupError("只能声明保留 API、Web 和三个 Worker 的版本")
    if any(
        not re.fullmatch(r"[0-9a-f]{40}", value)
        for value in (config.revision, *config.retained.values())
    ):
        raise BackupError("目标版本和保留版本必须使用完整提交 SHA")
    verify_source_checkout(config.root, config.revision, runner)
    records = records if records is not None else service_snapshot(config, runner)
    report: dict[str, object] = {}
    for service, record in records.items():
        entry: dict[str, object] = {
            "container_id": record["Id"],
            "image_id": record["Image"],
            "state": "running",
        }
        if service in application_services:
            image = json.loads(
                runner.run(["docker", "image", "inspect", record["Image"]])
            )[0]
            revision = (image["Config"].get("Labels") or {}).get(REVISION_LABEL)
            expected = config.retained.get(service, config.revision)
            if revision != expected:
                raise BackupError(
                    f"服务版本不匹配：{service}，预期 {expected}，实际 {revision}"
                )
            entry.update(
                {
                    "revision": revision,
                    "release_state": "retained"
                    if service in config.retained
                    else "target",
                }
            )
            if service in BACKEND_SERVICES:
                entry.update(
                    verify_backend_source(
                        config.root, record["Id"], revision, config.revision, runner
                    )
                )
        report[service] = entry
    verify_served_web(config, runner, web_id=records["web"]["Id"])
    return {
        "status": "passed",
        "target_revision": config.revision,
        "services": report,
        "web_assets_match_runtime": True,
    }
