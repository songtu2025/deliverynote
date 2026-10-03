from __future__ import annotations

import json

from scripts.backup.database import RESTORE_DATABASE_PATTERN
from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class BackupWorkflowTests(BackupTestCase):
    def test_successful_backup_is_completed_only_after_resume_and_validation(self):
        runner = FakeRunner()

        result = create_backup(
            self.config,
            runner=runner,
            now=lambda: self.fixed_time,
        )

        backup = self.destination / "20260722-183000"
        self.assertEqual(result["backup_directory"], str(backup))
        self.assertEqual(result["status"], "complete")
        self.assertTrue((backup / "READY").is_file())
        self.assertTrue((backup / "database.dump").is_file())
        self.assertTrue((backup / "delivery_data.tar.gz").is_file())
        self.assertTrue((backup / "SHA256SUMS").is_file())
        metadata = json.loads(
            (backup / "BACKUP-METADATA.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(metadata["data_archive"]["files"], 1)
        self.assertEqual(metadata["active_jobs_before_maintenance"], 0)
        self.assertEqual(
            metadata["database"]["source_row_counts"],
            runner.source_counts,
        )
        self.assertEqual(
            metadata["database"]["restore_verification"],
            {
                "status": "passed",
                "restored_row_counts": runner.source_counts,
            },
        )
        self.assertTrue(result["database_restore_verified"])
        self.assertEqual((backup / "database.dump").stat().st_mode & 0o777, 0o600)

        stop_ingress = next(
            index
            for index, command in enumerate(runner.commands)
            if "stop" in command and command[-2:] == ("web", "api")
        )
        stop_worker = next(
            index
            for index, command in enumerate(runner.commands)
            if "stop" in command
            and command[-3:]
            == ("worker", "purchase-sync-worker", "inbound-sync-worker")
        )
        database_dump = next(
            index
            for index, command in enumerate(runner.commands)
            if "pg_dump" in command
        )
        resume = next(
            index
            for index, command in enumerate(runner.commands)
            if command[:2] == ("docker", "start")
        )
        source_counts = next(
            index
            for index, command in enumerate(runner.commands)
            if "psql" in command
            and "UNION ALL" in command[command.index("-c") + 1]
            and command[command.index("-d") + 1] == "delivery_note"
        )
        create_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "createdb" in command
        )
        restore_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "pg_restore" in command
        )
        verify_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "psql" in command
            and "UNION ALL" in command[command.index("-c") + 1]
            and command[command.index("-d") + 1] != "delivery_note"
        )
        drop_database = next(
            index
            for index, command in enumerate(runner.commands)
            if "dropdb" in command
        )
        temporary_database = runner.commands[create_database][-1]
        self.assertLess(stop_ingress, stop_worker)
        self.assertLess(stop_worker, source_counts)
        self.assertLess(source_counts, database_dump)
        self.assertLess(database_dump, resume)
        self.assertLess(resume, create_database)
        self.assertLess(create_database, restore_database)
        self.assertLess(restore_database, verify_database)
        self.assertLess(verify_database, drop_database)
        self.assertRegex(temporary_database, RESTORE_DATABASE_PATTERN)
        self.assertNotEqual(temporary_database, "delivery_note")
        self.assertEqual(
            runner.commands[restore_database][
                runner.commands[restore_database].index("-d") + 1
            ],
            temporary_database,
        )
        self.assertEqual(runner.commands[drop_database][-1], temporary_database)
        self.assertEqual(runner.restored_payload, b"PGDMP\x01\x0funit-test")

    def test_resume_uses_existing_containers_when_new_compose_image_is_missing(self):
        runner = FakeRunner(fail_compose_reconcile=True)

        result = create_backup(
            self.config,
            runner=runner,
            now=lambda: self.fixed_time,
        )

        self.assertEqual(result["status"], "complete")
        resume = next(
            command
            for command in runner.commands
            if command[:2] == ("docker", "start")
            and command[-5:]
            == (
                "deliverynote-api-1",
                "deliverynote-worker-1",
                "deliverynote-purchase-sync-worker-1",
                "deliverynote-inbound-sync-worker-1",
                "deliverynote-web-1",
            )
        )
        self.assertNotIn("compose", resume)
