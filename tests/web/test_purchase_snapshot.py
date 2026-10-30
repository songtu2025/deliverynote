"""整批采购快照经过路由、队列、Worker 和文件持久化的验收。"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from openpyxl import load_workbook

from delivery_note.gerpgo import GerpgoError
from delivery_note.web.models import Batch, BatchFile, Job
from delivery_note.worker import run_once
from tests.support.web_api import WebApiCase


class PurchaseSnapshotTests(WebApiCase):
    def setUp(self):
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.upload_active_versions(self.headers)
        response = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "整批快照"},
        )
        self.batch_id = response.json()["id"]
        self.path = f"/api/self-operated-batches/{self.batch_id}/purchase-snapshot"
        source = self.root / "来源.xlsx"
        source.write_bytes(self.self_operated_delivery_bytes())
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "succeeded"
            session.add(
                BatchFile(
                    batch_id=batch.id,
                    original_name=source.name,
                    storage_path=str(source),
                    file_order=1,
                    supplier_name="供应商甲",
                    supplier_code="GYS-1",
                    delivery_total=15,
                    import_total=10,
                    manual_total=5,
                )
            )
            session.commit()

    def run_snapshot(self, *, balance=8):
        with patch(
            "delivery_note.workers.purchase_snapshot.GerpgoClient.from_config"
        ) as factory:
            client = factory.return_value
            client.list_purchase_orders.return_value = [
                {"code": "PO-1", "supplierCode": "GYS-1"}
            ]
            client.purchase_order_detail.return_value = {
                "warehouseProcureItemVos": [
                    {
                        "procureItemVos": [
                            {
                                "product": "SKU-A",
                                "supplierCode": "GYS-1",
                                "balanceQuantity": balance,
                                "arrivalMarketName": "SEEKWAY:US",
                                "arrivalWarehouseName": "仓库甲",
                            }
                        ]
                    }
                ]
            }
            run_once(
                str(self.app.state.database.engine.url),
                self.app.state.storage_root,
                "batch",
            )
            return client

    def test_first_load_is_shared_persistent_and_only_explicit_refresh_queries_again(
        self,
    ):
        self.assertEqual(
            self.client.get(self.path, headers=self.headers).json()["state"], "missing"
        )
        contract = self.app.openapi()["paths"][
            "/api/self-operated-batches/{batch_id}/purchase-snapshot"
        ]["post"]
        self.assertIn("202", contract["responses"])
        first = self.client.post(self.path, headers=self.headers).json()
        second = self.client.post(self.path, headers=self.headers).json()
        self.assertEqual(first["job"]["id"], second["job"]["id"])
        self.assertEqual(first["job"]["status"], "queued")
        client = self.run_snapshot()
        client.list_purchase_orders.assert_called_once_with(supplier_code="GYS-1")
        client.purchase_order_detail.assert_called_once_with("PO-1")
        ready = self.client.get(self.path, headers=self.headers).json()
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["items"][0]["remaining_quantity"], 8)
        self.assertEqual((ready["supplier_count"], ready["sku_count"]), (1, 1))
        self.assertFalse(ready["job"]["download_ready"])
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as remote:
            for method in ("GET", "POST", "GET"):
                data = self.client.request(
                    method, self.path, headers=self.headers
                ).json()
                self.assertEqual(data["snapshot_id"], ready["snapshot_id"])
            remote.assert_not_called()
        self.client.post(self.path, headers=self.headers, json={"refresh": True})
        self.run_snapshot(balance=5)
        newer = self.client.get(self.path, headers=self.headers).json()
        self.assertNotEqual(newer["snapshot_id"], ready["snapshot_id"])
        self.assertEqual(newer["items"][0]["remaining_quantity"], 5)

    def test_failed_refresh_preserves_snapshot_and_batch_without_auto_retry(
        self,
    ):
        self.client.post(self.path, headers=self.headers)
        self.run_snapshot()
        before = self.client.get(self.path, headers=self.headers).json()
        self.client.post(self.path, headers=self.headers, json={"refresh": True})
        queued = self.client.get(self.path, headers=self.headers).json()
        self.assertEqual(queued["snapshot_id"], before["snapshot_id"])
        with (
            patch(
                "delivery_note.workers.purchase_snapshot.GerpgoClient.from_config",
                side_effect=GerpgoError("上游内部内容"),
            ),
            self.assertLogs("delivery_note.worker", level="ERROR"),
        ):
            run_once(
                str(self.app.state.database.engine.url),
                self.app.state.storage_root,
                "batch",
            )
        after = self.client.post(self.path, headers=self.headers).json()
        self.assertEqual(after["snapshot_id"], before["snapshot_id"])
        self.assertEqual(after["items"], before["items"])
        self.assertEqual(after["job"]["status"], "failed")
        self.assertNotIn("上游内部内容", json.dumps(after))
        batch = self.client.get(
            f"/api/batches/{self.batch_id}", headers=self.headers
        ).json()
        self.assertEqual(batch["status"], "succeeded")
        self.assertIsNone(batch["error_message"])
        self.assertEqual(batch["summary"]["import_total"], 10)

    def test_source_changes_require_manual_refresh_and_snapshot_pagination_is_versioned(
        self,
    ):
        self.client.post(self.path, headers=self.headers)
        self.run_snapshot()
        ready = self.client.get(self.path, headers=self.headers).json()
        self.assertEqual(
            self.client.get(self.path + "?limit=201", headers=self.headers).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                self.path + "?snapshot_id=old", headers=self.headers
            ).status_code,
            409,
        )
        page = self.client.get(
            self.path + f"?offset=1&limit=1&snapshot_id={ready['snapshot_id']}",
            headers=self.headers,
        ).json()
        self.assertEqual((page["items"], page["total"]), ([], 1))
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == self.batch_id)
            )
            source.supplier_code = "OTHER"
            session.commit()
        stale = self.client.post(self.path, headers=self.headers).json()
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["items"], [])
        self.assertEqual(stale["job"]["status"], "succeeded")

    def test_empty_results_are_successful_and_operator_can_load_but_anonymous_cannot(
        self,
    ):
        self.create_operator(self.headers)
        operator = self.login("operator", "operator-pass")
        self.assertEqual(self.client.post(self.path, headers=operator).status_code, 202)
        with patch(
            "delivery_note.workers.purchase_snapshot.GerpgoClient.from_config"
        ) as factory:
            factory.return_value.list_purchase_orders.return_value = []
            run_once(
                str(self.app.state.database.engine.url),
                self.app.state.storage_root,
                "batch",
            )
        data = self.client.get(self.path, headers=operator).json()
        self.assertEqual(
            (data["state"], data["items"], data["total"]), ("ready", [], 0)
        )
        anonymous = type(self.client)(self.app)
        try:
            for method in ("GET", "POST"):
                self.assertEqual(anonymous.request(method, self.path).status_code, 401)
        finally:
            anonymous.close()

    def test_lost_lease_cannot_publish_and_recovery_does_not_mark_batch_failed(self):
        from delivery_note.workers.leases import (
            _claim_job,
            JobContext,
            LostJobLeaseError,
        )
        from delivery_note.workers.purchase_snapshot import execute_purchase_snapshot
        from delivery_note.workers.recovery import _recover_stale_jobs

        self.client.post(self.path, headers=self.headers)
        database = self.app.state.database
        job_id, _, _, token = _claim_job(database)
        with database.session() as session:
            job = session.get(Job, job_id)
            job.claim_token = "new-owner"
            job.heartbeat_at = datetime.utcnow() - timedelta(hours=1)
            job.attempts = 3
            session.commit()
        context = JobContext(database, job_id, token, lambda: None)
        with self.assertRaises(LostJobLeaseError):
            execute_purchase_snapshot(
                context, self.batch_id, self.app.state.storage_root
            )
        _recover_stale_jobs(database, queue="batch")
        with database.session() as session:
            self.assertEqual(session.get(Batch, self.batch_id).status, "succeeded")
            self.assertIsNone(session.get(Batch, self.batch_id).error_message)
            self.assertIsNone(session.get(Job, job_id).output_path)

    def test_all_source_files_and_unmatched_skus_are_covered_without_exceptions(self):
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == self.batch_id)
            )
            book = load_workbook(source.storage_path)
            book["明细"].append(["UNMATCHED", 19, "US站", "LN2608179025"])
            book.save(source.storage_path)
            book.close()
            for order, supplier in [(2, "GYS-1"), (3, "GYS-2")]:
                path = self.root / f"来源{order}.xlsx"
                path.write_bytes(self.self_operated_delivery_bytes())
                session.add(
                    BatchFile(
                        batch_id=self.batch_id,
                        original_name=path.name,
                        storage_path=str(path),
                        file_order=order,
                        supplier_code=supplier,
                    )
                )
            session.commit()
        self.client.post(self.path, headers=self.headers)
        with patch(
            "delivery_note.workers.purchase_snapshot.GerpgoClient.from_config"
        ) as factory:
            client = factory.return_value
            client.list_purchase_orders.side_effect = lambda **query: [
                {"code": query["supplier_code"], "supplierCode": query["supplier_code"]}
            ]
            client.purchase_order_detail.side_effect = lambda code: {
                "warehouseProcureItemVos": [
                    {
                        "procureItemVos": [
                            {
                                "supplierCode": code,
                                "product": sku,
                                "balanceQuantity": 8,
                                "arrivalMarketName": site,
                            }
                            for sku, site in [
                                ("SKU-A", "SEEKWAY:US"),
                                ("SKU-A", "SEEKWAY:CA"),
                                ("UNMATCHED", "SEEKWAY:US"),
                            ]
                        ]
                    }
                ]
            }
            run_once(
                str(self.app.state.database.engine.url),
                self.app.state.storage_root,
                "batch",
            )
        ready = self.client.get(self.path, headers=self.headers).json()
        self.assertEqual(
            (ready["supplier_count"], ready["sku_count"], ready["total"]), (2, 2, 5)
        )
        self.assertEqual(client.list_purchase_orders.call_count, 2)
        self.assertEqual(client.purchase_order_detail.call_count, 2)
        self.assertEqual(sum(row["sku"] == "UNMATCHED" for row in ready["items"]), 1)
