from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Sequence

from scripts.backup_deliverynote import (
    BackupConfig,
    BackupError,
    SubprocessRunner,
    _validate_data_archive,
    create_backup,
    inspect_environment,
)


class FakeRunner:
    def __init__(self, *, fail_archive: bool = False):
        self.fail_archive = fail_archive
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdout: BinaryIO | None = None,
        timeout_seconds: int = 300,
    ) -> str:
        command = tuple(arguments)
        self.commands.append(command)

        if "pg_dump" in command:
            if stdout is None:
                raise AssertionError("pg_dump 必须直接写入文件")
            stdout.write(b"PGDMP\x01\x0funit-test")
            return ""
        if command[:3] == ("docker", "volume", "ls"):
            return "deliverynote_delivery_data\n"
        if command[:2] == ("docker", "run"):
            if "pg_restore" in command:
                return "; Archive created for unit test\nTABLE public batches\n"
            if "tar" in command:
                if self.fail_archive:
                    raise BackupError("模拟文件卷归档失败")
                mount = next(
                    command[index + 1]
                    for index, value in enumerate(command)
                    if value == "--volume" and command[index + 1].endswith(":/backup")
                )
                target = Path(mount.removesuffix(":/backup")) / "delivery_data.tar.gz"
                payload = b"delivery-data"
                info = tarfile.TarInfo("storage/example.bin")
                info.size = len(payload)
                with tarfile.open(target, "w:gz") as archive:
                    archive.addfile(info, io.BytesIO(payload))
                return ""
        if "images" in command and "--quiet" in command:
            service = command[-1]
            return f"sha256:{service}-image\n"
        if "ps" in command and "--status" in command and "--services" in command:
            return "db\napi\nworker\nweb\n"
        if "psql" in command:
            return "0\n"
        return ""


class BackupDeliveryNoteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.compose_file = self.root / "compose.yaml"
        self.env_file = self.root / ".env"
        self.compose_file.write_text("services: {}\n", encoding="utf-8")
        self.env_file.write_text("POSTGRES_PASSWORD=test\n", encoding="utf-8")
        self.destination = self.root / "backups"
        self.config = BackupConfig(
            compose_file=self.compose_file,
            env_file=self.env_file,
            project_name="deliverynote",
            destination=self.destination,
            lock_file=self.root / "backup.lock",
        )
        self.fixed_time = datetime(2026, 7, 22, 18, 30, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temporary.cleanup()

    def test_successful_backup_is_completed_only_after_resume_and_validation(self):
        runner = FakeRunner()

        result = create_backup(
            self.config,
            runner=runner,
            now=lambda: self.fixed_time,
        )

        backup = self.destination / "20260722-183000"
        self.assertEqual(result["backup_directory"], str(backup))
        self.assertEqual(result["status"], "complete")
        self.assertTrue((backup / "READY").is_file())
        self.assertTrue((backup / "database.dump").is_file())
        self.assertTrue((backup / "delivery_data.tar.gz").is_file())
        self.assertTrue((backup / "SHA256SUMS").is_file())
        metadata = json.loads((backup / "BACKUP-METADATA.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(metadata["data_archive"]["files"], 1)
        self.assertEqual(metadata["active_jobs_before_maintenance"], 0)
        self.assertEqual((backup / "database.dump").stat().st_mode & 0o777, 0o600)

        stop_ingress = next(
            index
            for index, command in enumerate(runner.commands)
            if "stop" in command and command[-2:] == ("web", "api")
        )
        stop_worker = next(
            index
            for index, command in enumerate(runner.commands)
            if "stop" in command and command[-1] == "worker"
        )
        database_dump = next(
            index for index, command in enumerate(runner.commands) if "pg_dump" in command
        )
        resume = next(
            index for index, command in enumerate(runner.commands) if "up" in command
        )
        self.assertLess(stop_ingress, stop_worker)
        self.assertLess(stop_worker, database_dump)
        self.assertLess(database_dump, resume)

    def test_archive_failure_leaves_incomplete_marker_and_resumes_services(self):
        runner = FakeRunner(fail_archive=True)

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
        self.assertTrue(any("up" in command for command in runner.commands))

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
            _validate_data_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
