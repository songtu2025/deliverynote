"""已审核结构变更的停写时序、限定范围和失败维护门禁。"""

from dataclasses import replace
from contextlib import nullcontext
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.backend_release import BackendReleaseConfig, publish_backend
from scripts.deployment_sources import BACKEND_SERVICES
from scripts.schema_release import (
    REVIEWED_SCHEMA_CHANGES,
    run_schema_migrations,
    verify_reviewed_schema,
)
from tests.support.backend_release import BackendRunner
from tests.support.release import SHA, OLD_SHA


class SchemaReleaseTests(unittest.TestCase):
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
            schema_changes=("inbound-receipts",),
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
            patch("scripts.backend_release.verify_reviewed_schema"),
            patch(
                "scripts.backend_release.run_schema_migrations", side_effect=migration
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
            patch("scripts.backend_release.verify_reviewed_schema"),
            patch("scripts.backend_release.run_schema_migrations"),
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
            patch("scripts.backend_release.verify_reviewed_schema"),
            patch("scripts.backend_release.run_schema_migrations"),
            self.assertRaisesRegex(BackupError, "回退未通过"),
        ):
            publish_backend(self.config, runner=runner, sleep=lambda _: None)
        self.assertFalse(runner.running["web"])
        self.assertFalse(runner.running["api"])

    def test_schema_gate_rejects_extra_schema_changes(self):
        before = {
            name: "old"
            for name in REVIEWED_SCHEMA_CHANGES["inbound-receipts"].files
            if not name.endswith("inbound_receipts.py")
        }
        after = {
            name: "new" for name in REVIEWED_SCHEMA_CHANGES["inbound-receipts"].files
        }
        after["delivery_note/migrations/other.py"] = "extra"
        with (
            patch(
                "scripts.schema_release.source_files",
                side_effect=[(before, {}), (after, {})],
            ),
            self.assertRaises(BackupError),
        ):
            verify_reviewed_schema(
                self.config.root, OLD_SHA, SHA, self.config.schema_changes, Mock()
            )

    def test_schema_gate_checks_existing_model_fields_and_runner(self):
        before = {
            name: "old"
            for name in REVIEWED_SCHEMA_CHANGES["inbound-receipts"].files
            if not name.endswith("inbound_receipts.py")
        }
        after = {
            name: "new" for name in REVIEWED_SCHEMA_CHANGES["inbound-receipts"].files
        }
        runner = Mock()
        runner.run.side_effect = [
            "class Batch:\n    quantity: int = 1\n",
            "class Batch:\n    quantity: int = 2\n",
        ]
        with (
            patch(
                "scripts.schema_release.source_files",
                side_effect=[(before, {}), (after, {})],
            ),
            self.assertRaises(BackupError),
        ):
            verify_reviewed_schema(
                self.config.root, OLD_SHA, SHA, self.config.schema_changes, runner
            )

    def test_migration_connection_string_never_enters_command_arguments(self):
        runner = Mock()
        runner.run.side_effect = [
            '{"services":{"api":{"environment":{"DATABASE_URL":"postgresql://private"}}}}',
            "",
        ]
        run_schema_migrations(self.config, runner)
        arguments = runner.run.call_args_list[-1].args[0]
        self.assertNotIn("postgresql://private", " ".join(arguments))
        self.assertIn("/dev/stdin", arguments)

    def test_document_note_partial_release_migrates_without_web(self):
        config = replace(
            self.config,
            schema_changes=("document-note-text",),
            services=("api", "worker"),
            web_image=None,
            retained={
                name: OLD_SHA
                for name in {"web", "purchase-sync-worker", "inbound-sync-worker"}
            },
        )
        runner = BackendRunner()
        with (
            patch("scripts.backend_release.verify_reviewed_schema") as verify,
            patch("scripts.backend_release.run_schema_migrations") as migrate,
        ):
            result = publish_backend(config, runner=runner, sleep=lambda _: None)
        self.assertEqual(result["updated_services"], ["worker", "api"])
        migrate.assert_called_once_with(config, runner)
        self.assertTrue(verify.called)
        self.assertTrue(
            all(call.args[3] == config.schema_changes for call in verify.call_args_list)
        )
        self.assertEqual(runner.images["web"], "old-image")

    def test_invalid_schema_names_and_unapproved_web_are_rejected(self):
        for names, web, message in (
            (("unknown",), None, "未登记.*unknown"),
            (("document-note-text",) * 2, None, "重复.*document-note-text"),
            (("document-note-text",), "candidate", "联合 Web"),
            ((), "candidate", "联合 Web"),
        ):
            with (
                self.subTest(names=names, web=web),
                self.assertRaisesRegex(BackupError, message),
            ):
                publish_backend(
                    replace(self.config, schema_changes=names, web_image=web),
                    runner=BackendRunner(),
                    check_only=True,
                )

    def test_schema_gate_allows_already_applied_changes(self):
        files = {
            name: "same" for name in REVIEWED_SCHEMA_CHANGES["document-note-text"].files
        }
        runner = Mock()
        with patch("scripts.schema_release.source_files", return_value=(files, {})):
            verify_reviewed_schema(
                self.config.root, OLD_SHA, SHA, ("document-note-text",), runner
            )
        runner.run.assert_not_called()

    def test_ast_gate_only_ignores_declared_fields_imports_and_migrations(self):
        names = ("document-note-text",)
        module = "batch_file_document_note_text"
        function = "migrate_" + module
        model = "delivery_note/web/models/batches.py"
        runner_file = "delivery_note/migrations/runner.py"
        old_model = (
            "from sqlalchemy import String\nclass BatchFile:\n"
            "    document_note: str = String(20)\n    quantity: int = 1\n"
        )
        new_model = old_model.replace("import String", "import String, Text").replace(
            "String(20)", "Text()"
        )
        old_runner = "MIGRATIONS: tuple = (existing,)\nOTHER = ()\n"
        new_runner = (
            f"from .{module} import migrate as {function}\n"
            f"MIGRATIONS: tuple = (existing, {function})\nOTHER = ()\n"
        )
        expected = REVIEWED_SCHEMA_CHANGES[names[0]].files
        for model_source, runner_source, error in (
            (new_model, new_runner, None),
            (
                new_model.replace("quantity: int = 1", "quantity: int = 2"),
                new_runner,
                model,
            ),
            (
                new_model.replace("String, Text", "Integer, Text"),
                new_runner,
                model,
            ),
            (
                new_model,
                new_runner.replace("OTHER = ()", f"OTHER = ({function},)"),
                runner_file,
            ),
            (new_model, new_runner.replace("existing, ", ""), runner_file),
        ):
            runner = Mock()
            sources = {
                model: (old_model, model_source),
                runner_file: (old_runner, runner_source),
            }
            runner.run.side_effect = lambda args: sources[args[-1].split(":", 1)[1]][
                args[-1].startswith(SHA)
            ]
            with (
                self.subTest(model=model_source, runner=runner_source, error=error),
                patch(
                    "scripts.schema_release.source_files",
                    side_effect=[
                        ({file: "old" for file in expected}, {}),
                        ({file: "new" for file in expected}, {}),
                    ],
                ),
            ):
                with (
                    self.assertRaisesRegex(BackupError, error)
                    if error
                    else nullcontext()
                ):
                    verify_reviewed_schema(
                        self.config.root, OLD_SHA, SHA, names, runner
                    )

    @patch("locale.getencoding", return_value="utf-8")
    def test_real_git_document_note_history(self, _encoding):
        root = Path(__file__).resolve().parents[1]
        old = "c82d4aba4b2180c644202be92fcba8ea1045097a"
        target = "a27770a03f1857217b39e430d55754cab73a4763"
        for revision in (old, target):
            result = subprocess.run(
                ["git", "-C", str(root), "cat-file", "-e", revision + "^{commit}"],
                capture_output=True,
                check=False,
            )
            if result.returncode:
                self.skipTest("测试仓库缺少历史提交：" + revision)
        verify_reviewed_schema(
            root, old, target, ("document-note-text",), SubprocessRunner()
        )
        with self.assertRaisesRegex(BackupError, "batch_file_document_note_text.py"):
            verify_reviewed_schema(
                root, old, target, ("inbound-receipts",), SubprocessRunner()
            )
