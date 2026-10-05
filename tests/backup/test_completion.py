from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.backup.archive import write_private_text
from scripts.backup.runtime import BackupError
from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class BackupCompletionTests(BackupTestCase):
    def assert_incomplete(self, destination: Path) -> None:
        directories = list(destination.iterdir())
        self.assertEqual(len(directories), 1)
        self.assertTrue(directories[0].name.startswith(".incomplete-"))
        self.assertTrue((directories[0] / "FAILED.txt").is_file())
        self.assertFalse((directories[0] / "READY").exists())

    def test_completion_write_failures_record_failure_without_ready(self) -> None:
        for filename in ("BACKUP-METADATA.json", "SHA256SUMS", "READY"):
            with self.subTest(filename=filename):
                config = replace(self.config, destination=self.root / filename)
                runner = FakeRunner()

                def fail_write(path: Path, content: str) -> None:
                    if path.name == filename:
                        if filename == "READY":
                            write_private_text(path, content)
                        raise OSError("模拟完成文件写入失败")
                    write_private_text(path, content)

                with patch(
                    "scripts.backup.workflow.write_private_text", side_effect=fail_write
                ):
                    with self.assertRaisesRegex(OSError, "完成文件写入失败"):
                        create_backup(
                            config, runner=runner, now=lambda: self.fixed_time
                        )
                self.assert_incomplete(config.destination)
                self.assertTrue(
                    any(
                        command[:2] == ("docker", "start")
                        for command in runner.commands
                    )
                )

    def test_final_rename_failure_records_failure_without_ready(self) -> None:
        with patch.object(Path, "replace", side_effect=OSError("模拟目录改名失败")):
            with self.assertRaisesRegex(OSError, "目录改名失败"):
                create_backup(
                    self.config, runner=FakeRunner(), now=lambda: self.fixed_time
                )
        self.assert_incomplete(self.destination)

    def test_retention_failure_reports_and_preserves_completed_backup(self) -> None:
        with patch(
            "scripts.backup.workflow.prune_completed_backups",
            side_effect=BackupError("模拟删除旧备份失败"),
        ):
            with self.assertRaisesRegex(
                BackupError, "旧备份清理失败.*完整备份保留.*模拟删除旧备份失败"
            ):
                create_backup(
                    self.config, runner=FakeRunner(), now=lambda: self.fixed_time
                )
        directories = list(self.destination.iterdir())
        self.assertEqual(len(directories), 1)
        self.assertEqual(directories[0].name, "20260722-183000")
        for filename in ("READY", "database.dump", "delivery_data.tar.gz"):
            self.assertTrue((directories[0] / filename).is_file())
        self.assertFalse((directories[0] / "FAILED.txt").exists())
