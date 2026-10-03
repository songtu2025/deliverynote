from __future__ import annotations

import sys
import tarfile

from scripts.backup.archive import validate_data_archive
from scripts.backup.runtime import BackupConfig, BackupError, SubprocessRunner
from scripts.backup.services import inspect_environment
from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class BackupArchiveTests(BackupTestCase):
    def test_archive_failure_leaves_incomplete_marker_and_resumes_services(self):
        runner = FakeRunner(failure="archive")

        with self.assertRaisesRegex(BackupError, "模拟文件卷归档失败"):
            create_backup(
                self.config,
                runner=runner,
                now=lambda: self.fixed_time,
            )

        failed = list(self.destination.glob(".incomplete-20260722-183000-*"))
        self.assertEqual(len(failed), 1)
        self.assertTrue((failed[0] / "FAILED.txt").is_file())
        self.assertFalse((failed[0] / "READY").exists())
        self.assertTrue(any("start" in command for command in runner.commands))

    def test_retention_only_prunes_old_completed_standard_directories(self):
        self.destination.mkdir()
        for name in ("20260719-183000", "20260720-183000"):
            directory = self.destination / name
            directory.mkdir()
            (directory / "READY").write_text("ready\n", encoding="utf-8")
        unrelated = self.destination / "manual-copy"
        unrelated.mkdir()
        (unrelated / "READY").write_text("ready\n", encoding="utf-8")
        linked = self.destination / "20260718-183000"
        linked.symlink_to(unrelated, target_is_directory=True)
        config = BackupConfig(
            **{
                **self.config.__dict__,
                "retention_count": 2,
            }
        )

        result = create_backup(config, runner=FakeRunner(), now=lambda: self.fixed_time)

        self.assertEqual(result["pruned_backups"], ["20260719-183000"])
        self.assertFalse((self.destination / "20260719-183000").exists())
        self.assertTrue((self.destination / "20260720-183000").is_dir())
        self.assertTrue((self.destination / "20260722-183000").is_dir())
        self.assertTrue(unrelated.is_dir())
        self.assertTrue(linked.is_symlink())

    def test_check_only_inspects_without_stopping_services(self):
        runner = FakeRunner()

        result = inspect_environment(self.config, runner)

        self.assertEqual(result["active_jobs"], 0)
        self.assertEqual(result["data_volume"], "deliverynote_delivery_data")
        self.assertFalse(any("stop" in command for command in runner.commands))
        self.assertFalse(self.destination.exists())

    def test_subprocess_timeout_becomes_controlled_backup_error(self):
        with self.assertRaisesRegex(BackupError, "命令执行超过 1 秒"):
            SubprocessRunner().run(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout_seconds=1,
            )

    def test_archive_rejects_link_escaping_backup_root(self):
        archive_path = self.root / "unsafe.tar.gz"
        link = tarfile.TarInfo("storage/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.addfile(link)

        with self.assertRaisesRegex(BackupError, "不安全链接"):
            validate_data_archive(archive_path)
