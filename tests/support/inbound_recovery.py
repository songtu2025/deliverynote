"""复用完整备份恢复，补充自营仓业务记录比较。"""

import json
from pathlib import Path
from typing import Any, cast

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
    scenario_type: type[InboundScenario] = InboundScenario

    def remember_source(self) -> None:
        super().remember_source()
        self.source_inbound_records = inbound_records(self.fixture)

    def create_baseline(self) -> None:
        self.scenario.create_inbound_baseline()

    def restored_scenario(
        self, target: BusinessDockerFixture, directory: Path
    ) -> InboundScenario:
        scenario = cast(InboundScenario, super().restored_scenario(target, directory))
        scenario.batch_ids = self.scenario.batch_ids.copy()
        return scenario

    def assert_source_unchanged(self, snapshot: dict[str, Any]) -> None:
        super().assert_source_unchanged(snapshot)
        self.assertEqual(inbound_records(self.fixture), self.source_inbound_records)
