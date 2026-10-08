from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from typing import cast
from unittest.mock import patch

from scripts.backup.runtime import BackupError
from scripts.check_deployment import DeploymentConfig, main, retained_versions
from scripts.deployment_sources import BACKEND_SERVICES
from scripts.deployment_verification import service_snapshot, verify_deployment
from tests.support.release import SHA, OLD_SHA, ReleaseRunner


class DeploymentVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.config = DeploymentConfig(
            root,
            root / "compose.yaml",
            root / ".env",
            "test",
            SHA,
            retained={name: OLD_SHA for name in (*BACKEND_SERVICES, "web")},
        )
        self.runner = ReleaseRunner()
        self.web = patch("scripts.deployment_verification.verify_served_web").start()
        self.addCleanup(patch.stopall)

    def test_declared_old_versions_pass_and_report_target_differences(self) -> None:
        report = verify_deployment(self.config, self.runner)
        self.assertEqual(report["status"], "passed")
        services = cast(dict[str, dict[str, object]], report["services"])
        self.assertEqual(len(services), 6)
        for name in BACKEND_SERVICES:
            self.assertEqual(services[name]["release_state"], "retained")
            self.assertEqual(
                services[name]["different_from_target"], ["delivery_note/probe.py"]
            )
        self.web.assert_called_once()
        self.assertFalse(
            any(
                "up" in command or "tag" in command or "stop" in command
                for command in self.runner.commands
            )
        )

    def test_required_update_cannot_silently_retain_old_api(self) -> None:
        retained = dict(self.config.retained)
        del retained["api"]
        with self.assertRaisesRegex(BackupError, "服务版本不匹配：api"):
            verify_deployment(replace(self.config, retained=retained), self.runner)

    def test_source_missing_extra_modified_and_lock_modified_fail(self) -> None:
        for change in ("missing", "extra", "modified", "lock"):
            with self.subTest(change=change):
                runner = ReleaseRunner()
                if change == "missing":
                    del runner.runtime_files["delivery_note/probe.py"]
                elif change == "extra":
                    runner.runtime_files["delivery_note/unexpected.py"] = "unexpected"
                elif change == "modified":
                    runner.runtime_files["delivery_note/probe.py"] = "changed"
                else:
                    runner.runtime_files["requirements.lock"] = "changed"
                with self.assertRaisesRegex(BackupError, "运行源码.*不一致"):
                    verify_deployment(self.config, runner)

    def test_invalid_retention_and_dirty_repository_fail(self) -> None:
        for retained in ({"db": OLD_SHA}, {"api": "wrong-sha"}):
            with self.subTest(retained=retained), self.assertRaises(BackupError):
                verify_deployment(replace(self.config, retained=retained), self.runner)
        self.runner.dirty = True
        with self.assertRaisesRegex(BackupError, "未提交修改"):
            verify_deployment(self.config, self.runner)

    def test_unhealthy_service_fails_snapshot(self) -> None:
        original = self.runner.inspect

        def unhealthy(identifiers: list[str]) -> str:
            records = json.loads(original(identifiers))
            records[0]["State"]["Health"] = {"Status": "unhealthy"}
            return json.dumps(records)

        with patch.object(self.runner, "inspect", side_effect=unhealthy):
            with self.assertRaisesRegex(BackupError, "服务状态"):
                service_snapshot(self.config, self.runner)

    def test_missing_image_label_is_not_accepted_as_retained(self) -> None:
        original = self.runner.run

        def unlabeled(arguments: list[str], **kwargs: object) -> str:
            if arguments[:3] == ["docker", "image", "inspect"]:
                return json.dumps([{"Config": {"Labels": {}}}])
            return original(arguments, **kwargs)

        with patch.object(self.runner, "run", side_effect=unlabeled):
            with self.assertRaisesRegex(BackupError, "服务版本不匹配"):
                verify_deployment(self.config, self.runner)

    def test_cli_failure_returns_nonzero_and_no_success_json(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch(
            "scripts.check_deployment.SubprocessRunner", return_value=self.runner
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--revision", SHA])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("发布版本核验失败", stderr.getvalue())

    def test_cli_success_has_all_services_and_retention_states(self) -> None:
        arguments = ["--revision", SHA]
        for service, revision in self.config.retained.items():
            arguments.extend(["--retain", service + "=" + revision])
        stdout = io.StringIO()
        with patch(
            "scripts.check_deployment.SubprocessRunner", return_value=self.runner
        ):
            with redirect_stdout(stdout):
                result = main(arguments)
        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["services"]), 6)

    def test_duplicate_retention_is_rejected(self) -> None:
        with self.assertRaises(BackupError):
            retained_versions(["api=" + OLD_SHA, "api=" + SHA])
