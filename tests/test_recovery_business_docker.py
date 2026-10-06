import json
import os
from pathlib import Path
import shutil
from typing import Any
import unittest
from unittest.mock import patch

from tests.support.business_docker import BusinessDockerFixture
from tests.support.business_case import RecoveryCase
from tests.support.business_scenario import DeliveryScenario
from tests.support.delivery_exports import assert_delivery_exports
from scripts.backup.workflow import create_backup
from scripts.backup.archive import sha256
from scripts.backup.database import _restore_database, critical_table_counts
from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.backup.services import REQUIRED_SERVICES


@unittest.skipUnless(
    os.environ.get("RECOVERY_BUSINESS_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 业务恢复演练",
)
class RecoveryBusinessDockerTests(RecoveryCase):
    def setUp(self) -> None:
        super().setUp()
        self.scenario = DeliveryScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

    def backup_baseline(self) -> tuple[Path, dict[str, Any]]:
        self.scenario.login()
        self.scenario.create_baseline()
        self.scenario.split_and_export()
        snapshot = self.scenario.snapshot()
        self.assertEqual(
            [
                (part["quantity"], part["resolved"])
                for part in snapshot["exceptions"][0]["parts"]
            ],
            [(25, True), (35, False)],
        )
        self.source_counts = critical_table_counts(
            self.fixture.config, SubprocessRunner(), "delivery_note"
        )
        self.source_containers = {
            service: self.fixture.inspect(service)[0]["Id"]
            for service in REQUIRED_SERVICES
        }
        result = create_backup(self.fixture.config)
        self.assertEqual(result["status"], "complete")
        return Path(str(result["backup_directory"])), snapshot

    def assert_source_unchanged(self, snapshot: dict[str, Any]) -> None:
        self.assertEqual(self.scenario.snapshot(), snapshot)
        self.assertEqual(
            critical_table_counts(
                self.fixture.config, SubprocessRunner(), "delivery_note"
            ),
            self.source_counts,
        )
        for service, identifier in self.source_containers.items():
            record = self.fixture.inspect(service)[0]
            self.assertEqual(record["Id"], identifier)
            self.assertEqual(record["State"]["Status"], "running")
            self.assertEqual(record["RestartCount"], 0)
        self.fixture.wait_ready()

    def test_complete_backup_restores_real_business_in_empty_environment(self) -> None:
        target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        self.assertEqual(
            critical_table_counts(target.config, SubprocessRunner(), "delivery_note"),
            self.source_counts,
        )
        self.assertEqual(restored.snapshot(), snapshot)
        assert_delivery_exports(self, *restored.downloads())
        self.assert_source_unchanged(snapshot)

    def restored_scenario(
        self, target: BusinessDockerFixture, directory: Path
    ) -> DeliveryScenario:
        target.restore_from(self.fixture, directory)
        restored = DeliveryScenario(target.url, target.root)
        self.addCleanup(restored.client.close)
        self.assertEqual(restored.login()["username"], "admin")
        restored.batch_id = self.scenario.batch_id
        return restored

    def test_restored_workers_regenerate_export_and_compute_new_batch(self) -> None:
        target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        query = f"SELECT zip_path FROM batches WHERE id={restored.batch_id}"
        old_archive = target.database_query(query)
        merged = Path(old_archive).with_name(f"batch-{restored.batch_id}-merged.xlsx")
        target.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            f"from pathlib import Path; p=Path({str(merged)!r}); "
            "assert p.is_relative_to("
            f"'/data/storage/batches/{restored.batch_id}/exports'); "
            "p.unlink()",
        )
        restored.request(
            "GET", f"/api/batches/{restored.batch_id}/download-merged", 404
        )
        restored.export()
        self.assertNotEqual(target.database_query(query), old_archive)
        self.assertEqual(
            restored.batch()["jobs"]["export"]["id"],
            snapshot["batch"]["jobs"]["export"]["id"],
        )
        assert_delivery_exports(self, *restored.downloads())
        restored.create_delivery_batch()
        batch = restored.batch()
        self.assertNotEqual(batch["id"], snapshot["batch"]["id"])
        self.assertEqual(batch["version_ids"], snapshot["batch"]["version_ids"])
        self.assertNotEqual(
            batch["jobs"]["compute"]["id"], snapshot["batch"]["jobs"]["compute"]["id"]
        )
        self.assertEqual(
            [(item["import_total"], item["manual_total"]) for item in batch["files"]],
            [(80, 0), (20, 60)],
        )
        restored.split_and_export()
        assert_delivery_exports(self, *restored.downloads())
        self.assert_source_unchanged(snapshot)

    def test_restore_failures_never_start_target_or_change_source(self) -> None:
        target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        with patch(
            "tests.support.business_restore._restore_database", wraps=_restore_database
        ) as restore:
            with self.assertRaisesRegex(BackupError, "独立空环境"):
                self.fixture.restore_from(self.fixture, directory)
            for attribute, value in (
                ("project", self.fixture.project),
                ("volume", self.fixture.volume),
                ("restore_target", False),
            ):
                with (
                    self.subTest(attribute=attribute),
                    patch.object(target, attribute, value),
                    self.assertRaisesRegex(BackupError, "独立空环境"),
                ):
                    target.restore_from(self.fixture, directory)
            for filename in ("database.dump", "delivery_data.tar.gz"):
                corrupted = target.root / filename
                shutil.copytree(directory, corrupted)
                path = corrupted / filename
                path.write_bytes(path.read_bytes() + b"corrupted")
                with (
                    self.subTest(filename=filename),
                    self.assertRaisesRegex(BackupError, "校验和或大小不一致"),
                ):
                    target.restore_from(self.fixture, corrupted)
            restore.assert_not_called()
        self.assertEqual(
            target.database_query(
                "SELECT datname FROM pg_database WHERE datname='delivery_note'",
                "postgres",
            ),
            "",
        )
        corrupted = target.root / "invalid-dump"
        shutil.copytree(directory, corrupted)
        dump = corrupted / "database.dump"
        dump.write_bytes(b"not a postgresql archive")
        metadata_path = corrupted / "BACKUP-METADATA.json"
        metadata = json.loads(metadata_path.read_text())
        original_digest = metadata["database"]["sha256"]
        metadata["database"].update(bytes=dump.stat().st_size, sha256=sha256(dump))
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        checksums = corrupted / "SHA256SUMS"
        checksums.write_text(
            checksums.read_text().replace(original_digest, sha256(dump)),
            encoding="utf-8",
        )
        with patch(
            "tests.support.business_restore._restore_database", wraps=_restore_database
        ) as restore:
            with self.assertRaisesRegex(BackupError, "pg_restore"):
                target.restore_from(self.fixture, corrupted)
            restore.assert_called_once()
        self.assertEqual(target.url, "")
        self.assertEqual(
            target.compose("ps", "--status", "running", "--services"), "db"
        )
        self.assert_source_unchanged(snapshot)

    def test_real_api_and_workers_compute_split_and_export_baseline(self) -> None:
        self.assertEqual(self.scenario.login()["username"], "admin")
        self.scenario.create_baseline()
        batch = self.scenario.batch()
        self.assertEqual(batch["status"], "succeeded")
        self.assertEqual(
            [(item["import_total"], item["manual_total"]) for item in batch["files"]],
            [(80, 0), (20, 60)],
        )
        self.scenario.split_and_export()
        assert_delivery_exports(self, *self.scenario.downloads())
        for service in ("api", "worker", "purchase-sync-worker", "inbound-sync-worker"):
            record = self.fixture.inspect(service)[0]
            self.assertEqual(record["State"]["Status"], "running")
            self.assertEqual(record["RestartCount"], 0)
            command = record["Config"]["Cmd"]
            self.assertIn(
                "delivery_note.web.api:create_app"
                if service == "api"
                else "delivery_note.worker",
                command,
            )
