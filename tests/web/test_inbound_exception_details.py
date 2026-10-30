import json
from unittest.mock import patch

from delivery_note.gerpgo import GerpgoError
from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    SelfOperatedBatch,
    Job,
)
from delivery_note.web.purchase_snapshot import snapshot_sources
from tests.support.web_api import WebApiCase


class InboundExceptionDetailsTests(WebApiCase):
    def setUp(self):
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.upload_active_versions(self.headers)
        response = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "合成异常查询"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.batch_id = response.json()["id"]
        row = {
            "SKU": "SKU-A",
            "平台站点": "AMAZON:SEEKWAY:US",
            "入库单号": "WV-1",
            "关联采购单": "PO-1",
            "关联交货单/调拨单": "LN-1",
            "入库仓": "仓库甲",
            "已入库": 3,
            "正常分配数量": 67,
            "规则内超收数量": 5,
            "本次入库": 72,
        }
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "succeeded"
            profile = session.get(SelfOperatedBatch, self.batch_id)
            profile.receipt_snapshot = {"captured_at": "2026-10-30T00:00:00+00:00"}
            source = BatchFile(
                batch_id=batch.id,
                original_name="合成来源.xlsx",
                storage_path="synthetic",
                file_order=1,
                supplier_name="合成供应商",
                supplier_code="GYS-1",
                delivery_total=82,
                import_total=74,
                manual_total=8,
                import_rows=[
                    row,
                    {
                        **row,
                        "SKU": "SKU-B",
                        "正常分配数量": 1,
                        "规则内超收数量": 0,
                        "本次入库": 1,
                    },
                    {
                        **row,
                        "平台站点": "AMAZON:SEEKWAY:UK",
                        "正常分配数量": 1,
                        "规则内超收数量": 0,
                        "本次入库": 1,
                    },
                ],
            )
            session.add(source)
            session.flush()
            exception = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-A",
                original_site="US",
                full_site="AMAZON:SEEKWAY:US",
                delivery_quantity=80,
                allocated_quantity=72,
                purchase_allocated_quantity=67,
                overreceipt_allocated_quantity=5,
                manual_quantity=8,
                reason="超出允许超收量",
                status="pending",
            )
            session.add(exception)
            session.commit()
            self.exception_id = exception.id
            self.source_id = source.id

    def path(self, suffix):
        return f"/api/exceptions/{self.exception_id}/{suffix}"

    def test_allocation_is_scoped_to_the_source_sku_and_site_without_erp_calls(self):
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            response = self.client.get(
                self.path("inbound-allocation"), headers=self.headers
            )
        self.assertEqual(response.status_code, 200, response.text)
        factory.assert_not_called()
        data = response.json()
        self.assertEqual(data["supplier_code"], "GYS-1")
        self.assertEqual(len(data["items"]), 1)
        row = data["items"][0]
        self.assertEqual(
            (row["po_code"], row["inbound_no"], row["delivery_no"]),
            ("PO-1", "WV-1", "LN-1"),
        )
        self.assertEqual(
            (
                row["normal_quantity"],
                row["overreceipt_quantity"],
                row["current_quantity"],
            ),
            (67, 5, 72),
        )
        self.assertEqual(row["history_quantity"], 3)
        self.assertNotIn("storage_path", data)
        self.assertNotIn("import_rows", data)
        with self.app.state.database.session() as session:
            source = session.get(BatchFile, self.source_id)
            self.assertEqual((source.import_total, source.manual_total), (74, 8))
            self.assertEqual(
                session.get(ExceptionRecord, self.exception_id).status, "pending"
            )

    def test_purchase_snapshot_uses_server_side_identity_and_operator_can_read(
        self,
    ):
        self.create_operator(self.headers)
        operator = self.login("operator", "operator-pass")
        storage = self.app.state.storage_root
        path = (
            storage
            / "batches"
            / str(self.batch_id)
            / "purchase-snapshots"
            / "test.json"
        )
        path.parent.mkdir(parents=True)
        with self.app.state.database.session() as session:
            _, signature = snapshot_sources(session, session.get(Batch, self.batch_id))
            row = {
                "supplier_code": "GYS-1",
                "sku": "SKU-A",
                "po_code": "PO-1",
                "remaining_quantity": 8,
            }
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_signature": signature,
                        "snapshot_id": "test",
                        "completed_at": "2026-10-30T00:00:00Z",
                        "items": [
                            row,
                            {**row, "sku": "SKU-B"},
                            {**row, "supplier_code": "OTHER"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            session.add(
                Job(
                    batch_id=self.batch_id,
                    kind="purchase_snapshot",
                    status="succeeded",
                    output_path=str(path),
                )
            )
            session.commit()
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            response = self.client.get(
                self.path("purchase-options") + "?sku=SKU-B&supplier_code=OTHER",
                headers=operator,
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [row])
        self.assertTrue(response.json()["queried_at"])
        factory.assert_not_called()

    def test_missing_snapshot_does_not_prevent_allocation_read(self):
        with patch(
            "delivery_note.gerpgo.GerpgoClient.from_config",
            side_effect=GerpgoError("不应对外显示的上游内容"),
        ):
            response = self.client.get(
                self.path("purchase-options"), headers=self.headers
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("不应对外", response.text)
        self.assertEqual(
            self.client.get(
                self.path("inbound-allocation"), headers=self.headers
            ).status_code,
            200,
        )

    def test_rejects_missing_wrong_workflow_and_uncomputed_records_before_querying(
        self,
    ):
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            missing = self.client.get(
                "/api/exceptions/99999/purchase-options", headers=self.headers
            )
            self.assertEqual(missing.status_code, 404)
            with self.app.state.database.session() as session:
                session.get(Batch, self.batch_id).status = "running"
                session.commit()
            self.assertEqual(
                self.client.get(
                    self.path("purchase-options"), headers=self.headers
                ).status_code,
                409,
            )
            with self.app.state.database.session() as session:
                session.delete(session.get(SelfOperatedBatch, self.batch_id))
                session.commit()
            self.assertEqual(
                self.client.get(
                    self.path("inbound-allocation"), headers=self.headers
                ).status_code,
                404,
            )
        factory.assert_not_called()

    def test_unknown_supplier_and_no_matching_allocations_are_distinguished(self):
        with self.app.state.database.session() as session:
            source = session.get(BatchFile, self.source_id)
            source.supplier_code = ""
            source.import_rows = []
            session.commit()
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            self.assertEqual(
                self.client.get(
                    self.path("purchase-options"), headers=self.headers
                ).status_code,
                409,
            )
        factory.assert_not_called()
        response = self.client.get(
            self.path("inbound-allocation"), headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    def test_both_routes_require_authentication(self):
        anonymous = type(self.client)(self.app)
        try:
            for suffix in ("purchase-options", "inbound-allocation"):
                self.assertEqual(anonymous.get(self.path(suffix)).status_code, 401)
        finally:
            anonymous.close()
