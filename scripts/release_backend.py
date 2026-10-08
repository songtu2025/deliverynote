"""选择性发布无数据库迁移的后端版本，失败时恢复原镜像。"""

import argparse
import json
import sys
from typing import Sequence

from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.backend_release import BackendReleaseConfig, publish_backend
from scripts.deployment_sources import BACKEND_SERVICES
from scripts.release_common import add_release_arguments, release_config, verify_ci


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_release_arguments(parser)
    parser.add_argument(
        "--services", nargs="+", choices=sorted(BACKEND_SERVICES), required=True
    )
    parser.add_argument(
        "--check-only", action="store_true", help="预检候选，不停止或更新正式服务"
    )
    parser.add_argument("--job-drain-timeout-seconds", type=int, default=1800)
    parser.add_argument("--job-poll-seconds", type=int, default=5)
    parser.add_argument("--stop-timeout-seconds", type=int, default=60)
    arguments = parser.parse_args(argv)
    try:
        base = release_config(arguments)
        config = BackendReleaseConfig(
            **vars(base),
            services=tuple(arguments.services),
            job_drain_timeout_seconds=arguments.job_drain_timeout_seconds,
            job_poll_seconds=arguments.job_poll_seconds,
            stop_timeout_seconds=arguments.stop_timeout_seconds,
        )
        verify_ci(config.revision, arguments.ci_run)
        report = publish_backend(
            config, runner=SubprocessRunner(), check_only=arguments.check_only
        )
    except (BackupError, OSError, ValueError) as error:
        print(f"后端发布失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
