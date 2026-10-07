"""编排镜像身份、资源快照及临时文件卷恢复，不启动业务应用。"""

from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import tempfile
from typing import cast

from scripts.backup.database import RESTORE_DATABASE_PATTERN
from scripts.backup.runtime import BackupConfig, BackupError, Runner, compose
from scripts.backup.services import Environment


ResourceReport = dict[str, dict[str, object]]


@dataclass(frozen=True)
class ResourceContext:
    root: str
    environment: dict[str, str]
    image_revision: str | None
    api_image: str


def resource_context(runner: Runner, environment: Environment) -> ResourceContext:
    raw = runner.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            environment["service_containers"]["api"],
        ]
    )
    values = dict(value.split("=", 1) for value in json.loads(raw))
    root = values.get("STORAGE_ROOT", "/data/storage")
    if not Path(root).is_relative_to("/data") or ".." in Path(root).parts:
        raise BackupError("运行存储目录不在备份文件卷内")
    labels = (
        json.loads(
            runner.run(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{json .Config.Labels}}",
                    environment["api_image"],
                ]
            )
        )
        or {}
    )
    return ResourceContext(
        root,
        {
            name: values.get(name, "")
            for name in ("GERPGO_API_BASE_URL", "GERPGO_APP_ID", "GERPGO_APP_KEY")
        },
        labels.get("org.opencontainers.image.revision"),
        environment["api_image"],
    )


def resource_references(
    config: BackupConfig, runner: Runner, database: str
) -> list[tuple[str, str]]:
    if database != "delivery_note" and not RESTORE_DATABASE_PATTERN.fullmatch(database):
        raise BackupError("临时恢复数据库名称不安全")
    raw = runner.run(
        compose(
            config,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "delivery_note",
            "-d",
            database,
            "-Atq",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT coalesce(json_agg(json_build_array(kind, storage_path) "
            "ORDER BY id), "
            "'[]'::json) FROM public.input_versions;",
        )
    )
    return [(kind, path) for kind, path in json.loads(raw)]


def probe_resources(
    config: BackupConfig,
    runner: Runner,
    context: ResourceContext,
    volume: str,
    references: list[tuple[str, str]],
) -> ResourceReport:
    payload = json.dumps(
        {
            "root": context.root,
            "environment": context.environment,
            "references": references,
        }
    ).encode()
    scripts = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryFile() as source:
        source.write(payload)
        source.seek(0)
        raw = runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--user",
                "0:0",
                "--network",
                "none",
                "--read-only",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--volume",
                f"{volume}:/data:ro",
                "--volume",
                f"{scripts}:/app/scripts:ro",
                context.api_image,
                "python",
                "-m",
                "scripts.backup.resource_probe",
            ],
            stdin=source,
            timeout_seconds=config.snapshot_timeout_seconds,
        )
    report = cast(ResourceReport, json.loads(raw))
    if not report or any(
        item.get("validation") not in {"passed", "absent"} for item in report.values()
    ):
        raise BackupError("资源验证未返回完整的通过证据")
    return report


def extract_resource_archive(
    config: BackupConfig, runner: Runner, image: str, archive: Path, volume: str
) -> None:
    with archive.open("rb") as source:
        runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--user",
                "0:0",
                "--network",
                "none",
                "--volume",
                f"{volume}:/data",
                image,
                "tar",
                "--numeric-owner",
                "-xzf",
                "-",
                "-C",
                "/data",
            ],
            stdin=source,
            timeout_seconds=config.snapshot_timeout_seconds,
        )


@dataclass(frozen=True)
class ResourceRestore:
    config: BackupConfig
    runner: Runner
    context: ResourceContext
    source_references: list[tuple[str, str]]
    source_report: ResourceReport

    def verify(self, archive: Path, database: str) -> ResourceReport:
        volume = f"deliverynote-resource-restore-{secrets.token_hex(16)}"
        primary_error: Exception | None = None
        restored: ResourceReport = {}
        try:
            references = resource_references(self.config, self.runner, database)
            if references != self.source_references:
                raise BackupError("恢复库资源登记与快照不一致")
            self.runner.run(["docker", "volume", "create", volume])
            extract_resource_archive(
                self.config, self.runner, self.context.api_image, archive, volume
            )
            restored = probe_resources(
                self.config, self.runner, self.context, volume, references
            )
            if restored != self.source_report:
                raise BackupError("资源恢复结果与快照不一致")
        except Exception as error:
            primary_error = error
        finally:
            try:
                self.runner.run(["docker", "volume", "rm", "--force", volume])
            except Exception as cleanup_error:
                primary_error = BackupError(
                    "恢复文件卷清理失败"
                    + (f"；资源验证失败：{primary_error}" if primary_error else "")
                    + f"；{cleanup_error}"
                )
        if primary_error is not None:
            raise primary_error
        return restored
