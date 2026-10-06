"""通过真实接口创建同步候选版本与使用 API 来源的批次。"""

from pathlib import Path
from typing import Any, cast

from tests.support.api_docker import ApiDockerFixture
from tests.support.inbound_scenario import InboundScenario
from tests.support.sync_http import configure_sync, start_sync, sync_snapshot
from tests.support.worker import WorkerCase

SYNC = "/api/self-operated-inbound-sync"


class ApiScenario(InboundScenario):
    def __init__(self, url: str, root: Path) -> None:
        super().__init__(url, root)
        self.sync_jobs: list[dict[str, Any]] = []

    def sync(self, expected: str = "succeeded") -> dict[str, Any]:
        job = start_sync(self, SYNC, expected)
        self.sync_jobs.append(job)
        return job

    def activate(self, job: dict[str, Any], expected: int = 200) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.request("POST", f"{SYNC}/{job['id']}/activate", expected).json(),
        )

    def create_api_batch(self) -> None:
        path = WorkerCase.create_self_operated_delivery(
            self.root / "260817-狂飙-API质检交货单.xlsx", 18
        )
        with path.open("rb") as upload:
            self.batch_id = self.request(
                "POST",
                "/api/self-operated-batches",
                201,
                data={"name": "恢复 API 来源批次"},
                files={"delivery_file": (path.name, upload)},
            ).json()["id"]
        self.batch_ids.append(self.batch_id)
        self.request("POST", f"/api/batches/{self.batch_id}/preflight")
        job = self.request("POST", f"/api/batches/{self.batch_id}/compute", 202)
        self.wait_job(job.json()["id"])
        self.export()

    def create_api_baseline(self, fixture: ApiDockerFixture) -> None:
        self.activate_inputs()
        self.request(
            "POST",
            "/api/self-operated-overreceipt-rule-versions",
            201,
            json={"name": "API 恢复超收5件", "allowance": 5},
        )
        configure_sync(self)
        self.activate(self.sync())
        self.create_api_batch()
        fixture.set_case(12)
        self.sync()
        fixture.set_case(12, warning=True)
        self.sync()
        fixture.set_case(12, blocked=True)
        self.sync("blocked")

    def snapshot(self) -> dict[str, Any]:
        result = super().snapshot()
        result.update(sync_snapshot(self, SYNC, self.sync_jobs))
        return result
