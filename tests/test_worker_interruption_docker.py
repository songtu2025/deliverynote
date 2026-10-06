"""真实业务执行完成但尚未提交时，强制中断并重新领取任务。"""

import os
import unittest

from tests.support.worker_case import WorkerDockerCase
from tests.support.worker_docker import TASKS, wait_until


@unittest.skipUnless(
    os.getenv("WORKER_DOCKER_TESTS") == "1", "需显式开启隔离 Worker 演练"
)
class WorkerInterruptionDockerTests(WorkerDockerCase):
    def assert_interruption(self, kind: str) -> None:
        historical = self.remember_history()
        fixture = self.fixture
        point = kind + ".finalize"
        fixture.arm(point)
        identifier = self.enqueue(kind)
        original = fixture.arrived(point)
        first = fixture.job(kind, identifier)
        self.assertEqual((first["status"], first["attempts"]), ("running", 1))
        self.assertEqual(first["claim_token"], original["claim"])
        service = TASKS[kind][0]
        container = fixture.inspect(service)[0]["Id"]
        fixture.run("docker", "kill", "--signal", "KILL", container)
        self.assertFalse(fixture.state(container)["Running"])
        self.assertEqual(fixture.state(container)["ExitCode"], 137)
        stopped = fixture.job(kind, identifier)
        self.assertEqual(fixture.recover(kind), 0)
        self.assertEqual(fixture.job(kind, identifier), stopped)
        if kind == "compute":
            self.assertEqual(
                fixture.database_query(
                    "SELECT sum(import_total+manual_total) FROM batch_files "
                    f"WHERE batch_id={first['batch_id']}"
                ),
                "0",
            )
            self.assertEqual(
                fixture.database_query(
                    "SELECT count(*) FROM exceptions e JOIN batch_files f "
                    f"ON e.batch_file_id=f.id WHERE f.batch_id={first['batch_id']}"
                ),
                "0",
            )
        elif kind == "export":
            self.assertIsNone(stopped["output_path"])
        else:
            self.assertIsNone(stopped["candidate_version_id"])
        fixture.expire(kind, identifier)
        fixture.arm(point)
        fixture.compose("start", service)
        replacement = fixture.arrived(point)
        self.assertNotEqual(replacement["claim"], original["claim"])
        retried = fixture.job(kind, identifier)
        self.assertEqual((retried["status"], retried["attempts"]), ("running", 2))
        self.assertEqual(retried["claim_token"], replacement["claim"])
        fixture.release(point)
        wait_until(
            lambda: fixture.job(kind, identifier)["status"] == "succeeded",
            "重新领取任务未完成",
        )
        self.assert_result(kind, identifier, 2)
        self.assert_history(historical)

    def test_compute_recovers_without_partial_results(self) -> None:
        self.assert_interruption("compute")

    def test_export_recovers_a_complete_registered_download(self) -> None:
        self.assert_interruption("export")

    def test_purchase_recovers_one_registered_candidate(self) -> None:
        self.assert_interruption("purchase-sync")

    def test_inbound_recovers_one_registered_candidate(self) -> None:
        self.assert_interruption("inbound-sync")
