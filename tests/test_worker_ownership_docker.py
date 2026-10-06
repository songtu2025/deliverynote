"""旧执行者恢复后，不得覆盖新租约登记的真实业务结果。"""

import os
import unittest

from tests.support.worker_case import WorkerDockerCase
from tests.support.worker_docker import TASKS, wait_until


@unittest.skipUnless(
    os.getenv("WORKER_DOCKER_TESTS") == "1", "需显式开启隔离 Worker 演练"
)
class WorkerOwnershipDockerTests(WorkerDockerCase):
    def assert_old_owner_rejected(self, kind: str) -> None:
        historical = self.remember_history()
        fixture = self.fixture
        point = kind + ".finalize"
        fixture.arm(point)
        identifier = self.enqueue(kind)
        original = fixture.arrived(point)
        container = fixture.inspect(TASKS[kind][0])[0]["Id"]
        fixture.pause(container)
        fixture.expire(kind, identifier)
        self.assertEqual(fixture.recover(kind), 1)
        queued = fixture.job(kind, identifier)
        self.assertEqual((queued["status"], queued["attempts"]), ("queued", 1))
        self.assertIsNone(queued["claim_token"])
        fixture.release(point)
        fixture.arm(kind)
        replacement = fixture.once(kind)
        self.assertNotEqual(fixture.arrived(kind)["claim"], original["claim"])
        fixture.release(kind)
        wait_until(
            lambda: not fixture.state(replacement)["Running"], "替代 Worker 未完成"
        )
        self.assertEqual(fixture.state(replacement)["ExitCode"], 0)
        saved = self.assert_result(kind, identifier, 2)
        self.scenario.batch_id = int(saved.get("batch_id", historical["batch"]["id"]))
        outputs = self.scenario.downloads() if kind == "export" else None
        cache = fixture.cache() if kind == "purchase-sync" else None
        fixture.resume(container)
        fixture.run("docker", "kill", "--signal", "TERM", container)
        wait_until(lambda: not fixture.state(container)["Running"], "旧 Worker 未退出")
        self.assertEqual(fixture.state(container)["ExitCode"], 0)
        self.assertEqual(fixture.job(kind, identifier), saved)
        self.assert_result(kind, identifier, 2)
        if outputs is not None:
            self.assertEqual(self.scenario.downloads(), outputs)
        if cache is not None:
            self.assertEqual(fixture.cache(), cache)
        self.assert_history(historical)

    def test_old_compute_owner_cannot_overwrite_new_result(self) -> None:
        self.assert_old_owner_rejected("compute")

    def test_old_export_owner_cannot_remove_new_download(self) -> None:
        self.assert_old_owner_rejected("export")

    def test_old_purchase_owner_cannot_remove_new_candidate(self) -> None:
        self.assert_old_owner_rejected("purchase-sync")

    def test_old_inbound_owner_cannot_remove_new_candidate(self) -> None:
        self.assert_old_owner_rejected("inbound-sync")
