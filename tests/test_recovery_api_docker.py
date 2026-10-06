import os
import unittest
from typing import cast

from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from tests.support.api_docker import ApiDockerFixture
from tests.support.api_recovery import ApiRecoveryCase
from tests.support.business_case import sync_records
from tests.support.api_scenario import SYNC
from tests.support.inbound_exports import assert_inbound_exports
from tests.support.inbound_recovery import inbound_records


@unittest.skipUnless(
    os.environ.get("RECOVERY_API_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker API 来源恢复演练",
)
class RecoveryApiDockerTests(ApiRecoveryCase):
    def test_real_http_sync_preserves_candidates_warnings_and_blocked_jobs(
        self,
    ) -> None:
        self.assertEqual(self.scenario.login()["username"], "admin")
        self.scenario.create_api_baseline(self.fixture)
        first, second, warning, blocked = self.scenario.sync_jobs
        self.assertIsNone(first["base_version_id"])
        for job in (second, warning, blocked):
            self.assertEqual(job["base_version_id"], first["candidate_version_id"])
            self.assertIsNotNone(job["claimed_at"])
            self.assertIsNotNone(job["finished_at"])
        self.assertEqual(second["diff"]["before_quantity"], 10)
        self.assertEqual(second["diff"]["after_quantity"], 12)
        self.assertEqual(second["diff"]["changed_lines"], 1)
        self.assertEqual(warning["status"], "succeeded")
        self.assertEqual(warning["warning_count"], 1)
        self.assertEqual(warning["issue_count"], 0)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["issue_count"], 1)
        self.assertIsNone(blocked["candidate_version_id"])
        snapshot = self.scenario.snapshot()
        self.assertEqual(snapshot["configuration"]["source"], "managed")
        self.assertEqual(
            snapshot["sync_status"]["active_version"]["id"],
            first["candidate_version_id"],
        )
        record = snapshot["batches"][self.scenario.batch_id]
        self.assertEqual(
            record["batch"]["version_ids"]["self_operated_inbound"],
            first["candidate_version_id"],
        )
        self.assertEqual(
            record["batch"]["summary"],
            {
                "delivery_total": 18,
                "import_total": 15,
                "manual_total": 3,
                "conserved": True,
            },
        )
        assert_inbound_exports(self, record)
        self.assertEqual(len(snapshot["reports"][warning["id"]]["issues"]), 1)
        self.assertEqual(len(snapshot["reports"][blocked["id"]]["issues"]), 1)
        self.scenario.request("GET", f"{SYNC}/{blocked['id']}/preview", 409)

    def test_complete_backup_restores_api_config_records_and_original_files(
        self,
    ) -> None:
        target = cast(ApiDockerFixture, self.empty_target())
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        self.assertEqual(
            critical_table_counts(target.config, SubprocessRunner(), "delivery_note"),
            self.source_counts,
        )
        self.assertEqual(inbound_records(target), self.source_inbound_records)
        self.assertEqual(sync_records(target), self.source_sync_records)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(len(self.source_sync_records), 4)
        for job in self.source_sync_records:
            self.assertEqual(job["attempts"], 1)
            self.assertIsNone(job["active_slot"])
            self.assertIsNone(job["claim_token"])
        record = snapshot["batches"][restored.batch_id]
        assert_inbound_exports(self, record)
        self.assertEqual(
            target.compose(
                "exec",
                "-T",
                "api",
                "stat",
                "-c",
                "%a",
                "/data/storage/config/gerpgo.json",
            ),
            "600",
        )
        # 未重新保存配置，真实同步成功才能证明备份中的凭据可使用。
        target.set_case(12)
        fresh = restored.sync()
        self.assertGreater(fresh["id"], self.source_sync_records[-1]["id"])
        self.assertEqual(
            fresh["base_version_id"], self.scenario.sync_jobs[0]["candidate_version_id"]
        )
        self.assertEqual(fresh["diff"]["before_quantity"], 10)
        self.assertEqual(fresh["diff"]["after_quantity"], 12)
        self.assert_source_unchanged(snapshot)

    def test_restored_activation_locks_history_and_new_sync_uses_new_base(self) -> None:
        target = cast(ApiDockerFixture, self.empty_target())
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        first, second, _, _ = restored.sync_jobs
        historical_id = restored.batch_ids[0]
        restored.activate(second)
        restored.create_api_batch()
        after = restored.snapshot()
        historical = after["batches"][historical_id]
        original = snapshot["batches"][historical_id]
        self.assertEqual(
            historical["batch"]["version_ids"], original["batch"]["version_ids"]
        )
        self.assertEqual(historical["batch"]["summary"], original["batch"]["summary"])
        self.assertEqual(historical["exports"], original["exports"])
        self.assertEqual(historical["download"], original["download"])
        fresh = after["batches"][restored.batch_id]
        self.assertEqual(
            fresh["batch"]["version_ids"]["self_operated_inbound"],
            second["candidate_version_id"],
        )
        self.assertNotEqual(
            first["candidate_version_id"], second["candidate_version_id"]
        )
        self.assertEqual(
            fresh["batch"]["summary"],
            {
                "delivery_total": 18,
                "import_total": 17,
                "manual_total": 1,
                "conserved": True,
            },
        )
        self.assertEqual(fresh["exceptions"][0]["manual_quantity"], 1)
        assert_inbound_exports(self, fresh, receivable=12)
        target.set_case(14)
        job = restored.sync()
        self.assertEqual(job["base_version_id"], second["candidate_version_id"])
        self.assertEqual(job["diff"]["before_quantity"], 12)
        self.assertEqual(job["diff"]["after_quantity"], 14)
        self.assertEqual(job["diff"]["changed_lines"], 1)
        self.assertEqual(
            restored.request("GET", SYNC).json()["active_version"]["id"],
            second["candidate_version_id"],
        )
        self.assertEqual(restored.snapshot()["batches"][historical_id], historical)
        self.assert_source_unchanged(snapshot)

    def test_restored_faults_reject_candidates_and_release_failed_sync(self) -> None:
        target = cast(ApiDockerFixture, self.empty_target())
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        first, second, _, blocked = restored.sync_jobs
        active = restored.request("GET", SYNC).json()["active_version"]
        restored.activate(blocked, 409)
        target.remove_restored_candidate(second["id"])
        restored.request("GET", f"{SYNC}/{second['id']}/preview", 409)
        restored.activate(second, 409)
        self.assertEqual(restored.request("GET", SYNC).json()["active_version"], active)
        target.set_case(12, fail=True)
        failure = restored.sync("failed")
        self.assertIsNone(failure["candidate_version_id"])
        self.assertIn("隔离接口故障", failure["error_message"])
        self.assertIsNone(sync_records(target)[-1]["active_slot"])
        self.assertIsNone(sync_records(target)[-1]["claim_token"])
        self.assertEqual(restored.request("GET", SYNC).json()["active_version"], active)
        target.set_case(12)
        retried = restored.sync()
        self.assertEqual(retried["base_version_id"], first["candidate_version_id"])
        self.assertEqual(restored.request("GET", SYNC).json()["active_version"], active)
        self.assert_source_unchanged(snapshot)
