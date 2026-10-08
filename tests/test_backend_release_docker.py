"""在独立数据库与文件卷验证真实排空、发布、回退及历史保护。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from typing import cast
import unittest

from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.backend_release import publish_backend
from scripts.deployment_sources import BACKEND_SERVICES
from scripts.deployment_verification import service_snapshot
from scripts.release_common import verify_unchanged
from tests.support.backend_docker import BackendDockerFixture
from tests.support.worker_case import WorkerDockerCase
from tests.support.worker_docker import wait_until


@unittest.skipUnless(
    os.getenv("BACKEND_RELEASE_DOCKER_TESTS") == "1", "需显式开启隔离后端发布演练"
)
class BackendReleaseDockerTests(WorkerDockerCase):
    fixture_type = BackendDockerFixture
    fixture: BackendDockerFixture

    def running_tasks(self) -> dict[str, int]:
        tasks = {}
        for kind in ("compute", "purchase-sync", "inbound-sync"):
            self.fixture.arm(kind)
            tasks[kind] = self.enqueue(kind)
            self.fixture.arrived(kind)
        return tasks

    def finish_tasks(self, tasks: dict[str, int]) -> None:
        for kind in tasks:
            self.fixture.release(kind)
        for kind, identifier in tasks.items():
            wait_until(
                lambda: self.fixture.job(kind, identifier)["status"] == "succeeded",
                "任务未完成",
            )
            self.assert_result(kind, identifier, 1)

    def test_worker_release_drains_both_states_and_preserves_history(
        self,
    ) -> None:
        fixture = self.fixture
        history = self.remember_history()
        tasks = self.running_tasks()
        queued = self.enqueue("compute")
        config = fixture.release_config()
        runner = SubprocessRunner()
        before = service_snapshot(config, runner)
        ready = publish_backend(config, runner=runner, check_only=True)
        self.assertEqual(ready["active_jobs"], 4)
        verify_unchanged(before, service_snapshot(config, runner), set())
        with ThreadPoolExecutor(max_workers=1) as executor:
            release = executor.submit(publish_backend, config, runner=runner)
            try:
                wait_until(
                    lambda: not fixture.state(before["api"]["Id"])["Running"],
                    "发布未暂停接单",
                )
                self.assertFalse(release.done())
                self.assertEqual(
                    fixture.inspect("worker")[0]["Id"], before["worker"]["Id"]
                )
            finally:
                for kind in tasks:
                    fixture.release(kind)
            result = release.result(timeout=90)
        self.assertEqual(result["updated_services"], ["worker"])
        after = service_snapshot(config, runner)
        verify_unchanged(before, after, {"worker"})
        self.assertNotEqual(before["worker"]["Id"], after["worker"]["Id"])
        self.finish_tasks(tasks)
        self.assert_result("compute", queued, 1)
        self.assert_history(history)
        self.scenario.create_delivery_batch()
        export_job = self.scenario.export()
        self.assert_result("export", export_job, 1)

    def test_drain_timeout_resumes_original_containers_without_replacing_workers(
        self,
    ) -> None:
        fixture = self.fixture
        tasks = self.running_tasks()
        config = replace(fixture.release_config(), job_drain_timeout_seconds=1)
        runner = SubprocessRunner()
        before = service_snapshot(config, runner)
        try:
            with self.assertRaisesRegex(BackupError, "已恢复原镜像.*排空超时"):
                publish_backend(config, runner=runner)
            after = service_snapshot(config, runner)
            verify_unchanged(before, after, set())
            for kind, identifier in tasks.items():
                self.assertEqual(fixture.job(kind, identifier)["status"], "running")
        finally:
            for kind in tasks:
                fixture.release(kind)
        self.finish_tasks(tasks)

    def test_api_failure_rolls_back_workers_and_all_backends_can_publish(
        self,
    ) -> None:
        fixture = self.fixture
        history = self.remember_history()
        fixture.disable_automatic_migration()
        config = fixture.release_config(tuple(sorted(BACKEND_SERVICES)))
        broken = fixture.backend_image("bad-api", fixture.revision, broken_api=True)
        runner = SubprocessRunner()
        before = service_snapshot(config, runner)
        with self.assertRaisesRegex(BackupError, "已恢复原镜像"):
            publish_backend(replace(config, image=broken), runner=runner)
        recovered = service_snapshot(config, runner)
        verify_unchanged(before, recovered, set(BACKEND_SERVICES))
        for name in BACKEND_SERVICES:
            self.assertEqual(before[name]["Image"], recovered[name]["Image"])
        self.assert_history(history)
        result = publish_backend(config, runner=runner)
        self.assertEqual(
            set(cast(list[str], result["updated_services"])), BACKEND_SERVICES
        )
        self.assert_history(history)
        self.scenario.create_delivery_batch()
        self.scenario.export()
