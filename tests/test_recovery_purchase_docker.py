import os
import unittest
from copy import deepcopy
from typing import Any, cast

from scripts.backup.database import critical_table_counts
from scripts.backup.runtime import SubprocessRunner
from tests.support.business_case import sync_records
from tests.support.delivery_exports import assert_delivery_exports
from tests.support.purchase_docker import PurchaseDockerFixture
from tests.support.purchase_scenario import SYNC
from tests.support.purchase_recovery import PurchaseRecoveryCase


@unittest.skipUnless(
    os.environ.get("RECOVERY_PURCHASE_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 采购 API 来源恢复演练",
)
class RecoveryPurchaseDockerTests(PurchaseRecoveryCase):
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

    def test_complete_backup_restores_purchase_records_cache_and_files(self) -> None:
        target = cast(PurchaseDockerFixture, self.empty_target())
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        self.assertEqual(
            critical_table_counts(target.config, SubprocessRunner(), "delivery_note"),
            self.source_counts,
        )
        self.assertEqual(sync_records(target, "purchase"), self.source_sync_records)
        self.assertEqual(target.cache(), self.source_cache)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(len(self.source_sync_records), 4)
        for job in self.source_sync_records:
            self.assertEqual(job["attempts"], 1)
            self.assertIsNone(job["active_slot"])
            self.assertIsNone(job["claim_token"])
        for path in ("config/gerpgo.json", "cache/purchase-details-v1.json"):
            self.assertEqual(
                target.compose(
                    "exec", "-T", "api", "stat", "-c", "%a", f"/data/storage/{path}"
                ),
                "600",
            )
        historical = snapshot["batches"][restored.batch_id]
        assert_delivery_exports(self, *historical["exports"], resolved=0)
        # 保持恢复出的配置不变，由真实请求证明凭据和缓存可继续使用。
        target.set_case(120)
        fresh = restored.sync()
        self.assertGreater(fresh["id"], self.source_sync_records[-1]["id"])
        self.assertEqual(
            fresh["base_version_id"], self.scenario.sync_jobs[0]["candidate_version_id"]
        )
        self.assertEqual(fresh["diff"]["before_quantity"], 100)
        self.assertEqual(fresh["diff"]["after_quantity"], 120)
        after = restored.snapshot()["batches"][restored.batch_id]
        for key in ("batch", "exceptions", "exports"):
            self.assertEqual(after[key], historical[key])
        self.assert_source_unchanged(snapshot)

    def test_restored_activation_freezes_history_and_verifies_real_cache(self) -> None:
        target = cast(PurchaseDockerFixture, self.empty_target())
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        first, second, _, _ = restored.sync_jobs
        historical_id = restored.batch_id
        original = snapshot["batches"][historical_id]
        # 全局启用标记会切换，历史批次的锁定版本、数量和结果不变。
        historical = deepcopy(original)
        historical["batch"]["versions"]["purchase"]["active"] = False
        restored.activate(second)
        restored.create_api_batch()
        after = restored.snapshot()
        for key in ("batch", "exceptions", "exports"):
            self.assertEqual(after["batches"][historical_id][key], historical[key])
        fresh = after["batches"][restored.batch_id]
        self.assertEqual(
            fresh["batch"]["version_ids"]["purchase"], second["candidate_version_id"]
        )
        self.assertEqual(
            original["batch"]["version_ids"]["purchase"], first["candidate_version_id"]
        )
        self.assertEqual(
            [
                (item["import_total"], item["manual_total"])
                for item in fresh["batch"]["files"]
            ],
            [(80, 0), (40, 40)],
        )
        assert_delivery_exports(self, *fresh["exports"], balance=120, resolved=0)

        def check_sync(request_count: int, **expected: object) -> dict[str, Any]:
            offset = len(target.requests())
            job = restored.sync()
            details = [
                r for r in target.requests()[offset:] if r["path"].endswith("/detail")
            ]
            stats = target.sync_stats(job["id"])
            self.assertEqual(len(details), request_count)
            self.assertEqual(stats["detail_request_count"], request_count)
            for key, value in expected.items():
                self.assertEqual(stats[key], value)
            self.assertEqual(job["processed_orders"], 6)
            self.assertEqual(job["base_version_id"], second["candidate_version_id"])
            self.assertEqual(job["diff"]["before_quantity"], 120)
            return job

        target.set_case(120)
        stable = check_sync(
            5,
            cache_hit_count=1,
            sampled_order_count=5,
            changed_order_count=0,
            incremental_fallback=False,
        )
        self.assertEqual(stable["diff"]["after_quantity"], 120)
        target.set_case(140)
        changed = check_sync(
            6,
            cache_hit_count=0,
            sampled_order_count=0,
            changed_order_count=6,
            incremental_fallback=False,
        )
        self.assertEqual(changed["diff"]["after_quantity"], 140)
        # 列表指纹不变而真实详情变化，必须由抽样发现并回退全量抓取。
        target.set_case(160, fingerprint=140)
        mismatch = check_sync(
            11,
            cache_hit_count=0,
            changed_order_count=0,
            incremental_fallback=True,
            forced_full_reason="sample_mismatch",
        )
        self.assertEqual(mismatch["diff"]["after_quantity"], 160)
        self.assertGreater(
            target.sync_stats(mismatch["id"])["sample_mismatch_count"], 0
        )
        latest = restored.snapshot()
        active = [
            v["id"]
            for v in latest["versions"]
            if v["kind"] == "purchase" and v["active"]
        ]
        self.assertEqual(active, [second["candidate_version_id"]])
        for key in ("batch", "exceptions", "exports"):
            self.assertEqual(latest["batches"][historical_id][key], historical[key])
        self.assert_source_unchanged(snapshot)

    def test_restored_faults_reject_activation_and_allow_sync_retry(self) -> None:
        target = cast(PurchaseDockerFixture, self.empty_target())
        directory, snapshot = self.backup_baseline()
        restored = self.restored_scenario(target, directory)
        first, second, _, blocked = restored.sync_jobs
        before = restored.request("GET", "/api/input-versions").json()
        restored.request(
            "POST",
            "/api/users",
            201,
            json={
                "username": "operator",
                "password": "operator-pass",
                "role": "operator",
            },
        )
        login = restored.request(
            "POST",
            "/api/auth/login",
            json={"username": "operator", "password": "operator-pass"},
        ).json()
        operator = {"Authorization": "Bearer " + login["token"]}
        restored.request("GET", f"{SYNC}/{second['id']}/preview", headers=operator)
        restored.request(
            "POST",
            f"/api/input-versions/{second['candidate_version_id']}/activate",
            403,
            headers=operator,
        )
        restored.request("GET", f"{SYNC}/{blocked['id']}/preview", 409)
        target.remove_restored_candidate(second["id"], kind="purchase")
        restored.request("GET", f"{SYNC}/{second['id']}/preview", 409)
        restored.activate(second, 409)
        self.assertEqual(restored.request("GET", "/api/input-versions").json(), before)
        target.set_case(120, fail=True)
        failure = restored.sync("failed")
        self.assertIn("隔离接口故障", failure["error_message"])
        self.assertIsNone(failure["candidate_version_id"])
        for key in ("active_slot", "claim_token"):
            self.assertIsNone(sync_records(target, "purchase")[-1][key])
        target.set_case(120)
        retried = restored.sync()
        self.assertEqual(retried["base_version_id"], first["candidate_version_id"])
        active = [
            v["id"]
            for v in restored.request("GET", "/api/input-versions").json()
            if v["kind"] == "purchase" and v["active"]
        ]
        self.assertEqual(active, [first["candidate_version_id"]])
        self.assert_source_unchanged(snapshot)
