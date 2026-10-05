from contextlib import nullcontext, redirect_stderr
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Sequence
import unittest
from unittest.mock import patch

from scripts.release_web import (
    REVISION_LABEL,
    ReleaseConfig,
    main,
    publish_web,
    verify_ci,
)
from scripts.backup.runtime import BackupError


SHA = "1" * 40
OLD_SHA = "2" * 40


def container(service: str, image: str = "old-image") -> dict[str, object]:
    return {
        "Id": service + "-id",
        "Image": image,
        "Config": {
            "Image": "web-current",
            "Labels": {
                "org.opencontainers.image.revision": OLD_SHA,
            },
        },
        "State": {"Status": "running"},
        "RestartCount": 0,
    }


class ReleaseRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.current_image = "old-image"
        self.dirty = False
        self.image_revision = SHA
        self.failed_rollback = False
        self.recreated_api = False

    def run(self, arguments: Sequence[str], **kwargs: object) -> str:
        arguments = list(arguments)
        self.commands.append(list(arguments))
        if arguments[0] == "git":
            if "rev-parse" in arguments:
                return SHA
            return " M source.py" if self.dirty else ""
        if arguments[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "candidate-image",
                        "Config": {
                            "Labels": {
                                REVISION_LABEL: self.image_revision,
                            }
                        },
                    }
                ]
            )
        if "ps" in arguments:
            return arguments[-1] + "-id"
        if arguments[:2] == ["docker", "inspect"]:
            return self.inspect(arguments[2:])
        if arguments[:3] == ["docker", "image", "tag"]:
            if arguments[3] == "candidate-image":
                self.current_image = "candidate-image"
            elif arguments[-1] == "web-current":
                if self.failed_rollback:
                    raise BackupError("恢复镜像失败")
                self.current_image = "old-image"
        return ""

    def inspect(self, identifiers: Sequence[str]) -> str:
        records = []
        for identifier in identifiers:
            record = container(identifier.removesuffix("-id"))
            if identifier == "web-id":
                record = container("web", self.current_image)
                record["Config"] = {
                    "Image": "web-current",
                    "Labels": {
                        REVISION_LABEL: (
                            SHA if self.current_image == "candidate-image" else OLD_SHA
                        )
                    },
                }
            if identifier == "api-id" and self.recreated_api:
                record["Id"] = "unexpected-api-id"
            records.append(record)
        return json.dumps(records)


class WebReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.config = ReleaseConfig(
            root=root,
            compose_file=root / "compose.yaml",
            env_file=root / ".env",
            project_name="release-test",
            image="candidate",
            revision=SHA,
            health_url="http://127.0.0.1:18080",
            wait_seconds=2,
        )
        self.runner = ReleaseRunner()

    def publish(self) -> dict[str, object]:
        with patch("scripts.release_web.exclusive_lock", return_value=nullcontext()):
            return publish_web(self.config, runner=self.runner)

    def test_success_keeps_other_containers_and_backup_image(self) -> None:
        with patch("scripts.release_web.verify_served_web") as verify:
            result = self.publish()
        self.assertEqual(result["revision"], SHA)
        self.assertEqual(self.runner.current_image, "candidate-image")
        self.assertEqual(verify.call_count, 2)
        self.assertTrue(
            any(
                command[:4] == ["docker", "image", "tag", "old-image"]
                for command in self.runner.commands
            )
        )
        update = next(command for command in self.runner.commands if "up" in command)
        self.assertEqual(update[-1], "web")
        self.assertIn("--no-deps", update)
        self.assertIn("--no-build", update)

    def test_failed_validation_restores_old_image_and_validates_recovery(self) -> None:
        with patch(
            "scripts.release_web.verify_served_web",
            side_effect=[
                None,
                BackupError("候选页面失败"),
                None,
            ],
        ) as verify:
            with self.assertRaisesRegex(BackupError, "已恢复原镜像.*候选页面失败"):
                self.publish()
        self.assertEqual(self.runner.current_image, "old-image")
        self.assertEqual(verify.call_count, 3)

    def test_rollback_failure_reports_both_errors(self) -> None:
        self.runner.failed_rollback = True
        with patch(
            "scripts.release_web.verify_served_web",
            side_effect=[
                None,
                BackupError("候选页面失败"),
            ],
        ):
            with self.assertRaisesRegex(BackupError, "候选页面失败.*恢复镜像失败"):
                self.publish()

    def test_wrong_revision_or_dirty_repo_cannot_change_images(self) -> None:
        for attribute, value in (("dirty", True), ("image_revision", OLD_SHA)):
            with self.subTest(attribute=attribute):
                self.runner = ReleaseRunner()
                setattr(self.runner, attribute, value)
                with self.assertRaises(BackupError):
                    self.publish()
                self.assertFalse(
                    any("tag" in command for command in self.runner.commands)
                )

    def test_unrelated_container_replacement_fails_release(self) -> None:
        self.runner.recreated_api = True
        # 首次快照后模拟外部任务重建 API。
        self.runner.recreated_api = False

        def validate(*args: object) -> None:
            if self.runner.current_image == "candidate-image":
                self.runner.recreated_api = True

        with patch("scripts.release_web.verify_served_web", side_effect=validate):
            with self.assertRaisesRegex(BackupError, "未发布服务.*api"):
                self.publish()


class ReleaseCITests(unittest.TestCase):
    def test_cli_ci_failure_returns_nonzero_without_publishing(self) -> None:
        arguments = [
            "release",
            "--image",
            "candidate",
            "--revision",
            SHA,
            "--ci-run",
            "123",
            "--health-url",
            "http://127.0.0.1:18080",
        ]
        with patch.object(sys, "argv", arguments), redirect_stderr(io.StringIO()):
            with patch(
                "scripts.release_web.verify_ci", side_effect=BackupError("CI 失败")
            ):
                with patch("scripts.release_web.publish_web") as publish:
                    self.assertEqual(main(), 1)
                publish.assert_not_called()

    def test_cli_verified_rollback_still_returns_nonzero(self) -> None:
        arguments = [
            "release",
            "--image",
            "candidate",
            "--revision",
            SHA,
            "--ci-run",
            "123",
            "--health-url",
            "http://127.0.0.1:18080",
        ]
        with patch.object(sys, "argv", arguments), redirect_stderr(io.StringIO()):
            with patch("scripts.release_web.verify_ci"):
                with patch(
                    "scripts.release_web.publish_web",
                    side_effect=BackupError("发布失败，已恢复原镜像并验收"),
                ):
                    self.assertEqual(main(), 1)

    def test_only_matching_successful_ci_run_can_publish(self) -> None:
        passed = {
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/ci.yml",
            "event": "push",
        }
        jobs = {"jobs": [{"conclusion": "success"}] * 3, "total_count": 3}
        for replacement in (
            {},
            {"head_sha": OLD_SHA},
            {"conclusion": "failure"},
            {"status": "in_progress"},
            {"event": "pull_request"},
        ):
            result = {**passed, **replacement}
            with self.subTest(replacement=replacement):
                with patch(
                    "scripts.release_web.urlopen",
                    side_effect=[
                        io.BytesIO(json.dumps(result).encode()),
                        io.BytesIO(json.dumps(jobs).encode()),
                    ],
                ):
                    if replacement:
                        with self.assertRaises(BackupError):
                            verify_ci(SHA, 123)
                    else:
                        verify_ci(SHA, 123)

    def test_skipped_or_failed_jobs_are_rejected(self) -> None:
        run = {
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/ci.yml",
            "event": "push",
        }
        for conclusion in ("failure", "skipped", None):
            jobs = {"jobs": [{"conclusion": conclusion}], "total_count": 1}
            with self.subTest(conclusion=conclusion):
                with patch(
                    "scripts.release_web.urlopen",
                    side_effect=[
                        io.BytesIO(json.dumps(run).encode()),
                        io.BytesIO(json.dumps(jobs).encode()),
                    ],
                ):
                    with self.assertRaises(BackupError):
                        verify_ci(SHA, 123)
