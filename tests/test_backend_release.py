"""验证后端发布的预检、排空、选择性更新和失败恢复。"""

from contextlib import nullcontext, redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
import unittest
from unittest.mock import patch

from scripts.backup.runtime import BackupError
from scripts.backend_release import BackendReleaseConfig, publish_backend
from scripts.deployment_sources import BACKEND_SERVICES
from scripts.release_backend import main
from scripts.release_common import verify_unchanged
from tests.support.backend_release import BackendRunner
from tests.support.release import SHA, OLD_SHA


class BackendReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.config = BackendReleaseConfig(
            root,
            root / "compose.yaml",
            root / ".env",
            "test",
            "candidate",
            SHA,
            "http://localhost:8080",
            services=("worker",),
            retained={
                name: OLD_SHA for name in (BACKEND_SERVICES - {"worker"}) | {"web"}
            },
            job_drain_timeout_seconds=1,
            job_poll_seconds=1,
        )
        self.runner = BackendRunner()
        self.lock = patch(
            "scripts.backend_release.exclusive_lock", return_value=nullcontext()
        )
        self.lock.start()
        self.addCleanup(self.lock.stop)
        self.web = patch("scripts.deployment_verification.verify_served_web")
        self.web.start()
        self.addCleanup(self.web.stop)
        recovery_web = patch("scripts.backup.services.verify_served_web")
        recovery_web.start()
        self.addCleanup(recovery_web.stop)

    def publish(
        self,
        *,
        check_only: bool = False,
        sleep: Callable[[float], None] = lambda _: None,
        monotonic: Callable[[], float] = lambda: 0.0,
    ) -> dict[str, object]:
        return publish_backend(
            self.config,
            runner=self.runner,
            check_only=check_only,
            sleep=sleep,
            monotonic=monotonic,
        )

    def test_precheck_does_not_stop_services_or_change_image_tags(self) -> None:
        report = self.publish(check_only=True)
        self.assertEqual(report["status"], "ready")
        self.assertFalse(
            any("stop" in args or "tag" in args for args in self.runner.commands)
        )
        probe = next(
            args for args in self.runner.commands if args[:2] == ["docker", "run"]
        )
        self.assertIn("--read-only", probe)
        self.assertIn("none", probe)

    def test_only_selected_worker_updates_after_all_queues_drain(self) -> None:
        self.runner.counts = [3, 2, 0, 0]
        report = self.publish(sleep=lambda _: None, monotonic=lambda: 0.0)
        self.assertEqual(report["updated_services"], ["worker"])
        self.assertEqual(self.runner.images["worker"], "candidate-image")
        for name in self.runner.images.keys() - {"worker"}:
            self.assertEqual(self.runner.images[name], "old-image")
        stops = [args for args in self.runner.commands if "stop" in args]
        self.assertEqual(stops[0][-2:], ["web", "api"])
        self.assertEqual(stops[1][-1], "worker")
        self.assertTrue(all(self.runner.running.values()))
        self.assertTrue(
            all(args[-1] == "worker" for args in self.runner.commands if "up" in args)
        )

    def test_timeout_restores_original_entry_without_stopping_workers(self) -> None:
        self.runner.counts = [3]
        clock = iter([0.0, 2.0])
        with self.assertRaisesRegex(BackupError, "已恢复原镜像.*排空超时"):
            self.publish(sleep=lambda _: None, monotonic=lambda: next(clock))
        stops = [args for args in self.runner.commands if "stop" in args]
        self.assertEqual(len(stops), 1)
        self.assertFalse(
            any("tag" in args or "up" in args for args in self.runner.commands)
        )
        self.assertTrue(all(self.runner.running.values()))

    def test_partial_update_failure_rolls_back_every_selected_service(self) -> None:
        self.config = replace(
            self.config,
            services=("worker", "api"),
            retained={
                name: OLD_SHA
                for name in {"web", "purchase-sync-worker", "inbound-sync-worker"}
            },
        )
        self.runner.failed_service = "api"
        with self.assertRaisesRegex(BackupError, "已恢复原镜像.*启动失败"):
            self.publish()
        self.assertTrue(
            all(image == "old-image" for image in self.runner.images.values())
        )
        self.assertTrue(all(self.runner.running.values()))
        updates = [args[-1] for args in self.runner.commands if "up" in args]
        self.assertEqual(updates, ["worker", "api", "worker", "api"])

    def test_preflight_rejections_leave_formal_services_untouched(self) -> None:
        for attribute, value in (
            ("dirty", True),
            ("image_revision", OLD_SHA),
            ("tampered_candidate", True),
        ):
            with self.subTest(attribute=attribute):
                self.runner = BackendRunner()
                setattr(self.runner, attribute, value)
                with self.assertRaises(BackupError):
                    self.publish()
                self.assertFalse(
                    any(
                        "stop" in args or "tag" in args for args in self.runner.commands
                    )
                )

    def test_missing_retention_duplicate_selection_and_overlap_are_rejected(
        self,
    ) -> None:
        for config in (
            replace(self.config, retained={}),
            replace(self.config, services=("worker", "worker")),
            replace(self.config, services=("db",)),
            replace(self.config, retained={**self.config.retained, "worker": OLD_SHA}),
        ):
            with self.subTest(config=config), self.assertRaises(BackupError):
                publish_backend(config, runner=self.runner)
        self.assertFalse(any("stop" in args for args in self.runner.commands))

    def test_automatic_schema_migration_is_rejected_for_selected_api(self) -> None:
        self.config = replace(
            self.config,
            services=("api",),
            retained={name: OLD_SHA for name in (BACKEND_SERVICES - {"api"}) | {"web"}},
        )
        self.runner.automatic_migration = "true"
        with self.assertRaisesRegex(BackupError, "自动迁移"):
            self.publish()
        self.assertFalse(any("stop" in args for args in self.runner.commands))

    def test_rollback_failure_reports_both_failures(self) -> None:
        self.runner.failed_service = "worker"
        self.runner.failed_rollback = True
        with self.assertRaisesRegex(BackupError, "启动失败.*回退失败"):
            self.publish()

    def test_task_appearing_after_worker_stop_aborts_before_retagging(self) -> None:
        self.runner.counts = [0, 0, 1]
        with self.assertRaisesRegex(BackupError, "已恢复原镜像.*仍存在活动任务"):
            self.publish()
        self.assertFalse(any("tag" in args for args in self.runner.commands))
        self.assertTrue(all(self.runner.running.values()))

    def test_shared_tags_are_rejected_before_maintenance(self) -> None:
        original = self.runner.inspect

        def shared(identifiers: list[str]) -> str:
            records = json.loads(original(identifiers))
            for record in records:
                record["Config"]["Image"] = "shared-tag"
            return json.dumps(records)

        with patch.object(self.runner, "inspect", side_effect=shared):
            with self.assertRaisesRegex(BackupError, "标签共用"):
                self.publish()
        self.assertFalse(any("stop" in args for args in self.runner.commands))

    def test_mount_change_fails_validation_and_rolls_back(self) -> None:
        original = self.runner.inspect
        calls = 0

        def changed(identifiers: list[str]) -> str:
            nonlocal calls
            calls += 1
            records = json.loads(original(identifiers))
            if calls == 2:
                records[0]["Mounts"] = [{"Name": "unexpected"}]
            return json.dumps(records)

        with patch.object(self.runner, "inspect", side_effect=changed):
            with self.assertRaisesRegex(BackupError, "已恢复原镜像.*挂载发生变化"):
                self.publish()
        self.assertTrue(
            all(image == "old-image" for image in self.runner.images.values())
        )

    def test_mount_order_is_ignored_but_source_and_permissions_must_match(self) -> None:
        before = {
            name: record
            for name, record in zip(
                self.runner.images,
                json.loads(
                    self.runner.inspect([name + "-id" for name in self.runner.images])
                ),
                strict=True,
            )
        }
        before["worker"]["Mounts"] = [
            {"Destination": "/data", "Source": "volume-a", "RW": True},
            {"Destination": "/control", "Source": "/test/control", "RW": False},
        ]
        after = deepcopy(before)
        after["worker"]["Mounts"].reverse()
        verify_unchanged(before, after, set())
        for key, value in (("Source", "/wrong"), ("RW", True)):
            changed = deepcopy(after)
            changed["worker"]["Mounts"][0][key] = value
            with self.assertRaisesRegex(BackupError, "挂载发生变化"):
                verify_unchanged(before, changed, set())

    def cli_arguments(self) -> list[str]:
        args = [
            "--image",
            "candidate",
            "--revision",
            SHA,
            "--ci-run",
            "123",
            "--health-url",
            self.config.health_url,
            "--services",
            "worker",
        ]
        for name, revision in self.config.retained.items():
            args.extend(["--retain", name + "=" + revision])
        return args

    def test_cli_ci_failure_cannot_publish(self) -> None:
        with patch(
            "scripts.release_backend.verify_ci", side_effect=BackupError("CI 失败")
        ):
            with patch("scripts.release_backend.publish_backend") as publish:
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(self.cli_arguments()), 1)
                publish.assert_not_called()

    def test_cli_precheck_returns_readable_report(self) -> None:
        stdout = io.StringIO()
        with (
            patch("scripts.release_backend.verify_ci"),
            patch("scripts.release_backend.SubprocessRunner", return_value=self.runner),
        ):
            with redirect_stdout(stdout):
                self.assertEqual(main([*self.cli_arguments(), "--check-only"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "ready")

    def test_cli_verified_rollback_is_still_a_failed_release(self) -> None:
        self.runner.failed_service = "worker"
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("scripts.release_backend.verify_ci"),
            patch("scripts.release_backend.SubprocessRunner", return_value=self.runner),
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(self.cli_arguments()), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("已恢复原镜像", stderr.getvalue())
