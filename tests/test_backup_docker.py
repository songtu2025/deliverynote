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
from scripts.backup.resources import extract_resource_archive
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
        self.restore_volumes = self.fixture.run(
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            "name=deliverynote-resource-restore-",
        )
        self.resource_state = self.runtime_state()

    def runtime_state(self) -> str:
        return self.fixture.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import hashlib,json; from pathlib import Path; "
            "paths=[Path('/data/storage/config/gerpgo.json'),"
            "Path('/data/storage/cache/purchase-details-v1.json')]; "
            "print(json.dumps({str(p):[hashlib.sha256(p.read_bytes()).hexdigest(),"
            "p.stat().st_mode,p.stat().st_uid,p.stat().st_gid] for p in paths}))",
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
        self.assertEqual(self.runtime_state(), self.resource_state)
        self.assertEqual(
            fixture.run(
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                "name=deliverynote-resource-restore-",
            ),
            self.restore_volumes,
        )

    def test_real_database_and_file_volume_backup_restore_all_seven_tables(
        self,
    ) -> None:
        result = create_backup(self.fixture.config, runner=self.runner)
        directory = Path(str(result["backup_directory"]))
        metadata = json.loads((directory / "BACKUP-METADATA.json").read_text())
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["database_restore_verified"])
        self.assertTrue((directory / "READY").is_file())
        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(
            metadata["application_image"]["id"], self.fixture.inspect("api")[0]["Image"]
        )
        resources = metadata["resources"]
        self.assertEqual(resources["status"], "passed")
        self.assertEqual(resources["source"], resources["restored"])
        self.assertEqual(len(resources["restored"]), 4)
        self.assertTrue(
            all(
                entry["validation"] == "passed"
                for entry in resources["restored"].values()
            )
        )
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
            self.assertEqual((directory / name).stat().st_uid, os.getuid())
            self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)
        with tarfile.open(directory / "delivery_data.tar.gz", "r:gz") as archive:
            for name, expected in FILES.items():
                stream = archive.extractfile("./" + name)
                self.assertIsNotNone(stream)
                assert stream is not None
                with stream:
                    self.assertEqual(stream.read(), expected)
        self.assert_source_and_services_unchanged()

    def assert_tampered_restore(self, script: str, message: str) -> None:
        fixture = self.fixture

        def tamper(
            config: BackupConfig, runner: Runner, image: str, archive: Path, volume: str
        ) -> None:
            self.assertTrue(volume.startswith("deliverynote-resource-restore-"))
            self.assertNotEqual(volume, fixture.volume)
            extract_resource_archive(config, runner, image, archive, volume)
            runner.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--volume",
                    f"{volume}:/data",
                    image,
                    "python",
                    "-c",
                    script,
                ]
            )

        with patch(
            "scripts.backup.resources.extract_resource_archive", side_effect=tamper
        ):
            with self.assertRaisesRegex(BackupError, message):
                create_backup(fixture.config, runner=self.runner)
        self.assertFalse(any(fixture.config.destination.glob("*/READY")))
        incomplete = list(fixture.config.destination.glob(".incomplete-*"))
        self.assertEqual(len(incomplete), 1)
        self.assertTrue((incomplete[0] / "FAILED.txt").is_file())
        self.assert_source_and_services_unchanged()

    def test_same_size_valid_config_tampering_cannot_mark_ready(self) -> None:
        self.assert_tampered_restore(
            "from pathlib import Path; p=Path('/data/storage/config/gerpgo.json'); "
            "p.write_bytes(p.read_bytes().replace("
            "b'backup-private-key', b'broken-private-key'))",
            "资源恢复结果与快照不一致",
        )

    def test_corrupt_cache_in_actual_restored_volume_cannot_mark_ready(self) -> None:
        self.assert_tampered_restore(
            "from pathlib import Path; "
            "Path('/data/storage/cache/purchase-details-v1.json').write_text('[]')",
            "资源校验失败",
        )

    def test_cache_source_mismatch_in_actual_restored_volume_cannot_mark_ready(
        self,
    ) -> None:
        self.assert_tampered_restore(
            "import json; from pathlib import Path; "
            "p=Path('/data/storage/cache/purchase-details-v1.json'); "
            "v=json.loads(p.read_text()); v['source_identity']='wrong'; "
            "p.write_text(json.dumps(v))",
            "资源校验失败",
        )

    def test_changed_config_permissions_in_restored_volume_cannot_mark_ready(
        self,
    ) -> None:
        self.assert_tampered_restore(
            "from pathlib import Path; "
            "Path('/data/storage/config/gerpgo.json').chmod(0o644)",
            "资源恢复结果与快照不一致",
        )

    def test_relative_config_symlink_in_restored_volume_cannot_mark_ready(self) -> None:
        self.assert_tampered_restore(
            "from pathlib import Path; p=Path('/data/storage/config/gerpgo.json'); "
            "p.rename(p.with_suffix('.private')); p.symlink_to('gerpgo.private')",
            "资源校验失败",
        )

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
