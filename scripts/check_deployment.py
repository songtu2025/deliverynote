"""只读核验系统运行版本，不构建镜像、不重启服务。"""

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence

from scripts.backup.runtime import BackupError, SubprocessRunner, compose
from scripts.deployment_verification import verify_deployment


@dataclass(frozen=True)
class DeploymentConfig:
    root: Path
    compose_file: Path
    env_file: Path
    project_name: str
    revision: str
    health_url: str | None = None
    wait_seconds: int = 30
    retained: Mapping[str, str] = field(default_factory=dict)


def retained_versions(values: Sequence[str]) -> dict[str, str]:
    result = {}
    for value in values:
        service, separator, revision = value.partition("=")
        if not separator or service in result:
            raise BackupError("保留版本需使用 SERVICE=SHA，且服务不能重复")
        result[service] = revision
    return result


def add_deployment_arguments(
    parser: argparse.ArgumentParser, *, health_required: bool = False
) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--project-name", default="deliverynote")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--health-url", required=health_required)
    parser.add_argument(
        "--retain",
        action="append",
        default=[],
        help="明确保留 SERVICE=完整SHA，可重复传入",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_deployment_arguments(parser)
    arguments = parser.parse_args(argv)
    try:
        config = DeploymentConfig(
            arguments.root.resolve(),
            arguments.compose_file.resolve(),
            arguments.env_file.resolve(),
            arguments.project_name,
            arguments.revision,
            arguments.health_url,
            retained=retained_versions(arguments.retain),
        )
        runner = SubprocessRunner()
        runner.run(compose(config, "config", "--quiet"))
        report = verify_deployment(config, runner)
    except (BackupError, OSError, ValueError) as error:
        print(f"发布版本核验失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
