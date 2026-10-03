from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup.runtime import BackupConfig, BackupError, SubprocessRunner  # noqa: E402
from scripts.backup.services import inspect_environment  # noqa: E402
from scripts.backup.workflow import create_backup  # noqa: E402


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
            result = dict(inspect_environment(config, SubprocessRunner()))
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
