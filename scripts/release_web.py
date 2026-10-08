"""发布已通过 CI 的 Web 镜像，失败时恢复并验证原镜像。"""

import argparse
import json
import sys

from scripts.backup.runtime import BackupError, Runner, SubprocessRunner, exclusive_lock
from scripts.deployment_verification import service_snapshot, verify_deployment
from scripts.release_common import (
    ReleaseConfig as ReleaseConfig,
    add_release_arguments,
    previous_config,
    release_config,
    retain_images,
    update_services,
    verify_ci as verify_ci,
    verify_release_inputs,
    verify_unchanged,
)


def publish_web(config: ReleaseConfig, *, runner: Runner) -> dict[str, object]:
    if "web" in config.retained:
        raise BackupError("Web 发布不能将 Web 声明为保留版本")
    with exclusive_lock(config.lock_file):
        candidate = verify_release_inputs(config, runner)
        runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "nginx",
                candidate["Id"],
                "-t",
            ]
        )
        before = service_snapshot(config, runner)
        original = before["web"]
        previous = previous_config(config, before, ("web",), runner)
        verify_deployment(previous, runner, records=before)
        target = original["Config"]["Image"]
        backup = retain_images(config, before, ("web",), runner)["web"]
        try:
            runner.run(["docker", "image", "tag", candidate["Id"], target])
            update_services(config, runner, ("web",))
            after = service_snapshot(config, runner)
            verify_unchanged(before, after, {"web"})
            if after["web"]["Image"] != candidate["Id"]:
                raise BackupError("更新后的 Web 未运行候选镜像")
            deployment = verify_deployment(config, runner, records=after)
        except Exception as failure:
            try:
                runner.run(["docker", "image", "tag", original["Image"], target])
                update_services(config, runner, ("web",))
                recovered = service_snapshot(config, runner)
                if recovered["web"]["Image"] != original["Image"]:
                    raise BackupError("回退后的镜像仍不匹配")
                verify_unchanged(before, recovered, {"web"})
                verify_deployment(previous, runner, records=recovered)
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
    add_release_arguments(parser)
    arguments = parser.parse_args()
    try:
        config = release_config(arguments)
        verify_ci(config.revision, arguments.ci_run)
        result = publish_web(config, runner=SubprocessRunner())
    except (BackupError, OSError, ValueError) as error:
        print(f"发布失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
