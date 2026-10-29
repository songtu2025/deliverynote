"""累计实收迁移的停写时序、限定范围和失败维护门禁。"""

from dataclasses import replace
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from scripts.backup.runtime import BackupError
from scripts.backend_release import BackendReleaseConfig, publish_backend
from scripts.deployment_sources import BACKEND_SERVICES
from scripts.receipt_release import (
    SCHEMA_FILES,
    migrate_receipts,
    verify_receipt_migration,
)
from tests.support.backend_release import BackendRunner
from tests.support.release import SHA, OLD_SHA


class ReceiptReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.config = BackendReleaseConfig(
            root=root,
            compose_file=root / "compose.yaml",
            env_file=root / ".env",
            project_name="deliverynote",
            image="candidate",
            revision=SHA,
            health_url="https://example.test",
            lock_file=root / "release.lock",
            services=tuple(sorted(BACKEND_SERVICES)),
            receipt_migration=True,
            web_image="candidate",
        )
        for target in (
            "scripts.backend_release.exclusive_lock",
            "scripts.deployment_verification.verify_served_web",
            "scripts.backup.services.verify_served_web",
        ):
            mocked = patch(target, return_value=nullcontext())
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_migrates_only_after_all_writers_stop_and_updates_web_atomically(self):
        runner = BackendRunner()

        def migration(config, selected):
            self.assertTrue(
                all(not selected.running[name] for name in (*BACKEND_SERVICES, "web"))
            )
            self.assertTrue(selected.running["db"])

        with (
            patch("scripts.backend_release.verify_receipt_migration"),
            patch(
                "scripts.backend_release.migrate_receipts", side_effect=migration
            ) as migrate,
        ):
            result = publish_backend(self.config, runner=runner, sleep=lambda _: None)
        migrate.assert_called_once()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(set(result["updated_services"]), {*BACKEND_SERVICES, "web"})

    def test_after_migration_failure_rolls_back_but_keeps_entry_closed(self):
        runner = BackendRunner()
        runner.failed_service = "api"
        with (
            patch("scripts.backend_release.verify_receipt_migration"),
            patch("scripts.backend_release.migrate_receipts"),
            self.assertRaisesRegex(BackupError, "入口保持维护"),
        ):
            publish_backend(self.config, runner=runner, sleep=lambda _: None)
        self.assertFalse(runner.running["web"])
        self.assertFalse(runner.running["api"])
        self.assertTrue(all(image == "old-image" for image in runner.images.values()))

    def test_incomplete_service_selection_and_missing_web_are_rejected(self):
        for config in (
            replace(self.config, services=("api",)),
            replace(self.config, web_image=None),
        ):
            with self.assertRaises(BackupError):
                publish_backend(config, runner=BackendRunner(), check_only=True)

    def test_rollback_failure_still_keeps_entry_closed(self):
        runner = BackendRunner()
        runner.failed_service = "api"
        runner.failed_rollback = True
        with (
            patch("scripts.backend_release.verify_receipt_migration"),
            patch("scripts.backend_release.migrate_receipts"),
            self.assertRaisesRegex(BackupError, "回退未通过"),
        ):
            publish_backend(self.config, runner=runner, sleep=lambda _: None)
        self.assertFalse(runner.running["web"])
        self.assertFalse(runner.running["api"])

    def test_schema_gate_rejects_extra_schema_changes(self):
        before = {
            name: "old"
            for name in SCHEMA_FILES
            if not name.endswith("inbound_receipts.py")
        }
        after = {name: "new" for name in SCHEMA_FILES}
        after["delivery_note/migrations/other.py"] = "extra"
        with (
            patch(
                "scripts.receipt_release.source_files",
                side_effect=[(before, {}), (after, {})],
            ),
            self.assertRaises(BackupError),
        ):
            verify_receipt_migration(self.config.root, OLD_SHA, SHA, Mock())

    def test_schema_gate_checks_existing_model_fields_and_runner(self):
        before = {
            name: "old"
            for name in SCHEMA_FILES
            if not name.endswith("inbound_receipts.py")
        }
        after = {name: "new" for name in SCHEMA_FILES}
        runner = Mock()
        runner.run.side_effect = [
            "class Batch:\n    quantity: int = 1\n",
            "class Batch:\n    quantity: int = 2\n",
        ]
        with (
            patch(
                "scripts.receipt_release.source_files",
                side_effect=[(before, {}), (after, {})],
            ),
            self.assertRaises(BackupError),
        ):
            verify_receipt_migration(self.config.root, OLD_SHA, SHA, runner)

    def test_migration_connection_string_never_enters_command_arguments(self):
        runner = Mock()
        runner.run.side_effect = [
            '{"services":{"api":{"environment":{"DATABASE_URL":"postgresql://private"}}}}',
            "",
        ]
        migrate_receipts(self.config, runner)
        arguments = runner.run.call_args_list[-1].args[0]
        self.assertNotIn("postgresql://private", " ".join(arguments))
        self.assertIn("/dev/stdin", arguments)
