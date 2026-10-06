"""通过真实模型和隔离文件验证只读审计分类及无写入约束。"""

import json
import subprocess
import sys
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from scripts.audit_storage import audit_storage, read_session
from delivery_note.web.models import (
    InputVersion,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)
from tests.support.storage_audit import StorageAuditCase


class StorageAuditTests(StorageAuditCase):
    def categories(self) -> dict[str, str]:
        report = audit_storage(self.url, self.storage)
        self.assertEqual(report["status"], "complete")
        return {entry["path"]: entry["category"] for entry in report["entries"]}

    def test_all_reference_fields_and_derived_merged_output_are_preserved(self) -> None:
        published = self.seed_outputs()
        categories = self.categories()
        self.assertTrue(categories)
        self.assertEqual(set(categories.values()), {"normal_reference"})
        self.assertEqual(categories["master/inactive.xlsx"], "normal_reference")
        self.assertEqual(categories["shared/inbound.xlsx"], "normal_reference")
        self.assertEqual(
            categories[
                (
                    published.relative_to(self.storage)
                    / f"batch-{self.batch_id}-merged.xlsx"
                ).as_posix()
            ],
            "normal_reference",
        )

    def test_missing_references_are_reported_and_paths_are_deduplicated(self) -> None:
        published = self.seed_outputs()
        archive = published / "batch.zip"
        archive.unlink()
        merged = published / f"batch-{self.batch_id}-merged.xlsx"
        merged.unlink()
        categories = self.categories()
        self.assertEqual(
            categories[archive.relative_to(self.storage).as_posix()],
            "missing_reference",
        )
        self.assertEqual(
            categories[merged.relative_to(self.storage).as_posix()], "missing_reference"
        )
        self.assertEqual(
            sum(value == "missing_reference" for value in categories.values()), 2
        )

    def test_known_unregistered_artifacts_are_suspected_residue(self) -> None:
        paths = self.candidates()
        categories = self.categories()
        for path in paths:
            self.assertEqual(
                categories[path.relative_to(self.storage).as_posix()],
                "suspected_residue",
            )

    def test_active_tasks_protect_unregistered_candidates(self) -> None:
        paths = self.candidates()
        with self.app.state.database.session() as session:
            session.add_all(
                [
                    Job(batch_id=self.batch_id, kind="export", status="running"),
                    PurchaseSyncJob(id=91, created_by=self.user_id, status="queued"),
                    SelfOperatedInboundSyncJob(
                        id=92, created_by=self.user_id, status="running"
                    ),
                ]
            )
            session.commit()
        categories = self.categories()
        for path in paths:
            self.assertEqual(
                categories[path.relative_to(self.storage).as_posix()], "active_task"
            )
        extra = self.file(
            "master/purchase/purchase_sync_93_积加采购数据_20261006_120000.xlsx"
        )
        self.assertEqual(
            self.categories()[extra.relative_to(self.storage).as_posix()],
            "suspected_residue",
        )

    def test_unknown_names_and_outside_references_are_not_classified_as_residue(
        self,
    ) -> None:
        self.file("cache/inspection.json")
        self.file("batches/1/exports/export-not-a-uuid/result.xlsx")
        outside = self.root / "outside.xlsx"
        outside.write_bytes(b"outside")
        with self.app.state.database.session() as session:
            version = session.scalar(
                select(InputVersion).where(InputVersion.kind == "purchase")
            )
            version.storage_path = outside.as_posix()
            session.commit()
        categories = self.categories()
        self.assertEqual(categories["cache/inspection.json"], "unknown")
        self.assertEqual(
            categories["batches/1/exports/export-not-a-uuid/result.xlsx"], "unknown"
        )
        self.assertEqual(categories[outside.as_posix()], "unknown")

    def test_symlink_targets_are_never_scanned(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "private.xlsx").write_bytes(b"private")
        link = self.storage / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("当前 Windows 账号没有创建符号链接权限")
        categories = self.categories()
        self.assertEqual(categories["linked"], "unknown")
        self.assertNotIn("linked/private.xlsx", categories)

    def test_repeated_cli_audits_do_not_write_database_or_storage(self) -> None:
        self.seed_outputs()
        self.candidates()
        before = self.snapshot_files()
        command = [
            sys.executable,
            "-B",
            "-m",
            "scripts.audit_storage",
            "--database-url",
            self.url,
            "--storage-root",
            str(self.storage),
        ]
        first = subprocess.check_output(command, text=True, encoding="utf-8")
        second = subprocess.check_output(command, text=True, encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["status"], "complete")
        self.assertEqual(self.snapshot_files(), before)
        with read_session(self.url) as session:
            with self.assertRaises(DatabaseError):
                session.execute(text("UPDATE batches SET name='不可写入'"))
        self.assertEqual(self.snapshot_files(), before)

    def test_unavailable_database_does_not_create_a_database_or_leak_credentials(
        self,
    ) -> None:
        missing = self.root / "missing.db"
        report = audit_storage(f"sqlite+pysqlite:///{missing.as_posix()}", self.storage)
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(missing.exists())
        secret = "never-emit-this-password"
        report = audit_storage(
            f"postgresql+missing_driver://admin:{secret}@localhost/test", self.storage
        )
        self.assertNotIn(secret, json.dumps(report))
        self.assertEqual(report["status"], "incomplete")

    def test_unreadable_reference_state_is_unknown(self) -> None:
        with patch(
            "scripts.audit_storage.read_snapshot", side_effect=OSError("不可读取")
        ):
            report = audit_storage(self.url, self.storage)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["counts"]["unknown"], 1)

    def test_sqlite_uri_preserves_chinese_spaces_and_fragment_characters(self) -> None:
        self.app.state.database.dispose()
        renamed = self.root / "只读数据库 #&版本.db"
        (self.root / "test.db").rename(renamed)
        report = audit_storage(f"sqlite+pysqlite:///{renamed.as_posix()}", self.storage)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["counts"]["missing_reference"], 0)

    def test_missing_storage_root_is_not_created(self) -> None:
        missing = self.root / "missing-storage"
        self.assertEqual(audit_storage(self.url, missing)["status"], "incomplete")
        self.assertFalse(missing.exists())
