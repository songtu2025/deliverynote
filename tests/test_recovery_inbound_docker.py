import os
import unittest

from tests.support.business_case import RecoveryCase
from tests.support.inbound_scenario import InboundScenario
from tests.support.inbound_exports import assert_inbound_exports


@unittest.skipUnless(
    os.environ.get("RECOVERY_INBOUND_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 自营仓恢复演练",
)
class RecoveryInboundDockerTests(RecoveryCase):
    def test_real_workers_preserve_order_allowance_and_site_choice(self) -> None:
        scenario = InboundScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(scenario.client.close)
        self.assertEqual(scenario.login()["username"], "admin")
        identifiers = scenario.create_inbound_baseline()
        snapshot = scenario.snapshot()
        multi, ambiguous, selected = (
            snapshot["batches"][identifier] for identifier in identifiers
        )
        self.assertEqual(
            [
                (item["original_name"], item["import_total"], item["manual_total"])
                for item in multi["batch"]["files"]
            ],
            [
                ("260817-狂飙-B质检交货单.xlsx", 8, 0),
                ("260817-狂飙-A质检交货单.xlsx", 7, 3),
            ],
        )
        self.assertEqual(ambiguous["batch"]["summary"]["manual_total"], 18)
        self.assertEqual(ambiguous["batch"]["site_resolutions"], [])
        self.assertEqual(ambiguous["exceptions"][0]["reason"], "产品信息站点不唯一")
        self.assertEqual(
            selected["batch"]["site_resolutions"][0]["full_site"], "AMAZON:RIVMOUNT:US"
        )
        for record in (multi, selected):
            self.assertEqual(
                record["batch"]["self_operated_overreceipt_rule"]["allowance"], 5
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
            self.assertEqual(record["exceptions"][0]["manual_quantity"], 3)
            assert_inbound_exports(self, record)
        self.assertNotEqual(
            multi["batch"]["version_ids"]["product"],
            selected["batch"]["version_ids"]["product"],
        )
