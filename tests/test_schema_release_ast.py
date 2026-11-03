from contextlib import nullcontext
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.schema_release import REVIEWED_SCHEMA_CHANGES, verify_reviewed_schema
from tests.support.release import SHA, OLD_SHA


class SchemaReleaseAstTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

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
                    verify_reviewed_schema(self.root, OLD_SHA, SHA, names, runner)

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

    def test_new_model_and_exports_are_limited_to_the_registered_names(self):
        names = ("exception-transfers",)
        change = REVIEWED_SCHEMA_CHANGES[names[0]]
        models = "delivery_note/web/models/batches.py"
        exports = "delivery_note/web/models/__init__.py"
        runner_file = "delivery_note/migrations/runner.py"
        old_model = (
            "from sqlalchemy.orm import Mapped\n"
            "class ExceptionRecord:\n    quantity: int = 1\n"
        )
        new_model = old_model.replace(
            "import Mapped", "import Mapped, relationship"
        ) + (
            "    transfers: list = relationship()\n"
            "class ExceptionTransfer:\n    id: int = 1\n"
        )
        old_exports = (
            'from .batches import ExceptionRecord\n__all__ = ["ExceptionRecord"]\n'
        )
        new_exports = old_exports.replace(
            "import ExceptionRecord", "import ExceptionRecord, ExceptionTransfer"
        ).replace('["ExceptionRecord"]', '["ExceptionRecord", "ExceptionTransfer"]')
        old_runner = "MIGRATIONS: tuple = (existing,)\n"
        new_runner = (
            "from .exception_transfers import migrate as migrate_exception_transfers\n"
            "MIGRATIONS: tuple = (existing, migrate_exception_transfers)\n"
        )
        for extra in (None, "class Unexpected:\n    pass\n"):
            sources = {
                models: (old_model, new_model + (extra or "")),
                exports: (old_exports, new_exports),
                runner_file: (old_runner, new_runner),
            }
            runner = Mock()
            runner.run.side_effect = lambda args: sources[args[-1].split(":", 1)[1]][
                args[-1].startswith(SHA)
            ]
            with patch(
                "scripts.schema_release.source_files",
                side_effect=[
                    ({name: "old" for name in change.files}, {}),
                    ({name: "new" for name in change.files}, {}),
                ],
            ):
                with (
                    self.assertRaisesRegex(BackupError, "batches.py")
                    if extra
                    else nullcontext()
                ):
                    verify_reviewed_schema(self.root, OLD_SHA, SHA, names, runner)
