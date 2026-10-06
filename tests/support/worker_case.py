"""Worker 故障演练共用真实任务创建、结果和历史保护断言。"""

from typing import Any

from tests.support.business_case import RecoveryCase
from tests.support.delivery_exports import assert_delivery_exports
from tests.support.sync_http import configure_sync, start_sync
from tests.support.worker_docker import TASKS, WorkerDockerFixture


class WorkerDockerCase(RecoveryCase):
    fixture_type = WorkerDockerFixture
    fixture: WorkerDockerFixture

    def setUp(self) -> None:
        super().setUp()
        self.scenario.login()
        self.scenario.activate_inputs()
        configure_sync(self.scenario)

    def enqueue(self, kind: str) -> int:
        if kind == "compute":
            return self.scenario.create_delivery_batch(wait=False)
        if kind == "export":
            self.scenario.create_delivery_batch()
            return self.scenario.export(wait=False)
        path = (
            "/api/purchase-sync"
            if kind == "purchase-sync"
            else "/api/self-operated-inbound-sync"
        )
        return int(start_sync(self.scenario, path, wait=False)["id"])

    def assert_result(
        self, kind: str, identifier: int, attempts: int
    ) -> dict[str, Any]:
        job = self.fixture.job(kind, identifier)
        self.assertEqual((job["status"], job["attempts"]), ("succeeded", attempts))
        self.assertIsNone(job["claim_token"])
        if TASKS[kind][0] == "worker":
            self.scenario.batch_id = int(job["batch_id"])
            summary = self.scenario.batch()["summary"]
            self.assertEqual(
                (
                    summary["delivery_total"],
                    summary["import_total"],
                    summary["manual_total"],
                ),
                (160, 100, 60),
            )
            action = f"worker_{kind}_succeeded"
            entity = int(job["batch_id"])
            if kind == "export":
                assert_delivery_exports(self, *self.scenario.downloads(), resolved=0)
                self.assertIsNotNone(job["output_path"])
        else:
            self.assertIsNone(job["active_slot"])
            self.assertIsNotNone(job["candidate_version_id"])
            candidate = next(
                version
                for version in self.scenario.request(
                    "GET", "/api/input-versions"
                ).json()
                if version["id"] == job["candidate_version_id"]
            )
            self.assertFalse(candidate["active"])
            self.scenario.request(
                "GET", f"/api/input-versions/{candidate['id']}/download"
            )
            action = (
                "purchase_sync"
                if kind == "purchase-sync"
                else "self_operated_inbound_sync"
            ) + "_succeeded"
            entity = identifier
        self.assertEqual(
            self.fixture.database_query(
                f"SELECT count(*) FROM audit_logs WHERE action='{action}' "
                f"AND entity_id='{entity}'"
            ),
            "1",
        )
        return job

    def remember_history(self) -> dict[str, Any]:
        self.scenario.create_delivery_batch()
        self.scenario.export()
        snapshot = self.scenario.snapshot()
        return {name: snapshot[name] for name in ("batch", "exceptions", "exports")}

    def assert_history(self, snapshot: dict[str, Any]) -> None:
        self.scenario.batch_id = int(snapshot["batch"]["id"])
        current = self.scenario.snapshot()
        for name in snapshot:
            self.assertEqual(current[name], snapshot[name])
