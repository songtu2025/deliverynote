"""以真实采购候选版本驱动供应商交货批次。"""

from pathlib import Path
from typing import Any, cast

from tests.support.business_scenario import DeliveryScenario
from tests.support.purchase_docker import PurchaseDockerFixture
from tests.support.sync_http import configure_sync, start_sync, sync_snapshot

SYNC = "/api/purchase-sync"


class PurchaseScenario(DeliveryScenario):
    def __init__(self, url: str, root: Path) -> None:
        super().__init__(url, root)
        self.sync_jobs: list[dict[str, Any]] = []
        self.batch_ids: list[int] = []

    def sync(self, expected: str = "succeeded") -> dict[str, Any]:
        job = start_sync(self, SYNC, expected)
        self.sync_jobs.append(job)
        return job

    def activate(self, job: dict[str, Any], expected: int = 200) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.request(
                "POST",
                f"/api/input-versions/{job['candidate_version_id']}/activate",
                expected,
            ).json(),
        )

    def create_api_batch(self) -> None:
        self.create_delivery_batch()
        self.batch_ids.append(self.batch_id)
        self.export()

    def create_api_baseline(self, fixture: PurchaseDockerFixture) -> None:
        self.activate_inputs()
        configure_sync(self)
        fixture.set_case(100)
        self.activate(self.sync())
        self.create_api_batch()
        fixture.set_case(120)
        self.sync()
        fixture.set_case(120, warning=True)
        self.sync()
        fixture.set_case(120, blocked=True)
        self.sync("blocked")

    def snapshot(self) -> dict[str, Any]:
        current = self.batch_id
        batches = {}
        for identifier in self.batch_ids:
            self.batch_id = identifier
            batches[identifier] = super().snapshot()
        self.batch_id = current
        versions = self.request("GET", "/api/input-versions").json()
        return {
            "batches": batches,
            "versions": versions,
            "input_files": {
                version["id"]: self.request(
                    "GET", f"/api/input-versions/{version['id']}/download"
                ).content
                for version in versions
            },
            **sync_snapshot(self, SYNC, self.sync_jobs),
        }
