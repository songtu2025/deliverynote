"""发布已通过 CI 的 Web 镜像，失败时恢复并验证原镜像。"""

import argparse
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, cast
from urllib.request import Request, urlopen

from scripts.backup.runtime import (
    DEFAULT_LOCK_FILE,
    BackupError,
    Runner,
    SubprocessRunner,
    compose,
    exclusive_lock,
)
from scripts.backup.services import REQUIRED_SERVICES
from scripts.check_deployment import add_deployment_arguments, retained_versions
from scripts.deployment_sources import REVISION_LABEL
from scripts.deployment_verification import service_snapshot, verify_deployment


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


def verify_ci(revision: str, run_id: int) -> None:
    base = f"https://api.github.com/repos/songtu2025/deliverynote/actions/runs/{run_id}"

    def read(url: str) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": "DeliveryNote-release"})
        with urlopen(request, timeout=15) as response:
            return cast(dict[str, Any], json.load(response))

    run = read(base)
    expected = {
        "head_sha": revision,
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/ci.yml",
        "event": "push",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise BackupError("指定提交的 master 推送 CI 尚未全部成功")
    jobs = read(base + "/jobs?per_page=100")
    entries = jobs.get("jobs", [])
    if (
        len(entries) < 3
        or len(entries) != jobs.get("total_count")
        or any(job.get("conclusion") != "success" for job in entries)
    ):
        raise BackupError("CI 包含未完成、失败或跳过的任务，拒绝发布")


def _unchanged(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> None:
    for service in REQUIRED_SERVICES - {"web"}:
        if before[service]["Id"] != after[service]["Id"]:
            raise BackupError(f"未发布服务的容器发生变化：{service}")


def _update_web(config: ReleaseConfig, runner: Runner) -> None:
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
            "web",
        ),
        timeout_seconds=config.wait_seconds + 60,
    )


def publish_web(config: ReleaseConfig, *, runner: Runner) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", config.revision) or config.wait_seconds <= 0:
        raise BackupError("发布必须指定完整提交 SHA 和正数等待时间")
    if "web" in config.retained:
        raise BackupError("Web 发布不能将 Web 声明为保留版本")
    with exclusive_lock(config.lock_file):
        head = runner.run(["git", "-C", str(config.root), "rev-parse", "HEAD"]).strip()
        dirty = runner.run(
            ["git", "-C", str(config.root), "status", "--porcelain"]
        ).strip()
        if head != config.revision or dirty:
            raise BackupError("正式源码提交不匹配或工作区存在未提交修改")
        runner.run(compose(config, "config", "--quiet"))
        candidate = json.loads(
            runner.run(["docker", "image", "inspect", config.image])
        )[0]
        if candidate["Config"]["Labels"].get(REVISION_LABEL) != config.revision:
            raise BackupError("候选镜像版本与发布提交不匹配")
        runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "nginx",
                config.image,
                "-t",
            ]
        )
        before = service_snapshot(config, runner)
        original = before["web"]
        previous_image = json.loads(
            runner.run(["docker", "image", "inspect", original["Image"]])
        )[0]
        previous_revision = (previous_image["Config"].get("Labels") or {}).get(
            REVISION_LABEL
        )
        if not isinstance(previous_revision, str):
            raise BackupError("原 Web 镜像缺少提交标记，无法核验保留版本")
        previous_config = replace(
            config, retained={**config.retained, "web": previous_revision}
        )
        verify_deployment(previous_config, runner, records=before)
        target = original["Config"]["Image"]
        backup = f"{config.project_name}-web:before-{config.revision[:7]}"
        runner.run(["docker", "image", "tag", original["Image"], backup])
        try:
            runner.run(["docker", "image", "tag", candidate["Id"], target])
            _update_web(config, runner)
            after = service_snapshot(config, runner)
            _unchanged(before, after)
            if after["web"]["Image"] != candidate["Id"]:
                raise BackupError("更新后的 Web 未运行候选镜像")
            deployment = verify_deployment(config, runner, records=after)
        except Exception as failure:
            try:
                runner.run(["docker", "image", "tag", original["Image"], target])
                _update_web(config, runner)
                recovered = service_snapshot(config, runner)
                if recovered["web"]["Image"] != original["Image"]:
                    raise BackupError("回退后的镜像仍不匹配")
                _unchanged(before, recovered)
                verify_deployment(previous_config, runner, records=recovered)
            except Exception as recovery:
                raise BackupError(
                    f"发布失败且回退未通过：{failure}; {recovery}"
                ) from recovery
            raise BackupError(f"发布失败，已恢复原镜像并验收：{failure}") from failure
        return {
            "revision": config.revision,
            "updated_services": ["web"],
            "other_five_containers_unchanged": True,
            "rollback_image": backup,
            "deployment": deployment,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="仅发布已通过 CI 的 Web 镜像。")
    add_deployment_arguments(parser, health_required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--ci-run", type=int, required=True)
    parser.add_argument("--wait-seconds", type=int, default=120)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    arguments = parser.parse_args()
    config = ReleaseConfig(
        root=arguments.root.resolve(),
        compose_file=arguments.compose_file.resolve(),
        env_file=arguments.env_file.resolve(),
        project_name=arguments.project_name,
        image=arguments.image,
        revision=arguments.revision,
        health_url=arguments.health_url,
        wait_seconds=arguments.wait_seconds,
        lock_file=arguments.lock_file,
    )
    try:
        config = replace(config, retained=retained_versions(arguments.retain))
        verify_ci(config.revision, arguments.ci_run)
        result = publish_web(config, runner=SubprocessRunner())
    except (BackupError, OSError, ValueError) as error:
        print(f"发布失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
