"""真实引用和文件验证隔离范围、恢复、漂移拒绝及失败后的继续执行。"""

import json
import os
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from delivery_note.web.models import Batch, Job
from scripts.backup.archive import sha256
from scripts.quarantine_files import inventory, move_without_replace
from scripts.storage_quarantine import prepare_quarantine
from tests.support.storage_quarantine import StorageQuarantineCase


class StorageQuarantineTests(StorageQuarantineCase):
    def test_prepare_only_writes_private_manifest_outside_business_storage(self):
        before, database = self.contents(), sha256(self.database_file)
        plan = self.prepare()
        self.assertEqual(len(plan["entries"]), 3)
        self.assertEqual(self.contents(), before)
        self.assertEqual(sha256(self.database_file), database)
        manifest = self.quarantine_dir / "manifest.json"
        self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), plan)
        if os.name == "posix":
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.quarantine_dir.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_apply_and_restore_preserve_content_ownership_permissions_and_database(
        self,
    ):
        before, database = self.contents(), sha256(self.database_file)
        states = {str(path): inventory(path) for path in (self.old, *self.extra)}
        self.prepare()
        result = self.apply()
        self.assertEqual(
            result, {"moved_objects": 3, "selected_objects": 3, "preserved_files": 4}
        )
        self.assertFalse(self.old.exists())
        self.assertTrue(self.current.is_dir())
        self.assertTrue((self.current / "batch.zip").is_file())
        self.assertTrue((self.storage / "cache/inspection.json").is_file())
        self.assertEqual(self.apply()["moved_objects"], 0)
        self.assertEqual(self.apply(restore=True)["moved_objects"], 3)
        self.assertEqual(self.apply(restore=True)["moved_objects"], 0)
        self.assertEqual(self.contents(), before)
        self.assertEqual(sha256(self.database_file), database)
        for name, state in states.items():
            self.assertEqual(inventory(Path(name)), state)

    def test_referenced_directory_file_and_unknown_are_rejected(self):
        for path in (
            self.current,
            self.current / "result0.xlsx",
            self.storage / "cache/inspection.json",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prepare_quarantine(
                    self.url,
                    self.storage,
                    [str(path.relative_to(self.storage))],
                    self.quarantine_dir,
                )
            self.assertFalse(self.quarantine_dir.exists())

    def test_paths_cannot_escape_overlap_duplicate_or_use_business_directory(self):
        selections = [
            [],
            ["../outside.xlsx"],
            [str(self.old)],
            [self.paths[0], self.paths[0]],
            [self.paths[0], self.paths[0] + "/旧结果.xlsx"],
        ]
        for paths in selections:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                prepare_quarantine(self.url, self.storage, paths, self.quarantine_dir)
        with self.assertRaises(ValueError):
            prepare_quarantine(
                self.url, self.storage, self.paths, self.storage / "quarantine"
            )

    def test_new_reference_refuses_entire_plan_before_any_moves(self):
        self.prepare()
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.zip_path = str(self.extra[0])
            session.commit()
        before = self.contents()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.contents(), before)

    def test_active_export_task_refuses_plan(self):
        self.prepare()
        with self.app.state.database.session() as session:
            job = session.scalar(select(Job).where(Job.batch_id == self.batch_id))
            job.status = "running"
            session.commit()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertTrue(self.old.exists())

    def test_changed_content_members_and_permissions_refuse_plan(self):
        self.prepare()
        directory_stat = self.old.stat()
        for change in ("content", "member", "mode"):
            with self.subTest(change=change):
                path = self.extra[1]
                original = path.read_bytes(), path.stat()
                if change == "content":
                    path.write_bytes(b"changed")
                elif change == "member":
                    (self.old / "new.xlsx").write_bytes(b"new")
                elif os.name == "posix":
                    path.chmod(0o600 if original[1].st_mode & 0o777 != 0o600 else 0o644)
                else:
                    continue
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertTrue(self.old.exists())
                path.write_bytes(original[0])
                path.chmod(original[1].st_mode & 0o777)
                os.utime(path, ns=(original[1].st_atime_ns, original[1].st_mtime_ns))
                if change == "member":
                    (self.old / "new.xlsx").unlink()
                    os.utime(
                        self.old,
                        ns=(directory_stat.st_atime_ns, directory_stat.st_mtime_ns),
                    )

    def test_existing_destination_is_never_overwritten(self):
        self.prepare()
        target = self.quarantine_dir / "artifacts" / self.paths[0]
        target.mkdir(parents=True)
        protected = target / "保护.xlsx"
        protected.write_bytes(b"protected")
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(protected.read_bytes(), b"protected")
        self.assertTrue(self.old.exists())

    def test_interrupted_move_can_resume_or_restore_with_original_manifest(self):
        before = self.contents()
        self.prepare()
        calls = 0

        def fail_second(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("模拟第二次移动失败")
            move_without_replace(source, target)

        with (
            patch(
                "scripts.storage_quarantine.move_without_replace",
                side_effect=fail_second,
            ),
            self.assertRaises(OSError),
        ):
            self.apply()
        self.assertEqual(self.apply()["moved_objects"], 2)
        self.assertEqual(self.apply(restore=True)["moved_objects"], 3)
        self.assertEqual(self.contents(), before)

    def test_restore_refuses_new_source_and_modified_quarantine_file(self):
        self.prepare()
        self.apply()
        self.extra[0].write_bytes(b"new source")
        with self.assertRaises(ValueError):
            self.apply(restore=True)
        self.assertEqual(self.extra[0].read_bytes(), b"new source")
        self.extra[0].unlink()
        isolated = self.quarantine_dir / "artifacts" / self.paths[1]
        isolated.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            self.apply(restore=True)
        self.assertFalse(self.old.exists())

    def test_symlink_members_and_ancestors_are_rejected(self):
        outside = self.root / "outside.xlsx"
        outside.write_bytes(b"outside")
        link = self.old / "link.xlsx"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("当前账号不能创建符号链接")
        with self.assertRaises(ValueError):
            self.prepare()
        link.unlink()
        self.prepare()
        artifacts = self.quarantine_dir / "artifacts"
        artifacts.symlink_to(self.storage, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.apply()

    def test_atomic_move_refuses_a_destination_created_after_precheck(self):
        source = self.extra[0]
        target = self.root / "target.xlsx"
        target.write_bytes(b"protected")
        with self.assertRaises(FileExistsError):
            move_without_replace(source, target)
        self.assertTrue(source.is_file())
        self.assertEqual(target.read_bytes(), b"protected")
