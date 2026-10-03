from __future__ import annotations


from tests.support.backup import BackupTestCase, FakeRunner


class BackupRestoreTests(BackupTestCase):
    def test_restore_count_mismatch_fails_and_drops_temporary_database(self):
        restored_counts = {
            "users": 3,
            "input_versions": 7,
            "batches": 4,
            "batch_files": 8,
            "jobs": 2,
        }
        runner = FakeRunner(restored_counts=restored_counts)

        self.assert_failed_backup(runner, "关键表行数.*不一致")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_pg_restore_failure_drops_temporary_database(self):
        runner = FakeRunner(failure="restore")

        self.assert_failed_backup(runner, "模拟 pg_restore 失败")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_restore_validation_failure_drops_temporary_database(self):
        runner = FakeRunner(failure="validation")

        self.assert_failed_backup(runner, "模拟恢复库验证失败")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_restore_database_creation_failure_still_attempts_drop(self):
        runner = FakeRunner(failure="create_database")

        self.assert_failed_backup(runner, "模拟临时数据库创建失败")

        self.assertTrue(any("dropdb" in command for command in runner.commands))

    def test_restore_database_drop_failure_cannot_mark_backup_ready(self):
        runner = FakeRunner(failure="drop_database")

        failed = self.assert_failed_backup(runner, "临时恢复数据库清理失败")

        failure_marker = (failed / "FAILED.txt").read_text(encoding="utf-8")
        self.assertIn("模拟临时数据库清理失败", failure_marker)
