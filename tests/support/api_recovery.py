"""复用自营仓恢复流程并比较完整 API 同步记录。"""

from pathlib import Path
from typing import Any, cast

from tests.support.api_docker import ApiDockerFixture
from tests.support.api_scenario import ApiScenario
from tests.support.business_case import sync_records
from tests.support.business_docker import BusinessDockerFixture
from tests.support.inbound_recovery import InboundRecoveryCase


class ApiRecoveryCase(InboundRecoveryCase):
    fixture_type = ApiDockerFixture
    scenario_type = ApiScenario
    fixture: ApiDockerFixture
    scenario: ApiScenario

    def create_baseline(self) -> None:
        self.scenario.create_api_baseline(self.fixture)

    def remember_source(self) -> None:
        super().remember_source()
        self.source_sync_records = sync_records(self.fixture)

    def restored_scenario(
        self, target: BusinessDockerFixture, directory: Path
    ) -> ApiScenario:
        scenario = cast(ApiScenario, super().restored_scenario(target, directory))
        scenario.sync_jobs = self.scenario.sync_jobs.copy()
        return scenario

    def assert_source_unchanged(self, snapshot: dict[str, Any]) -> None:
        super().assert_source_unchanged(snapshot)
        self.assertEqual(sync_records(self.fixture), self.source_sync_records)
