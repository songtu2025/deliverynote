"""采购和待入库演练共用的真实同步请求与问题报告快照。"""

from io import BytesIO
import time
from typing import Any, cast

from openpyxl import load_workbook

from tests.support.business_scenario import DeliveryScenario


def configure_sync(scenario: DeliveryScenario) -> None:
    scenario.request(
        "PUT",
        "/api/admin/integrations/gerpgo",
        json={
            "base_url": "http://erp-stub:8000",
            "app_id": "fixture-app",
            "app_key": "fixture-key",
        },
    )


def start_sync(
    scenario: DeliveryScenario,
    path: str,
    expected: str = "succeeded",
    *,
    wait: bool = True,
) -> dict[str, Any]:
    created = scenario.request("POST", path, 201).json()
    identifier = created["id"]
    if not wait:
        return cast(dict[str, Any], created)
    deadline = time.monotonic() + 60
    while True:
        job = scenario.request("GET", path).json()["job"]
        assert job["id"] == identifier
        if job["status"] == expected:
            return cast(dict[str, Any], job)
        if job["status"] in {"succeeded", "blocked", "failed"}:
            raise AssertionError(f"同步状态与预期 {expected} 不符：{job}")
        if time.monotonic() >= deadline:
            raise AssertionError(f"同步未完成：{job}")
        time.sleep(0.1)


def sync_snapshot(
    scenario: DeliveryScenario, path: str, jobs: list[dict[str, Any]]
) -> dict[str, Any]:
    reports = {}
    for job in jobs:
        prefix = f"{path}/{job['id']}"
        issues = scenario.request("GET", prefix + "/issues").json()
        report = {"issues": issues}
        if job["candidate_version_id"] is not None:
            report["preview"] = scenario.request("GET", prefix + "/preview").json()
        if issues:
            workbook = load_workbook(
                BytesIO(scenario.request("GET", prefix + "/issues/download").content),
                data_only=True,
            )
            report["workbook"] = list(workbook.worksheets[0].values)
            workbook.close()
        reports[job["id"]] = report
    return {
        "configuration": scenario.request(
            "GET", "/api/admin/integrations/gerpgo"
        ).json(),
        "sync_status": scenario.request("GET", path).json(),
        "reports": reports,
    }
