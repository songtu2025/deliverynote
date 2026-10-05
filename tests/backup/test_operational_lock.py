from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.backup.runtime import exclusive_lock
from scripts.backup_deliverynote import build_parser
from scripts.release_web import ReleaseConfig
from tests.support.backup import BackupTestCase


@unittest.skipUnless(os.name == "posix", "共享运维锁需要 Linux flock")
class OperationalLockTests(BackupTestCase):
    def run_child(self, operation: str) -> subprocess.CompletedProcess[str]:
        source = """
import sys
from pathlib import Path
from scripts.backup.runtime import BackupConfig, SubprocessRunner, exclusive_lock
from scripts.backup.workflow import create_backup
from scripts.release_web import ReleaseConfig, publish_web
root, operation = Path(sys.argv[1]), sys.argv[2]
lock = root / 'backup.lock'
if operation == 'backup':
    create_backup(BackupConfig(root/'compose.yaml', root/'.env', 'deliverynote',
                              root/'backups', lock))
elif operation == 'release':
    publish_web(ReleaseConfig(root, root/'compose.yaml', root/'.env', 'deliverynote',
                             'unused-image', '1'*40, 'http://127.0.0.1',
                             lock_file=lock),
                runner=SubprocessRunner())
else:
    with exclusive_lock(lock):
        print('lock acquired')
"""
        return subprocess.run(
            [sys.executable, "-c", source, str(self.root), operation],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_backup_and_release_refuse_shared_lock_before_any_commands(self) -> None:
        with exclusive_lock(self.config.lock_file):
            for operation in ("backup", "release"):
                with self.subTest(operation=operation):
                    result = self.run_child(operation)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("已有备份任务正在运行", result.stderr)
                    self.assertFalse(self.destination.exists())

    def test_lock_is_released_after_exception(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "模拟持锁任务失败"):
            with exclusive_lock(self.config.lock_file):
                self.assertEqual(self.config.lock_file.stat().st_mode & 0o777, 0o600)
                raise RuntimeError("模拟持锁任务失败")
        result = self.run_child("lock")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("lock acquired", result.stdout)

    def test_backup_and_release_defaults_use_same_lock(self) -> None:
        arguments = build_parser().parse_args(["--destination", str(self.destination)])
        config = ReleaseConfig(
            self.root,
            self.compose_file,
            self.env_file,
            "deliverynote",
            "unused-image",
            "1" * 40,
            "http://127.0.0.1",
        )
        self.assertEqual(arguments.lock_file, config.lock_file)
