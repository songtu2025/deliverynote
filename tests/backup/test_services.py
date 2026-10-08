import sqlite3
from dataclasses import replace
from unittest.mock import patch

from scripts.backup.runtime import BackupError
from scripts.backup.services import (
    API_HEALTH_FORMAT,
    RESUMED_SERVICES,
    active_job_count,
    resume_services,
    wait_for_api,
)
from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class QueueRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.database = sqlite3.connect(":memory:")
        for table in ("jobs", "purchase_sync_jobs", "self_operated_inbound_sync_jobs"):
            self.database.execute(f"CREATE TABLE {table} (status TEXT)")

    def _counts(self, command: tuple[str, ...]) -> str:
        query = command[command.index("-c") + 1]
        if "public.users" in query or "json_agg" in query:
            return super()._counts(command)
        return str(self.database.execute(query).fetchone()[0])


class BackupServicesTests(BackupTestCase):
    def test_http_ready_waits_for_container_health(self) -> None:
        runner = FakeRunner()
        original = runner.run
        states = iter(["starting", "starting", "healthy"])

        def readiness(arguments: list[str], **kwargs: object) -> str:
            if API_HEALTH_FORMAT in arguments:
                return next(states)
            return original(arguments)

        with (
            patch.object(runner, "run", side_effect=readiness),
            patch("scripts.backup.services.time.sleep") as sleep,
        ):
            wait_for_api(self.config, runner, "api-id")
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(
            any(command[:2] == ("docker", "exec") for command in runner.commands)
        )

    def test_container_health_timeout_refuses_recovery(self) -> None:
        runner = FakeRunner()
        original = runner.run

        def readiness(arguments: list[str], **kwargs: object) -> str:
            return "starting" if API_HEALTH_FORMAT in arguments else original(arguments)

        with (
            patch.object(runner, "run", side_effect=readiness),
            patch("scripts.backup.services.time.monotonic", side_effect=[0, 2]),
            patch("scripts.backup.services.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(BackupError, "健康状态等待超时"):
                wait_for_api(
                    replace(self.config, service_wait_timeout_seconds=1),
                    runner,
                    "api-id",
                )
        sleep.assert_not_called()

    def test_each_queue_counts_active_states_and_excludes_finished_jobs(self) -> None:
        for table in ("jobs", "purchase_sync_jobs", "self_operated_inbound_sync_jobs"):
            for status in ("queued", "running", "succeeded", "failed"):
                with self.subTest(table=table, status=status):
                    runner = QueueRunner()
                    try:
                        runner.database.execute(
                            f"INSERT INTO {table} VALUES (?)", (status,)
                        )
                        self.assertEqual(
                            active_job_count(self.config, runner),
                            int(status in {"queued", "running"}),
                        )
                    finally:
                        runner.database.close()

    def test_mixed_queues_are_counted_in_one_database_snapshot(self) -> None:
        runner = QueueRunner()
        self.addCleanup(runner.database.close)
        for table in ("jobs", "purchase_sync_jobs", "self_operated_inbound_sync_jobs"):
            runner.database.executemany(
                f"INSERT INTO {table} VALUES (?)", [("queued",), ("running",)]
            )
        self.assertEqual(active_job_count(self.config, runner), 6)
        self.assertEqual(len(runner.commands), 1)

    def test_running_containers_and_internal_api_are_not_enough_for_recovery(
        self,
    ) -> None:
        runner = FakeRunner()
        containers = {service: f"{service}-id" for service in RESUMED_SERVICES}
        with patch(
            "scripts.backup.services.verify_served_web",
            side_effect=BackupError("Web 入口未恢复"),
        ):
            with self.assertRaisesRegex(BackupError, "Web 入口未恢复"):
                resume_services(self.config, runner, containers)

    def test_sync_queue_timeout_recovers_without_stopping_workers_or_dumping(
        self,
    ) -> None:
        for table in ("purchase_sync_jobs", "self_operated_inbound_sync_jobs"):
            for status in ("queued", "running"):
                with self.subTest(table=table, status=status):
                    runner = QueueRunner()
                    try:
                        runner.database.execute(
                            f"INSERT INTO {table} VALUES (?)", (status,)
                        )
                        clock = iter([0.0, 2.0])
                        with self.assertRaisesRegex(BackupError, "排空超时"):
                            create_backup(
                                replace(self.config, job_drain_timeout_seconds=1),
                                runner=runner,
                                now=lambda: self.fixed_time,
                                monotonic=lambda: next(clock),
                                sleep=lambda _: None,
                            )
                        self.assertFalse(
                            any("pg_dump" in command for command in runner.commands)
                        )
                        self.assertFalse(
                            any(
                                "stop" in command and "worker" in command
                                for command in runner.commands
                            )
                        )
                        self.assertTrue(
                            any(
                                command[:2] == ("docker", "start")
                                for command in runner.commands
                            )
                        )
                        self.assertFalse(any(self.destination.glob("*/READY")))
                    finally:
                        runner.database.close()

    def test_web_recovery_failure_prevents_restore_verification_and_ready(self) -> None:
        runner = FakeRunner()
        with patch(
            "scripts.backup.services.verify_served_web",
            side_effect=[None, BackupError("Web 入口未恢复")],
        ):
            self.assert_failed_backup(runner, "Web 入口未恢复")
        self.assertFalse(any("createdb" in command for command in runner.commands))

    def test_workers_finish_all_queues_before_snapshot(self) -> None:
        runner = QueueRunner()
        self.addCleanup(runner.database.close)
        tables = ("jobs", "purchase_sync_jobs", "self_operated_inbound_sync_jobs")
        for table in tables:
            runner.database.execute(f"INSERT INTO {table} VALUES ('queued')")

        def finish_tasks(_: float) -> None:
            for table in tables:
                runner.database.execute(f"UPDATE {table} SET status='succeeded'")

        result = create_backup(
            self.config, runner=runner, now=lambda: self.fixed_time, sleep=finish_tasks
        )
        self.assertEqual(result["status"], "complete")
        self.assertTrue(any(self.destination.glob("*/READY")))

    def test_sync_task_remaining_after_worker_stop_prevents_snapshot(self) -> None:
        for table in ("purchase_sync_jobs", "self_operated_inbound_sync_jobs"):
            with self.subTest(table=table):
                runner = QueueRunner()
                original = runner._compose

                def stop(command: tuple[str, ...]) -> str:
                    if "stop" in command and "worker" in command:
                        runner.database.execute(
                            f"INSERT INTO {table} VALUES ('running')"
                        )
                    return original(command)

                try:
                    destination = self.root / table
                    with (
                        patch.object(runner, "_compose", side_effect=stop),
                        patch.object(self, "destination", destination),
                        patch.object(
                            self,
                            "config",
                            replace(self.config, destination=destination),
                        ),
                    ):
                        self.assert_failed_backup(runner, "Worker 停止后仍存在活动任务")
                    self.assertFalse(
                        any("pg_dump" in command for command in runner.commands)
                    )
                finally:
                    runner.database.close()

    def test_bad_web_before_maintenance_does_not_stop_services(self) -> None:
        runner = FakeRunner()
        with patch(
            "scripts.backup.services.verify_served_web",
            side_effect=BackupError("Web 入口不可用"),
        ):
            with self.assertRaisesRegex(BackupError, "Web 入口不可用"):
                create_backup(self.config, runner=runner)
        self.assertFalse(self.destination.exists())
        self.assertFalse(any("stop" in command for command in runner.commands))
