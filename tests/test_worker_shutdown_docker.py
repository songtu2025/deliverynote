"""在独立 PostgreSQL 和文件卷验证真实 Worker 退出及备份排空。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest

from scripts.backup.runtime import BackupError
from scripts.backup.services import REQUIRED_SERVICES
from scripts.backup.workflow import create_backup
from tests.support.business_case import RecoveryCase
from tests.support.delivery_exports import assert_delivery_exports
from tests.support.sync_http import configure_sync, start_sync
from tests.support.worker_backup import DrainRunner
from tests.support.worker_docker import TASKS, WorkerDockerFixture, wait_until


@unittest.skipUnless(
    os.getenv("WORKER_DOCKER_TESTS") == "1", "需显式开启隔离 Worker 演练"
)
class WorkerShutdownDockerTests(RecoveryCase):
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

    def assert_shutdown(self, kind: str) -> None:
        fixture = self.fixture
        fixture.arm(kind)
        identifier = self.enqueue(kind)
        arrived = fixture.arrived(kind)
        self.assertEqual(arrived["id"], identifier)
        before = fixture.job(kind, identifier)
        self.assertEqual(before["status"], "running")
        service = TASKS[kind][0]
        container = fixture.inspect(service)[0]["Id"]
        queued = self.enqueue("compute") if service == "worker" else None
        fixture.run("docker", "kill", "--signal", "TERM", container)
        fixture.release(kind)
        wait_until(lambda: not fixture.state(container)["Running"], "Worker 未正常退出")
        self.assertEqual(fixture.state(container)["ExitCode"], 0)
        finished = fixture.job(kind, identifier)
        self.assertEqual((finished["status"], finished["attempts"]), ("succeeded", 1))
        self.assertIsNone(finished["claim_token"])
        if service != "worker":
            self.assertIsNone(finished["active_slot"])
            self.assertIsNotNone(finished["candidate_version_id"])
            queued = self.enqueue(kind)
        assert queued is not None
        queued_kind = "compute" if service == "worker" else kind
        self.assertEqual(fixture.job(queued_kind, queued)["status"], "queued")
        self.assertEqual(fixture.job(queued_kind, queued)["attempts"], 0)
        fixture.compose("start", service)
        wait_until(
            lambda: fixture.job(queued_kind, queued)["status"] == "succeeded",
            "重启后排队任务未完成",
        )
        if service == "worker":
            self.scenario.batch_id = int(finished["batch_id"])
            batch = self.scenario.batch()["summary"]
            self.assertEqual(
                (batch["delivery_total"], batch["import_total"], batch["manual_total"]),
                (160, 100, 60),
            )
            if kind == "export":
                assert_delivery_exports(self, *self.scenario.downloads(), resolved=0)

    def test_compute_finishes_current_task_on_sigterm(self) -> None:
        self.assert_shutdown("compute")

    def test_export_finishes_current_task_on_sigterm(self) -> None:
        self.assert_shutdown("export")

    def test_purchase_finishes_current_task_on_sigterm(self) -> None:
        self.assert_shutdown("purchase-sync")

    def test_inbound_finishes_current_task_on_sigterm(self) -> None:
        self.assert_shutdown("inbound-sync")

    def queued_three_queues(self) -> dict[str, int]:
        jobs = {}
        for kind in ("compute", "purchase-sync", "inbound-sync"):
            self.fixture.arm(kind)
            jobs[kind] = self.enqueue(kind)
            self.assertEqual(self.fixture.arrived(kind)["id"], jobs[kind])
        return jobs

    def test_backup_waits_for_all_three_real_queues(self) -> None:
        jobs = self.queued_three_queues()
        fixture = self.fixture
        api = fixture.inspect("api")[0]["Id"]
        runner = DrainRunner(fixture)
        config = replace(
            fixture.config, job_drain_timeout_seconds=60, job_poll_seconds=1
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            backup = executor.submit(create_backup, config, runner=runner)
            try:
                wait_until(lambda: not fixture.state(api)["Running"], "备份未停止 API")
                self.assertFalse(backup.done())
                self.assertEqual(runner.snapshot_counts, [])
                for kind in jobs:
                    fixture.release(kind)
            finally:
                for kind in jobs:
                    fixture.release(kind)
            result = backup.result(timeout=90)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(runner.snapshot_counts, [0])
        self.assertEqual(set(runner.stopped_workers), {TASKS[kind][0] for kind in jobs})
        directory = Path(str(result["backup_directory"]))
        metadata = json.loads((directory / "BACKUP-METADATA.json").read_text())
        self.assertEqual(metadata["active_jobs_before_maintenance"], 3)
        self.assertTrue((directory / "READY").is_file())
        for kind, identifier in jobs.items():
            self.assertEqual(fixture.job(kind, identifier)["status"], "succeeded")
        fixture.wait_ready()

    def test_drain_timeout_resumes_services_without_snapshot(self) -> None:
        jobs = self.queued_three_queues()
        fixture = self.fixture
        before = {
            service: fixture.inspect(service)[0]["Id"] for service in REQUIRED_SERVICES
        }
        runner = DrainRunner(fixture)
        config = replace(
            fixture.config, job_drain_timeout_seconds=1, job_poll_seconds=1
        )
        with self.assertRaisesRegex(BackupError, "等待活动任务排空超时"):
            create_backup(config, runner=runner)
        self.assertEqual(runner.snapshot_counts, [])
        self.assertEqual(runner.stopped_workers, [])
        self.assertFalse(any(config.destination.glob("*/READY")))
        self.assertTrue(any(config.destination.glob("*/FAILED.txt")))
        self.assertFalse(any(config.destination.glob("*/database.dump")))
        for service, identifier in before.items():
            self.assertEqual(fixture.inspect(service)[0]["Id"], identifier)
            self.assertTrue(fixture.state(identifier)["Running"])
        fixture.wait_ready()
        for kind, identifier in jobs.items():
            fixture.release(kind)
            wait_until(
                lambda: fixture.job(kind, identifier)["status"] == "succeeded",
                "恢复后任务未完成",
            )
