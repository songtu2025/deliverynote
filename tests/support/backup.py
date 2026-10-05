from __future__ import annotations

import io
import hashlib
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Sequence
from unittest.mock import patch
from urllib.parse import urlsplit

from scripts.backup.database import CRITICAL_TABLES, RESTORE_DATABASE_PATTERN
from scripts.backup.runtime import BackupConfig, BackupError
from scripts.backup.workflow import create_backup


class FakeRunner:
    web_contents = {
        "/index.html": b'<script src="/assets/app.js"></script>',
        "/assets/app.js": b"console.log('backup-test')",
    }

    @staticmethod
    def web_response(url: str, *, timeout: int) -> io.BytesIO:
        path = urlsplit(url).path
        if path.startswith("/health/"):
            return io.BytesIO(b'{"status":"ok"}')
        return io.BytesIO(
            FakeRunner.web_contents["/index.html" if path == "/" else path]
        )

    def __init__(
        self,
        *,
        failure: str | None = None,
        fail_compose_reconcile: bool = False,
        restored_counts: dict[str, int] | None = None,
    ) -> None:
        self.fail_archive = failure == "archive"
        self.fail_create_database = failure == "create_database"
        self.fail_restore = failure == "restore"
        self.fail_validation = failure == "validation"
        self.fail_drop_database = failure == "drop_database"
        self.fail_compose_reconcile = fail_compose_reconcile
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
        if command[:2] == ("docker", "exec") and "sha256sum" in command:
            path = command[-1].removeprefix("/usr/share/nginx/html")
            return hashlib.sha256(self.web_contents[path]).hexdigest() + "  " + path
        if command[:3] == ("docker", "volume", "ls"):
            return "deliverynote_delivery_data\n"
        if command[:2] == ("docker", "run"):
            return self._archive(command)
        if any(
            name in command
            for name in ("pg_dump", "createdb", "pg_restore", "dropdb", "psql")
        ):
            return self._database(command, stdin, stdout)
        return self._compose(command)

    def _fail(self, enabled: bool, message: str) -> None:
        if enabled:
            raise BackupError(message)

    def _database(
        self,
        command: tuple[str, ...],
        stdin: BinaryIO | None,
        stdout: BinaryIO | None,
    ) -> str:
        if "pg_dump" in command:
            if stdout is None:
                raise AssertionError("pg_dump 必须直接写入文件")
            stdout.write(b"PGDMP\x01\x0funit-test")
        elif "createdb" in command:
            self._fail(self.fail_create_database, "模拟临时数据库创建失败")
        elif "pg_restore" in command:
            if stdin is None:
                raise AssertionError("pg_restore 必须从数据库备份读取标准输入")
            self._fail(self.fail_restore, "模拟 pg_restore 失败")
            self.restored_payload = stdin.read()
        elif "dropdb" in command:
            self._fail(self.fail_drop_database, "模拟临时数据库清理失败")
        elif "psql" in command:
            return self._counts(command)
        return ""

    def _counts(self, command: tuple[str, ...]) -> str:
        query = command[command.index("-c") + 1]
        if "UNION ALL" not in query or "public.users" not in query:
            return "0\n"
        database = command[command.index("-d") + 1]
        self._fail(
            database != "delivery_note" and self.fail_validation, "模拟恢复库验证失败"
        )
        counts = (
            self.source_counts if database == "delivery_note" else self.restored_counts
        )
        return "".join(f"{table}={counts[table]}\n" for table in CRITICAL_TABLES)

    def _archive(self, command: tuple[str, ...]) -> str:
        if "tar" not in command:
            return ""
        self._fail(self.fail_archive, "模拟文件卷归档失败")
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

    def _compose(self, command: tuple[str, ...]) -> str:
        if "port" in command and command[-2:] == ("web", "80"):
            return "127.0.0.1:18080\n"
        self._fail(
            command[:2] == ("docker", "compose")
            and self.fail_compose_reconcile
            and ("up" in command or "start" in command),
            "模拟新 Compose 镜像尚不存在",
        )
        if "images" in command and "--quiet" in command:
            return f"sha256:{command[-1]}-image\n"
        if "ps" in command and "--quiet" in command:
            return f"deliverynote-{command[-1]}-1\n"
        if "ps" in command and "--status" in command and "--services" in command:
            return "db\napi\nworker\npurchase-sync-worker\ninbound-sync-worker\nweb\n"
        return ""


class BackupTestCase(unittest.TestCase):
    def setUp(self) -> None:
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
        self.web_requests = self.enterContext(
            patch(
                "scripts.web_verification.urlopen", side_effect=FakeRunner.web_response
            )
        )

    def tearDown(self) -> None:
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
