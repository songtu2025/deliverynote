"""通过真实接口创建同步候选版本与使用 API 来源的批次。"""

from io import BytesIO
from pathlib import Path
import time
from typing import Any, cast

from openpyxl import load_workbook

from tests.support.api_docker import ApiDockerFixture
from tests.support.inbound_scenario import InboundScenario
from tests.support.worker import WorkerCase

SYNC = "/api/self-operated-inbound-sync"


class ApiScenario(InboundScenario):
    def __init__(self, url: str, root: Path) -> None:
        super().__init__(url, root)
        self.sync_jobs: list[dict[str, Any]] = []

    def sync(self, expected: str = "succeeded") -> dict[str, Any]:
        identifier = self.request("POST", SYNC, 201).json()["id"]
        deadline = time.monotonic() + 60
        while True:
            job = self.request("GET", SYNC).json()["job"]
            assert job["id"] == identifier
            if job["status"] == expected:
                self.sync_jobs.append(job)
                return cast(dict[str, Any], job)
            if job["status"] in {"succeeded", "blocked", "failed"}:
                raise AssertionError(f"同步状态与预期 {expected} 不符：{job}")
            if time.monotonic() >= deadline:
                raise AssertionError(f"同步未完成：{job}")
            time.sleep(0.1)

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
        self.request(
            "PUT",
            "/api/admin/integrations/gerpgo",
            json={
                "base_url": "http://erp-stub:8000",
                "app_id": "fixture-app",
                "app_key": "fixture-key",
            },
        )
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
        result["configuration"] = self.request(
            "GET", "/api/admin/integrations/gerpgo"
        ).json()
        result["sync_status"] = self.request("GET", SYNC).json()
        reports = {}
        for job in self.sync_jobs:
            prefix = f"{SYNC}/{job['id']}"
            issues = self.request("GET", prefix + "/issues").json()
            report = {"issues": issues}
            if job["candidate_version_id"] is not None:
                report["preview"] = self.request("GET", prefix + "/preview").json()
            if issues:
                workbook = load_workbook(
                    BytesIO(self.request("GET", prefix + "/issues/download").content),
                    data_only=True,
                )
                report["workbook"] = list(workbook.worksheets[0].values)
                workbook.close()
            reports[job["id"]] = report
        result["reports"] = reports
        return result
