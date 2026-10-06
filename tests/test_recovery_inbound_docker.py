import os
import unittest

from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from tests.support.inbound_recovery import InboundRecoveryCase, inbound_records
from tests.support.inbound_exports import assert_inbound_exports


@unittest.skipUnless(
    os.environ.get("RECOVERY_INBOUND_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 自营仓恢复演练",
)
class RecoveryInboundDockerTests(InboundRecoveryCase):
    def test_real_workers_preserve_order_allowance_and_site_choice(self) -> None:
        scenario = self.scenario
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

    def test_complete_backup_restores_inbound_records_and_original_exports(
        self,
    ) -> None:
        target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        self.assertEqual(
            critical_table_counts(target.config, SubprocessRunner(), "delivery_note"),
            self.source_counts,
        )
        self.assertEqual(inbound_records(target), self.source_inbound_records)
        self.assertEqual(restored.snapshot(), snapshot)
        multi, _, selected = (
            snapshot["batches"][identifier] for identifier in restored.batch_ids
        )
        for record in (multi, selected):
            assert_inbound_exports(self, record)
        self.assert_source_unchanged(snapshot)
