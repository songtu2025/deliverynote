import os
from pathlib import Path
from typing import Any
import unittest

from tests.support.business_docker import BusinessDockerFixture
from tests.support.business_scenario import DeliveryScenario
from tests.support.delivery_exports import assert_delivery_exports
from scripts.backup.workflow import create_backup
from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from scripts.backup.services import REQUIRED_SERVICES


@unittest.skipUnless(
    os.environ.get("RECOVERY_BUSINESS_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 业务恢复演练",
)
class RecoveryBusinessDockerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = BusinessDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"], os.environ["BACKUP_API_IMAGE"]
        )
        self.addCleanup(self.fixture.close)
        self.fixture.start()
        self.scenario = DeliveryScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

    def empty_target(self) -> BusinessDockerFixture:
        target = BusinessDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"],
            os.environ["BACKUP_API_IMAGE"],
            restore_target=True,
        )
        self.addCleanup(target.close)
        target.start()
        self.assertEqual(
            target.database_query(
                "SELECT datname FROM pg_database WHERE datname='delivery_note'",
                "postgres",
            ),
            "",
        )
        self.assertEqual(
            target.compose("ps", "--status", "running", "--services"), "db"
        )
        return target

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
        target.restore_from(self.fixture, directory)
        restored = DeliveryScenario(target.url, target.root)
        self.addCleanup(restored.client.close)
        self.assertEqual(restored.login()["username"], "admin")
        restored.batch_id = self.scenario.batch_id
        self.assertEqual(
            critical_table_counts(target.config, SubprocessRunner(), "delivery_note"),
            self.source_counts,
        )
        self.assertEqual(restored.snapshot(), snapshot)
        assert_delivery_exports(self, *restored.downloads())
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
