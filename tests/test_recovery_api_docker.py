import os
import unittest

from tests.support.api_docker import ApiDockerFixture
from tests.support.api_scenario import ApiScenario, SYNC
from tests.support.business_case import RecoveryCase
from tests.support.inbound_exports import assert_inbound_exports


@unittest.skipUnless(
    os.environ.get("RECOVERY_API_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker API 来源恢复演练",
)
class RecoveryApiDockerTests(RecoveryCase):
    fixture_type = ApiDockerFixture
    fixture: ApiDockerFixture
    scenario: ApiScenario

    def setUp(self) -> None:
        super().setUp()
        self.scenario = ApiScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

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
