from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from scripts.backup.runtime import BackupError, exclusive_lock
from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class BackupLifecycleTests(BackupTestCase):
    def test_competing_backup_fails_before_inspection_or_maintenance(self) -> None:
        runner = FakeRunner()
        with exclusive_lock(self.config.lock_file):
            with self.assertRaisesRegex(BackupError, "已有备份任务正在运行"):
                create_backup(self.config, runner=runner)
        self.assertEqual(runner.commands, [])
        self.assertFalse(self.destination.exists())
        result = create_backup(self.config, runner=runner, now=lambda: self.fixed_time)
        self.assertEqual(result["status"], "complete")

    def test_job_drain_timeout_resumes_services_without_stopping_workers(self) -> None:
        runner = FakeRunner()
        clock = iter([0.0, 2.0])
        with patch("scripts.backup.services.active_job_count", return_value=1):
            with self.assertRaisesRegex(BackupError, "等待活动任务排空超时"):
                create_backup(
                    replace(self.config, job_drain_timeout_seconds=1),
                    runner=runner,
                    now=lambda: self.fixed_time,
                    monotonic=lambda: next(clock),
                    sleep=lambda _: None,
                )
        self.assertFalse(any("pg_dump" in command for command in runner.commands))
        self.assertFalse(
            any(
                "stop" in command and "worker" in command for command in runner.commands
            )
        )
        self.assertTrue(
            any(command[:2] == ("docker", "start") for command in runner.commands)
        )
        self.assertTrue(
            next(self.destination.glob(".incomplete-*"))
            .joinpath("FAILED.txt")
            .is_file()
        )
        self.assertFalse(any(self.destination.glob("*/READY")))

    def test_remaining_jobs_after_worker_stop_prevent_snapshot(self) -> None:
        runner = FakeRunner()
        with patch("scripts.backup.workflow.active_job_count", return_value=1):
            self.assert_failed_backup(runner, "Worker 停止后仍存在活动任务")
        self.assertFalse(any("pg_dump" in command for command in runner.commands))
        self.assertTrue(
            any(command[:2] == ("docker", "start") for command in runner.commands)
        )

    def test_resume_failure_prevents_restore_verification_and_ready_marker(
        self,
    ) -> None:
        runner = FakeRunner()
        with patch(
            "scripts.backup.workflow.resume_services",
            side_effect=BackupError("服务恢复失败"),
        ) as resume:
            self.assert_failed_backup(runner, "服务恢复失败")
        resume.assert_called_once()
        self.assertFalse(any("createdb" in command for command in runner.commands))

    def test_snapshot_and_resume_failures_are_both_reported(self) -> None:
        runner = FakeRunner(failure="archive")
        with patch(
            "scripts.backup.workflow.resume_services",
            side_effect=BackupError("服务恢复失败"),
        ) as resume:
            failed = self.assert_failed_backup(
                runner, "备份失败且服务恢复失败：模拟文件卷归档失败; 服务恢复失败"
            )
        resume.assert_called_once()
        self.assertIn(
            "服务恢复失败", (failed / "FAILED.txt").read_text(encoding="utf-8")
        )

    def test_restore_and_cleanup_failures_are_both_reported(self) -> None:
        runner = FakeRunner(failure="restore")
        runner.fail_drop_database = True
        self.assert_failed_backup(
            runner,
            "数据库恢复验证失败且临时恢复数据库清理失败："
            "模拟 pg_restore 失败; 模拟临时数据库清理失败",
        )
        self.assertTrue(any("dropdb" in command for command in runner.commands))
