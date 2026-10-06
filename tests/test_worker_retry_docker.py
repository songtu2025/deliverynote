"""连续真实中断达到上限后释放占用，并保留 API 手动重试能力。"""

import os
import unittest

from tests.support.worker_case import WorkerDockerCase
from tests.support.worker_docker import TASKS, wait_until


@unittest.skipUnless(
    os.getenv("WORKER_DOCKER_TESTS") == "1", "需显式开启隔离 Worker 演练"
)
class WorkerRetryDockerTests(WorkerDockerCase):
    def assert_retry_limit(self, kind: str) -> None:
        historical = self.remember_history()
        fixture = self.fixture
        fixture.arm(kind)
        identifier = self.enqueue(kind)
        service = TASKS[kind][0]
        container = fixture.inspect(service)[0]["Id"]
        claims = set()
        for attempt in range(1, 4):
            marker = fixture.arrived(kind)
            claims.add(marker["claim"])
            self.assertEqual(marker["id"], identifier)
            self.assertEqual(fixture.job(kind, identifier)["attempts"], attempt)
            fixture.run("docker", "kill", "--signal", "KILL", container)
            fixture.expire(kind, identifier)
            fixture.arm(kind)
            if attempt < 3:
                fixture.compose("start", service)
        self.assertEqual(len(claims), 3)
        fixture.release(kind)
        fixture.compose("start", service)
        wait_until(
            lambda: fixture.job(kind, identifier)["status"] == "failed",
            "未停止自动重试",
        )
        failed = fixture.job(kind, identifier)
        self.assertEqual(failed["attempts"], 3)
        self.assertIsNone(failed["claim_token"])
        self.assertIn("最大自动尝试次数", failed["error_message"])
        if kind == "compute":
            self.scenario.request(
                "POST", f"/api/batches/{failed['batch_id']}/compute", 202
            )
            retried = identifier
            attempts = 4
        else:
            self.assertIsNone(failed["active_slot"])
            self.assertIsNone(failed["candidate_version_id"])
            retried = self.enqueue(kind)
            self.assertNotEqual(retried, identifier)
            attempts = 1
        wait_until(
            lambda: fixture.job(kind, retried)["status"] == "succeeded",
            "手动重试未完成",
        )
        self.assert_result(kind, retried, attempts)
        self.assert_history(historical)

    def test_batch_retry_limit_allows_manual_retry(self) -> None:
        self.assert_retry_limit("compute")

    def test_purchase_retry_limit_releases_active_slot(self) -> None:
        self.assert_retry_limit("purchase-sync")

    def test_inbound_retry_limit_releases_active_slot(self) -> None:
        self.assert_retry_limit("inbound-sync")
