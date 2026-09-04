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
    CRITICAL_TABLES,
    RESTORE_DATABASE_PATTERN,
    SubprocessRunner,
    _validate_data_archive,
    create_backup,
    inspect_environment,
)


class FakeRunner:
    def __init__(
        self,
        *,
        fail_archive: bool = False,
        fail_create_database: bool = False,
        fail_restore: bool = False,
        fail_validation: bool = False,
        fail_drop_database: bool = False,
        restored_counts: dict[str, int] | None = None,
    ):
        self.fail_archive = fail_archive
        self.fail_create_database = fail_create_database
        self.fail_restore = fail_restore
        self.fail_validation = fail_validation
        self.fail_drop_database = fail_drop_database
        self.source_counts = {
            "users": 3,
            "input_versions": 7,
            "batches": 5,
            "batch_files": 8,
            "jobs": 2,
        }
        self.restored_counts = restored_counts or dict(self.source_counts)
        self.restored_payload: bytes | None = None
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: BinaryIO | None = None,
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
        if "createdb" in command:
            if self.fail_create_database:
                raise BackupError("模拟临时数据库创建失败")
            return ""
        if "pg_restore" in command:
            if stdin is None:
                raise AssertionError("pg_restore 必须从数据库备份读取标准输入")
            if self.fail_restore:
                raise BackupError("模拟 pg_restore 失败")
            self.restored_payload = stdin.read()
            return ""
        if "dropdb" in command:
            if self.fail_drop_database:
                raise BackupError("模拟临时数据库清理失败")
            return ""
        if command[:3] == ("docker", "volume", "ls"):
            return "deliverynote_delivery_data\n"
        if command[:2] == ("docker", "run"):
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
            return "db\napi\nworker\npurchase-sync-worker\ninbound-sync-worker\nweb\n"
        if "psql" in command:
            query = command[command.index("-c") + 1]
            if "UNION ALL" in query and "public.users" in query:
                database = command[command.index("-d") + 1]
                if database != "delivery_note" and self.fail_validation:
                    raise BackupError("模拟恢复库验证失败")
                counts = (
                    self.source_counts
                    if database == "delivery_note"
                    else self.restored_counts
                )
                return "".join(
                    f"{table}={counts[table]}\n" for table in CRITICAL_TABLES
                )
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

    def assert_failed_backup(self, runner: FakeRunner, message: str) -> Path:
        with self.assertRaisesRegex(BackupError, message):
            create_backup(
                self.config,
                runner=runner,
                now=lambda: self.fixed_time,
            )
        failed = list(self.destination.glob(".incomplete-20260722-183000-*"))
        self.assertEqual(len(failed), 1)
        self.assertTrue((failed[0] / "FAILED.txt").is_file())
        self.assertFalse((failed[0] / "READY").exists())
        for command in (item for item in runner.commands if "dropdb" in item):
            self.assertRegex(command[-1], RESTORE_DATABASE_PATTERN)
            self.assertNotEqual(command[-1], "delivery_note")
        return failed[0]

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
        metadata = json.loads(
            (backup / "BACKUP-METADATA.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(metadata["data_archive"]["files"], 1)
        self.assertEqual(metadata["active_jobs_before_maintenance"], 0)
        self.assertEqual(
            metadata["database"]["source_row_counts"],
            runner.source_counts,
        )
        self.assertEqual(
            metadata["database"]["restore_verification"],
            {
                "status": "passed",
                "restored_row_counts": runner.source_counts,
            },
        )
        self.assertTrue(result["database_restore_verified"])
        self.assertEqual((backup / "database.dump").stat().st_mode & 0o777, 0o600)

        stop_ingress = next(
            index
            for index, command in enumerate(runner.commands)
            if "stop" in command and command[-2:] == ("web", "api")
        )
        stop_worker = next(
            index
            for index, command in enumerate(runner.commands)
            if "stop" in command
            and command[-3:]
            == ("worker", "purchase-sync-worker", "inbound-sync-worker")
        )
        database_dump = next(
            index
            for index, command in enumerate(runner.commands)
            if "pg_dump" in command
        )
        resume = next(
            index for index, command in enumerate(runner.commands) if "up" in command
        )
        source_counts = next(
            index
            for index, command in enumerate(runner.commands)
            if "psql" in command
            and "UNION ALL" in command[command.index("-c") + 1]
            and command[command.index("-d") + 1] == "delivery_note"
        )
        create_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "createdb" in command
        )
        restore_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "pg_restore" in command
        )
        verify_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "psql" in command
            and "UNION ALL" in command[command.index("-c") + 1]
            and command[command.index("-d") + 1] != "delivery_note"
        )
        drop_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "dropdb" in command
        )
        temporary_database = runner.commands[create_database][-1]
        self.assertLess(stop_ingress, stop_worker)
        self.assertLess(stop_worker, source_counts)
        self.assertLess(source_counts, database_dump)
        self.assertLess(database_dump, resume)
        self.assertLess(resume, create_database)
        self.assertLess(create_database, restore_database)
        self.assertLess(restore_database, verify_database)
        self.assertLess(verify_database, drop_database)
        self.assertRegex(temporary_database, RESTORE_DATABASE_PATTERN)
        self.assertNotEqual(temporary_database, "delivery_note")
        self.assertEqual(
            runner.commands[restore_database][
                runner.commands[restore_database].index("-d") + 1
            ],
            temporary_database,
        )
        self.assertEqual(runner.commands[drop_database][-1], temporary_database)
        self.assertEqual(runner.restored_payload, b"PGDMP\x01\x0funit-test")

    def test_restore_count_mismatch_fails_and_drops_temporary_database(self):
        restored_counts = {
            "users": 3,
            "input_versions": 7,
            "batches": 4,
            "batch_files": 8,
            "jobs": 2,
        }
        runner = FakeRunner(restored_counts=restored_counts)

        self.assert_failed_backup(runner, "关键表行数.*不一致")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_pg_restore_failure_drops_temporary_database(self):
        runner = FakeRunner(fail_restore=True)

        self.assert_failed_backup(runner, "模拟 pg_restore 失败")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_restore_validation_failure_drops_temporary_database(self):
        runner = FakeRunner(fail_validation=True)

        self.assert_failed_backup(runner, "模拟恢复库验证失败")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_restore_database_creation_failure_still_attempts_drop(self):
        runner = FakeRunner(fail_create_database=True)

        self.assert_failed_backup(runner, "模拟临时数据库创建失败")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_restore_database_drop_failure_cannot_mark_backup_ready(self):
        runner = FakeRunner(fail_drop_database=True)

        failed = self.assert_failed_backup(runner, "临时恢复数据库清理失败")

        failure_marker = (failed / "FAILED.txt").read_text(encoding="utf-8")
        self.assertIn("模拟临时数据库清理失败", failure_marker)

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
