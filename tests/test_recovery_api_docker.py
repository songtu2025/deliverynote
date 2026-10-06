import os
import unittest
from typing import cast

from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from tests.support.api_docker import ApiDockerFixture
from tests.support.api_recovery import ApiRecoveryCase, sync_records
from tests.support.api_scenario import ApiScenario, SYNC
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
        restored = cast(ApiScenario, self.restored_scenario(target, directory))
        restored.sync_jobs = self.scenario.sync_jobs.copy()
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
