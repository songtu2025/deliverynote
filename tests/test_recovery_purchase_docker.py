import os
import unittest

from tests.support.business_case import RecoveryCase
from tests.support.delivery_exports import assert_delivery_exports
from tests.support.purchase_docker import PurchaseDockerFixture
from tests.support.purchase_scenario import PurchaseScenario, SYNC


@unittest.skipUnless(
    os.environ.get("RECOVERY_PURCHASE_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 采购 API 来源恢复演练",
)
class RecoveryPurchaseDockerTests(RecoveryCase):
    fixture_type = PurchaseDockerFixture
    fixture: PurchaseDockerFixture
    scenario: PurchaseScenario

    def setUp(self) -> None:
        super().setUp()
        self.scenario = PurchaseScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

    def test_real_purchase_http_preserves_order_and_candidate_states(self) -> None:
        self.assertEqual(self.scenario.login()["username"], "admin")
        self.scenario.create_api_baseline(self.fixture)
        first, second, warning, blocked = self.scenario.sync_jobs
        requests = self.fixture.requests()
        self.assertEqual(
            [record["payload"]["pageInfo"]["page"] for record in requests[:2]], [1, 2]
        )
        self.assertEqual(
            {record["payload"]["poCode"] for record in requests[2:8]},
            {f"PO-{index}" for index in range(1, 7)},
        )
        for job in (first, second, warning, blocked):
            self.assertIsNotNone(job["claimed_at"])
            self.assertIsNotNone(job["finished_at"])
            self.assertEqual(job["processed_orders"], job["total_orders"])
            self.assertIsNotNone(job["product_version_id"])
            self.assertIsNotNone(job["supplier_version_id"])
        self.assertEqual(first["total_orders"], 6)
        self.assertEqual(first["filtered_detail_count"], 1)
        for job in (second, warning, blocked):
            self.assertEqual(job["base_version_id"], first["candidate_version_id"])
        self.assertEqual(second["diff"]["before_quantity"], 100)
        self.assertEqual(second["diff"]["after_quantity"], 120)
        self.assertEqual(second["diff"]["changed_lines"], 1)
        self.assertEqual(warning["warning_count"], 1)
        self.assertEqual(warning["issue_count"], 0)
        self.assertEqual(blocked["issue_count"], 1)
        self.assertIsNone(blocked["candidate_version_id"])
        snapshot = self.scenario.snapshot()
        active = [
            v for v in snapshot["versions"] if v["kind"] == "purchase" and v["active"]
        ]
        self.assertEqual([v["id"] for v in active], [first["candidate_version_id"]])
        record = snapshot["batches"][self.scenario.batch_id]
        self.assertEqual(record["batch"]["version_ids"]["purchase"], active[0]["id"])
        self.assertEqual(
            [
                (item["import_total"], item["manual_total"])
                for item in record["batch"]["files"]
            ],
            [(80, 0), (20, 60)],
        )
        assert_delivery_exports(self, *record["exports"], resolved=0)
        self.assertEqual(snapshot["configuration"]["source"], "managed")
        for job in (warning, blocked):
            report = snapshot["reports"][job["id"]]
            self.assertEqual(len(report["issues"]), 1)
            self.assertEqual(len(report["workbook"]), 2)
        self.scenario.request("GET", f"{SYNC}/{blocked['id']}/preview", 409)
