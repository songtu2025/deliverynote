from contextlib import nullcontext, redirect_stderr
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.release_web import (
    ReleaseConfig,
    main,
    publish_web,
    verify_ci,
)
from scripts.backup.runtime import BackupError
from tests.support.release import SHA, OLD_SHA, ReleaseRunner


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
            retained={
                name: OLD_SHA
                for name in (
                    "api",
                    "worker",
                    "purchase-sync-worker",
                    "inbound-sync-worker",
                )
            },
        )
        self.runner = ReleaseRunner()

    def publish(self) -> dict[str, object]:
        with patch("scripts.release_web.exclusive_lock", return_value=nullcontext()):
            return publish_web(self.config, runner=self.runner)

    def test_success_keeps_other_containers_and_backup_image(self) -> None:
        with patch("scripts.deployment_verification.verify_served_web") as verify:
            result = self.publish()
        self.assertEqual(result["revision"], SHA)
        self.assertEqual(self.runner.current_image, "candidate-image")
        self.assertIn("deployment", result)
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
            "scripts.deployment_verification.verify_served_web",
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
            "scripts.deployment_verification.verify_served_web",
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
        # 发布期间模拟外部任务重建 API。
        self.runner.replace_api_on_update = True
        with patch("scripts.deployment_verification.verify_served_web"):
            with self.assertRaisesRegex(BackupError, "未发布服务.*api"):
                self.publish()

    def test_undeclared_old_backend_blocks_release_before_image_changes(self) -> None:
        from dataclasses import replace

        self.config = replace(self.config, retained={})
        with self.assertRaisesRegex(BackupError, "服务版本不匹配：api"):
            self.publish()
        self.assertFalse(any("tag" in command for command in self.runner.commands))

    def test_modified_backend_blocks_release_before_image_changes(self) -> None:
        self.runner.runtime_files["delivery_note/probe.py"] = "modified"
        with self.assertRaisesRegex(BackupError, "运行源码.*不一致"):
            self.publish()
        self.assertFalse(any("tag" in command for command in self.runner.commands))


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
