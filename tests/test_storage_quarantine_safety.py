"""验证执行期间状态变化、跨文件系统拒绝和共享运维锁入口。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from delivery_note.web.models import Batch
from scripts.quarantine_files import move_without_replace
from tests.support.storage_quarantine import StorageQuarantineCase


class StorageQuarantineSafetyTests(StorageQuarantineCase):
    def test_partial_execution_can_be_restored_without_finishing_apply(self):
        before = self.contents()
        self.prepare()
        calls = 0

        def fail_second(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("模拟中断")
            move_without_replace(source, target)

        with (
            patch(
                "scripts.storage_quarantine.move_without_replace",
                side_effect=fail_second,
            ),
            self.assertRaises(OSError),
        ):
            self.apply()
        self.assertEqual(self.apply(restore=True)["moved_objects"], 1)
        self.assertEqual(self.contents(), before)

    def test_reference_added_between_moves_protects_remaining_file(self):
        plan = self.prepare()
        first = plan["entries"][0]["path"]
        remaining = plan["entries"][1]["path"]

        def add_reference(source, target):
            move_without_replace(source, target)
            with self.app.state.database.session() as session:
                batch = session.get(Batch, self.batch_id)
                batch.zip_path = str(self.storage / remaining)
                session.commit()

        with (
            patch(
                "scripts.storage_quarantine.move_without_replace",
                side_effect=add_reference,
            ),
            self.assertRaises(ValueError),
        ):
            self.apply()
        self.assertFalse((self.storage / first).exists())
        self.assertTrue((self.storage / remaining).exists())
        self.assertEqual(self.apply(restore=True)["moved_objects"], 1)

    def test_cross_filesystem_is_refused_before_creating_manifest(self):
        parent = self.quarantine_dir.parent
        parent.mkdir()
        original = Path.stat

        def other_device(path, *args, **kwargs):
            record = original(path, *args, **kwargs)
            if path == parent:
                fields = list(record)
                fields[2] += 1
                return os.stat_result(fields)
            return record

        with patch.object(Path, "stat", other_device), self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.quarantine_dir.exists())

    def test_atomic_directory_move_does_not_replace_existing_directory(self):
        target = self.root / "existing"
        target.mkdir()
        with self.assertRaises(FileExistsError):
            move_without_replace(self.old, target)
        self.assertTrue(self.old.is_dir())
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "命令行共享运维锁使用 Linux flock")
    def test_cli_prepare_apply_restore_share_operational_lock(self):
        base = [
            sys.executable,
            "-m",
            "scripts.storage_quarantine",
            "--database-url",
            self.url,
            "--storage-root",
            str(self.storage),
            "--directory",
            str(self.quarantine_dir),
            "--lock-file",
            str(self.root / "operation.lock"),
        ]
        for operation in ("prepare", "apply", "restore"):
            args = base + ["--" + operation]
            if operation == "prepare":
                for path in self.paths:
                    args += ["--path", path]
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)
