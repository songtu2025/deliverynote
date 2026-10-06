"""复用完整备份恢复，补充自营仓业务记录比较。"""

import json
from pathlib import Path
from typing import Any

from scripts.backup.workflow import create_backup
from tests.support.business_case import RecoveryCase
from tests.support.business_docker import BusinessDockerFixture
from tests.support.inbound_scenario import InboundScenario


def inbound_records(fixture: BusinessDockerFixture) -> dict[str, Any]:
    records = {}
    for table, key in (
        ("self_operated_batches", "batch_id"),
        ("self_operated_overreceipt_rule_versions", "id"),
        ("self_operated_site_resolutions", "id"),
    ):
        records[table] = json.loads(
            fixture.database_query(
                f"SELECT COALESCE(json_agg(t), '[]'::json)::text "
                f"FROM (SELECT * FROM {table} ORDER BY {key}) t"
            )
        )
    return records


class InboundRecoveryCase(RecoveryCase):
    scenario: InboundScenario

    def setUp(self) -> None:
        super().setUp()
        self.scenario = InboundScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

    def backup_baseline(self) -> tuple[Path, dict[str, Any]]:
        self.scenario.login()
        self.scenario.create_inbound_baseline()
        snapshot = self.scenario.snapshot()
        self.remember_source()
        self.source_inbound_records = inbound_records(self.fixture)
        result = create_backup(self.fixture.config)
        self.assertEqual(result["status"], "complete")
        return Path(str(result["backup_directory"])), snapshot

    def restored_scenario(
        self, target: BusinessDockerFixture, directory: Path
    ) -> InboundScenario:
        target.restore_from(self.fixture, directory)
        scenario = InboundScenario(target.url, target.root)
        self.addCleanup(scenario.client.close)
        self.assertEqual(scenario.login()["username"], "admin")
        scenario.batch_ids = self.scenario.batch_ids.copy()
        return scenario

    def assert_source_unchanged(self, snapshot: dict[str, Any]) -> None:
        super().assert_source_unchanged(snapshot)
        self.assertEqual(inbound_records(self.fixture), self.source_inbound_records)
