"""两个真实 Worker 共用 PostgreSQL 时，每个任务只执行一次有效领取。"""

import os
import unittest

from tests.support.worker_case import WorkerDockerCase
from tests.support.worker_docker import TASKS, wait_until


@unittest.skipUnless(
    os.getenv("WORKER_DOCKER_TESTS") == "1", "需显式开启隔离 Worker 演练"
)
class WorkerClaimDockerTests(WorkerDockerCase):
    def assert_single_claim(self, kind: str) -> None:
        fixture = self.fixture
        service = TASKS[kind][0]
        fixture.compose("stop", "--timeout", "5", service)
        fixture.arm(kind)
        identifier = self.enqueue(kind)
        competing = fixture.once(kind)
        fixture.compose("start", service)
        self.assertEqual(fixture.arrived(kind)["id"], identifier)
        running = fixture.job(kind, identifier)
        self.assertEqual((running["status"], running["attempts"]), ("running", 1))
        # 再次请求同一批次复用原任务，同步队列则明确拒绝重复发起。
        if kind == "compute":
            response = self.scenario.request(
                "POST", f"/api/batches/{running['batch_id']}/compute", 202
            )
            self.assertEqual(response.json()["id"], identifier)
        else:
            path = (
                "/api/purchase-sync"
                if kind == "purchase-sync"
                else "/api/self-operated-inbound-sync"
            )
            self.scenario.request("POST", path, 409)
        fixture.release(kind)
        wait_until(
            lambda: fixture.job(kind, identifier)["status"] == "succeeded",
            "竞争领取任务未完成",
        )
        wait_until(
            lambda: not fixture.state(competing)["Running"], "一次性 Worker 未退出"
        )
        self.assertEqual(fixture.state(competing)["ExitCode"], 0)
        self.assert_result(kind, identifier, 1)

    def test_batch_workers_claim_one_task_once(self) -> None:
        self.assert_single_claim("compute")

    def test_purchase_workers_claim_one_task_once(self) -> None:
        self.assert_single_claim("purchase-sync")

    def test_inbound_workers_claim_one_task_once(self) -> None:
        self.assert_single_claim("inbound-sync")
