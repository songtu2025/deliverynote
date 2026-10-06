"""复用完整恢复流程并核对采购同步记录和私有缓存。"""

from pathlib import Path
from typing import Any, cast

from tests.support.business_case import RecoveryCase, sync_records
from tests.support.business_docker import BusinessDockerFixture
from tests.support.purchase_docker import PurchaseDockerFixture
from tests.support.purchase_scenario import PurchaseScenario


class PurchaseRecoveryCase(RecoveryCase):
    fixture_type = PurchaseDockerFixture
    scenario_type = PurchaseScenario
    fixture: PurchaseDockerFixture
    scenario: PurchaseScenario

    def create_baseline(self) -> None:
        self.scenario.create_api_baseline(self.fixture)

    def remember_source(self) -> None:
        super().remember_source()
        self.source_sync_records = sync_records(self.fixture, "purchase")
        self.source_cache = self.fixture.cache()

    def restored_scenario(
        self, target: BusinessDockerFixture, directory: Path
    ) -> PurchaseScenario:
        scenario = cast(PurchaseScenario, super().restored_scenario(target, directory))
        scenario.batch_ids = self.scenario.batch_ids.copy()
        scenario.sync_jobs = self.scenario.sync_jobs.copy()
        return scenario

    def assert_source_unchanged(self, snapshot: dict[str, Any]) -> None:
        super().assert_source_unchanged(snapshot)
        self.assertEqual(
            sync_records(self.fixture, "purchase"), self.source_sync_records
        )
        self.assertEqual(self.fixture.cache(), self.source_cache)
