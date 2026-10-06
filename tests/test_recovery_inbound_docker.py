import os
from pathlib import Path
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

    def test_restored_workers_recompute_regenerate_and_start_fresh_balances(
        self,
    ) -> None:
        target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        multi, ambiguous, selected = restored.batch_ids
        restored.batch_id = ambiguous
        before = restored.batch()
        record = snapshot["batches"][ambiguous]["exceptions"][0]
        restored.request(
            "PUT",
            f"/api/exceptions/{record['id']}/self-operated-site",
            400,
            json={"full_site": "AMAZON:OTHER:US"},
        )
        self.assertEqual(restored.batch(), before)
        job = restored.choose_site()
        self.assertEqual(job["id"], before["jobs"]["compute"]["id"])
        self.assertNotEqual(
            job["finished_at"], before["jobs"]["compute"]["finished_at"]
        )
        restored.export()

        restored.batch_id = multi
        query = f"SELECT zip_path FROM batches WHERE id={multi}"
        previous = target.database_query(query)
        merged = Path(previous).with_name(f"batch-{multi}-merged.xlsx")
        target.remove_restored_file(multi, merged, "exports")
        restored.request("GET", f"/api/batches/{multi}/download-merged", 404)
        restored.export()
        self.assertNotEqual(target.database_query(query), previous)
        self.assertEqual(
            restored.batch()["jobs"]["export"]["id"],
            snapshot["batches"][multi]["batch"]["jobs"]["export"]["id"],
        )

        restored.create_inbound_batch()
        fresh = restored.batch()
        self.assertEqual(fresh["summary"]["manual_total"], 18)
        self.assertEqual(fresh["version_ids"], before["version_ids"])
        self.assertNotEqual(fresh["jobs"]["compute"]["id"], job["id"])
        restored.choose_site()
        restored.export()
        after = restored.snapshot()
        for identifier in (multi, ambiguous, fresh["id"]):
            record = after["batches"][identifier]
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
        self.assertEqual(after["batches"][selected], snapshot["batches"][selected])
        self.assert_source_unchanged(snapshot)

    def test_missing_restored_inbound_file_fails_real_worker_without_export(
        self,
    ) -> None:
        target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        restored.batch_id = restored.batch_ids[1]
        path = target.database_query(
            "SELECT inbound_storage_path FROM self_operated_batches "
            f"WHERE batch_id={restored.batch_id}"
        )
        target.remove_restored_file(restored.batch_id, Path(path), "inputs")
        job = restored.choose_site(expected_status="failed")
        self.assertIn("自营仓收货入库单不存在", job["error_message"])
        batch = restored.batch()
        self.assertEqual(batch["status"], "failed")
        self.assertFalse(batch["download_ready"])
        self.assertFalse(batch["merged_download_ready"])
        self.assertTrue(all(not source["download_ready"] for source in batch["files"]))
        restored.request("GET", f"/api/batches/{restored.batch_id}/download", 404)
        self.assert_source_unchanged(snapshot)
