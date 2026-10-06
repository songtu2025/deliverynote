"""交货和自营仓演练共用真实服务与空恢复目标。"""

import os
import unittest
from typing import Any

from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from scripts.backup.services import REQUIRED_SERVICES
from tests.support.business_docker import BusinessDockerFixture
from tests.support.business_scenario import DeliveryScenario


class RecoveryCase(unittest.TestCase):
    scenario: DeliveryScenario

    def setUp(self) -> None:
        self.fixture = BusinessDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"], os.environ["BACKUP_API_IMAGE"]
        )
        self.addCleanup(self.fixture.close)
        self.fixture.start()

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
