import hashlib
import json
import os
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from scripts.backup.database import (
    RESTORE_DATABASE_PATTERN,
    _restore_database,
    critical_table_counts,
)
from scripts.backup.runtime import BackupConfig, BackupError, Runner, SubprocessRunner
from scripts.backup.services import REQUIRED_SERVICES
from scripts.backup.workflow import create_backup
from tests.support.backup_docker import FILES, BackupDockerFixture


@unittest.skipUnless(
    os.environ.get("BACKUP_DOCKER_TESTS") == "1", "需显式启用隔离 Docker 备份演练"
)
class BackupDockerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = BackupDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"], os.environ["BACKUP_API_IMAGE"]
        )
        self.addCleanup(self.fixture.close)
        try:
            self.fixture.start()
        except Exception:
            print(self.fixture.compose("logs", "--tail", "20", "api", "web", "db"))
            raise
        self.runner = SubprocessRunner()
        self.before = {
            service: self.fixture.inspect(service)[0]["Id"]
            for service in REQUIRED_SERVICES
        }
        self.counts = critical_table_counts(
            self.fixture.config, self.runner, "delivery_note"
        )

    def assert_source_and_services_unchanged(self) -> None:
        fixture = self.fixture
        for service, identifier in self.before.items():
            record = fixture.inspect(service)[0]
            self.assertEqual(record["Id"], identifier)
            self.assertEqual(record["State"]["Status"], "running")
        self.assertEqual(
            critical_table_counts(fixture.config, self.runner, "delivery_note"),
            self.counts,
        )
        self.assertEqual(
            fixture.database_query(
                "SELECT datname FROM pg_database "
                "WHERE datname LIKE 'delivery_note_restore_%'"
            ),
            "",
        )
        fixture.wait_ready()

    def test_real_database_and_file_volume_backup_restore_all_seven_tables(
        self,
    ) -> None:
        result = create_backup(self.fixture.config, runner=self.runner)
        directory = Path(str(result["backup_directory"]))
        metadata = json.loads((directory / "BACKUP-METADATA.json").read_text())
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["database_restore_verified"])
        self.assertTrue((directory / "READY").is_file())
        self.assertEqual(len(self.counts), 7)
        self.assertTrue(all(count > 0 for count in self.counts.values()))
        database = metadata["database"]
        self.assertEqual(database["source_row_counts"], self.counts)
        self.assertEqual(
            database["restore_verification"]["restored_row_counts"], self.counts
        )
        for entry, name in (
            (database, "database.dump"),
            (metadata["data_archive"], "delivery_data.tar.gz"),
        ):
            self.assertEqual(
                entry["sha256"],
                hashlib.sha256((directory / name).read_bytes()).hexdigest(),
            )
        with tarfile.open(directory / "delivery_data.tar.gz", "r:gz") as archive:
            for name, expected in FILES.items():
                stream = archive.extractfile("./" + name)
                self.assertIsNotNone(stream)
                assert stream is not None
                with stream:
                    self.assertEqual(stream.read(), expected)
        self.assert_source_and_services_unchanged()

    def test_missing_sync_rows_in_actual_restore_database_cannot_mark_ready(
        self,
    ) -> None:
        fixture = self.fixture

        def tamper(
            config: BackupConfig, runner: Runner, path: Path, database: str
        ) -> None:
            self.assertRegex(database, RESTORE_DATABASE_PATTERN)
            self.assertNotEqual(database, "delivery_note")
            _restore_database(config, runner, path, database)
            fixture.database_query("DELETE FROM purchase_sync_jobs", database)

        with patch("scripts.backup.database._restore_database", side_effect=tamper):
            with self.assertRaisesRegex(BackupError, "不一致.*purchase_sync_jobs"):
                create_backup(fixture.config, runner=self.runner)
        incomplete = list(fixture.config.destination.glob(".incomplete-*"))
        self.assertEqual(len(incomplete), 1)
        self.assertTrue((incomplete[0] / "FAILED.txt").is_file())
        self.assertFalse(any(fixture.config.destination.glob("*/READY")))
        self.assert_source_and_services_unchanged()
