"""Web 与后端发布共用提交、镜像和服务身份检查。"""

import argparse
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence, TypeVar, cast

from scripts.backup.runtime import DEFAULT_LOCK_FILE, BackupError, Runner, compose
from scripts.ci_evidence import (
    EVIDENCE_PREFIX,
    WORKFLOW_PATH,
    EvidenceError,
    Reader,
    api_reader,
    commit_tree,
    is_reuse_job,
    pr_run_problem,
    run_jobs,
    verified_pr_run,
)
from scripts.backup.services import REQUIRED_SERVICES
from scripts.check_deployment import add_deployment_arguments, retained_versions
from scripts.deployment_sources import REVISION_LABEL
from scripts.deployment_verification import verify_source_checkout


@dataclass(frozen=True)
class ReleaseConfig:
    root: Path
    compose_file: Path
    env_file: Path
    project_name: str
    image: str
    revision: str
    health_url: str
    wait_seconds: int = 120
    lock_file: Path = DEFAULT_LOCK_FILE
    retained: Mapping[str, str] = field(default_factory=dict)


ConfigT = TypeVar("ConfigT", bound=ReleaseConfig)


def verify_ci(revision: str, run_id: int, read: Reader | None = None) -> None:
    """要求 master 推送 CI 全部成功，或有测试过相同代码指纹且全部成功的 PR CI。"""
    read = read or api_reader()
    run = read(f"/actions/runs/{run_id}")
    if run.get("path") != WORKFLOW_PATH or run.get("status") != "completed":
        raise BackupError("指定的 CI 运行尚未完成")
    if run.get("event") == "push":
        if run.get("head_sha") != revision or run.get("conclusion") != "success":
            raise BackupError("指定提交的 master 推送 CI 尚未全部成功")
        jobs = run_jobs(read, run_id)
        if len(jobs) >= 3 and all(job.get("conclusion") == "success" for job in jobs):
            return
        if not _reused(jobs):
            raise BackupError("CI 包含未完成、失败或跳过的任务，拒绝发布")
    elif run.get("event") != "pull_request":
        raise BackupError("CI 运行类型不支持发布")
    _verify_pr_evidence(read, revision, None if run.get("event") == "push" else run_id)


def _reused(jobs: list[dict[str, Any]]) -> bool:
    reuse = [job for job in jobs if is_reuse_job(str(job.get("name", "")))]
    others = [job for job in jobs if job not in reuse]
    return (
        len(reuse) == 1
        and reuse[0].get("conclusion") == "success"
        and all(job.get("conclusion") == "skipped" for job in others)
    )


def _verify_pr_evidence(read: Reader, revision: str, run_id: int | None) -> None:
    # 复用 PR 结果时，要求待发布提交已在 master 上且代码指纹与 PR 测试的代码一致。
    try:
        compare = read(f"/compare/{revision}...master")
        if compare.get("status") not in {"identical", "ahead"}:
            raise BackupError("待发布提交不在 master 上")
        tree = commit_tree(read, revision)
        if run_id is None:
            verified_pr_run(read, tree)
            return
        problem = pr_run_problem(read, run_id)
        if problem is not None:
            raise BackupError(problem)
        if not _has_evidence(read, run_id, tree):
            raise BackupError("指定的 PR CI 没有测试过待发布的代码")
    except EvidenceError as error:
        raise BackupError(str(error)) from error


def _has_evidence(read: Reader, run_id: int, tree: str) -> bool:
    artifacts = read(f"/actions/runs/{run_id}/artifacts?per_page=100")
    return any(
        artifact.get("name") == f"{EVIDENCE_PREFIX}{tree}"
        and not artifact.get("expired")
        for artifact in artifacts.get("artifacts", [])
    )


def image_record(runner: Runner, image: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads(runner.run(["docker", "image", "inspect", image]))[0]
    )


def verify_release_inputs(config: ReleaseConfig, runner: Runner) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", config.revision) or config.wait_seconds <= 0:
        raise BackupError("发布必须指定完整提交 SHA 和正数等待时间")
    verify_source_checkout(config.root, config.revision, runner)
    runner.run(compose(config, "config", "--quiet"))
    candidate = image_record(runner, config.image)
    if (candidate["Config"].get("Labels") or {}).get(REVISION_LABEL) != config.revision:
        raise BackupError("候选镜像版本与发布提交不匹配")
    return candidate


def previous_config(
    config: ConfigT,
    before: dict[str, dict[str, Any]],
    services: Sequence[str],
    runner: Runner,
) -> ConfigT:
    retained = dict(config.retained)
    for service in services:
        image = image_record(runner, before[service]["Image"])
        revision = (image["Config"].get("Labels") or {}).get(REVISION_LABEL)
        if not isinstance(revision, str):
            raise BackupError(f"原 {service} 镜像缺少提交标记，无法核验保留版本")
        retained[service] = revision
    return replace(config, retained=retained)


def update_services(
    config: ReleaseConfig, runner: Runner, services: Sequence[str]
) -> None:
    runner.run(
        compose(
            config,
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            str(config.wait_seconds),
            *services,
        ),
        timeout_seconds=config.wait_seconds + 60,
    )


def verify_unchanged(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    updated: set[str],
) -> None:
    for service in REQUIRED_SERVICES:
        old, new = before[service], after[service]
        if service not in updated and any(
            old[key] != new[key] for key in ("Id", "Image")
        ):
            raise BackupError(f"未发布服务的容器发生变化：{service}")
        mounts = [
            sorted(
                record.get("Mounts", []), key=lambda mount: mount.get("Destination", "")
            )
            for record in (old, new)
        ]
        if mounts[0] != mounts[1]:
            raise BackupError(f"服务的数据挂载发生变化：{service}")


def retain_images(
    config: ReleaseConfig,
    before: dict[str, dict[str, Any]],
    services: Sequence[str],
    runner: Runner,
) -> dict[str, str]:
    tags = {}
    for service in services:
        tags[service] = f"{config.project_name}-{service}:before-{config.revision[:7]}"
        runner.run(["docker", "image", "tag", before[service]["Image"], tags[service]])
    return tags


def add_release_arguments(parser: argparse.ArgumentParser) -> None:
    add_deployment_arguments(parser, health_required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--ci-run", type=int, required=True)
    parser.add_argument("--wait-seconds", type=int, default=120)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)


def release_config(arguments: argparse.Namespace) -> ReleaseConfig:
    return ReleaseConfig(
        root=arguments.root.resolve(),
        compose_file=arguments.compose_file.resolve(),
        env_file=arguments.env_file.resolve(),
        project_name=arguments.project_name,
        image=arguments.image,
        revision=arguments.revision,
        health_url=arguments.health_url,
        wait_seconds=arguments.wait_seconds,
        lock_file=arguments.lock_file,
        retained=retained_versions(arguments.retain),
    )
