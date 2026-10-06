"""交货和自营仓演练共用真实服务与空恢复目标。"""

import os
import json
from pathlib import Path
import unittest
from typing import Any, Literal

from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from scripts.backup.services import REQUIRED_SERVICES
from scripts.backup.workflow import create_backup
from tests.support.business_docker import BusinessDockerFixture
from tests.support.business_scenario import DeliveryScenario


def sync_records(
    fixture: BusinessDockerFixture,
    kind: Literal["purchase", "self_operated_inbound"] = "self_operated_inbound",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(
        fixture.database_query(
            "SELECT COALESCE(json_agg(t), '[]'::json)::text FROM "
            f"(SELECT * FROM {kind}_sync_jobs ORDER BY id) t"
        )
    )
    return records


class RecoveryCase(unittest.TestCase):
    scenario: DeliveryScenario
    scenario_type: type[DeliveryScenario] = DeliveryScenario
    fixture_type: type[BusinessDockerFixture] = BusinessDockerFixture

    def setUp(self) -> None:
        self.fixture = self.fixture_type(
            os.environ["RELEASE_WEB_IMAGE"], os.environ["BACKUP_API_IMAGE"]
        )
        self.addCleanup(self.fixture.close)
        self.fixture.start()
        self.scenario = self.scenario_type(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

    def create_baseline(self) -> None:
        self.scenario.create_baseline()

    def backup_baseline(self) -> tuple[Path, dict[str, Any]]:
        self.scenario.login()
        self.create_baseline()
        snapshot = self.scenario.snapshot()
        self.remember_source()
        result = create_backup(self.fixture.config)
        self.assertEqual(result["status"], "complete")
        return Path(str(result["backup_directory"])), snapshot

    def restored_scenario(
        self, target: BusinessDockerFixture, directory: Path
    ) -> DeliveryScenario:
        target.restore_from(self.fixture, directory)
        scenario = self.scenario_type(target.url, target.root)
        self.addCleanup(scenario.client.close)
        self.assertEqual(scenario.login()["username"], "admin")
        scenario.batch_id = self.scenario.batch_id
        return scenario

    def empty_target(self) -> BusinessDockerFixture:
        target = self.fixture_type(
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

    def remember_source(self) -> None:
        self.source_counts = critical_table_counts(
            self.fixture.config, SubprocessRunner(), "delivery_note"
        )
        self.source_containers = {
            service: self.fixture.inspect(service)[0]["Id"]
            for service in REQUIRED_SERVICES
        }

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
