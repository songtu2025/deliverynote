from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import select

from delivery_note.config import SupplierIdentity
from delivery_note.excel_io import read_delivery_workbook
from delivery_note.web.models import Batch, BatchFile, ExceptionTransfer
from tests.support.exception_transfers import ExceptionTransferCase


class ExceptionTransferFileTests(ExceptionTransferCase):
    def test_target_locks_current_versions_without_changing_source_versions(self):
        uploaded = self.client.post(
            "/api/input-versions/product",
            headers=self.headers,
            data={"name": "product-v2", "activate": "true"},
            files={"file": ("product.xlsx", BytesIO(self.workbook_bytes("product")))},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        latest = {**self.versions, "product": uploaded.json()["id"]}
        response = self.transfer(3)
        self.assertEqual(response.status_code, 201, response.text)
        with self.app.state.database.session() as session:
            source = session.get(Batch, self.batch_id)
            target = session.get(Batch, response.json()["id"])
            self.assertEqual(source.product_version_id, self.versions["product"])
            for kind, version_id in latest.items():
                self.assertEqual(getattr(target, f"{kind}_version_id"), version_id)

    def test_transfer_ledger_prevents_deleting_batches_files_or_refreshing_source(self):
        target = self.transfer(3).json()["id"]
        for batch_id in (self.batch_id, target):
            with self.subTest(batch_id=batch_id):
                response = self.client.request(
                    "DELETE",
                    "/api/batches",
                    headers=self.headers,
                    json={"batch_ids": [batch_id]},
                )
                self.assertEqual(response.status_code, 409, response.text)
        source_file = self.client.get(
            f"/api/batches/{target}", headers=self.headers
        ).json()["files"][0]
        response = self.client.delete(
            f"/api/batches/{target}/files/{source_file['id']}", headers=self.headers
        )
        self.assertEqual(response.status_code, 409, response.text)
        response = self.client.post(
            f"/api/batches/{self.batch_id}/receipts/refresh", headers=self.headers
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.records()[0]["transferred_quantity"], 3)

    def test_delivery_file_reordering_and_preflight_keep_site_selection(self):
        target = self.transfer(3).json()["id"]
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == target)
            )
            file_id = source.id
            selected = source.receipt_sites.copy()
        response = self.client.put(
            f"/api/batches/{target}/files/order",
            headers=self.headers,
            json={"file_ids": [file_id]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(
            f"/api/batches/{target}/preflight", headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.app.state.database.session() as session:
            self.assertEqual(session.get(BatchFile, file_id).receipt_sites, selected)

    def test_source_files_preserve_selection_order_and_original_names(self):
        second = self.add_source(supplier_code="GYS-024", order=2)
        third = self.add_source(order=3)
        response = self.client.post(
            "/api/input-versions/supplier",
            headers=self.headers,
            data={"name": "供应商两家", "activate": "true"},
            files={
                "file": (
                    "supplier.xlsx",
                    BytesIO(
                        self.supplier_workbook_bytes(
                            [
                                ["GYS-023", "KuangBiao", "启用", ""],
                                ["GYS-024", "HaiLang", "启用", ""],
                            ]
                        )
                    ),
                )
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(
            f"/api/batches/{self.batch_id}/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={
                "name": "按选择顺序转交",
                "items": [
                    {
                        "exception_id": second,
                        "quantity": 2,
                        "full_site": "AMAZON:SEEKWAY:US",
                    },
                    {
                        "exception_id": self.exception_id,
                        "quantity": 3,
                        "full_site": "AMAZON:SEEKWAY:US",
                    },
                    {
                        "exception_id": third,
                        "quantity": 4,
                        "full_site": "AMAZON:SEEKWAY:US",
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        with self.app.state.database.session() as session:
            files = list(
                session.scalars(
                    select(BatchFile)
                    .where(BatchFile.batch_id == response.json()["id"])
                    .order_by(BatchFile.file_order)
                )
            )
            self.assertEqual(
                [source.supplier_code for source in files],
                ["GYS-024", "GYS-023", "GYS-023"],
            )
            self.assertEqual(
                [
                    read_delivery_workbook(Path(source.storage_path))["交货量"].tolist()
                    for source in files
                ],
                [[2], [3], [4]],
            )
            self.assertEqual(
                [source.original_name for source in files],
                [
                    "261008-HaiLang-2-交货194箱.xlsx",
                    "261008-KuangBiao-1-交货194箱.xlsx",
                    "261008-KuangBiao-3-交货194箱.xlsx",
                ],
            )
            transfers = list(session.scalars(select(ExceptionTransfer)))
            self.assertEqual(
                [item.target_file_id for item in transfers],
                [source.id for source in files],
            )
            self.assertTrue(all(source.receipt_sites for source in files))
            self.assertEqual(len(list(session.scalars(select(ExceptionTransfer)))), 3)

    def test_filename_resolver_must_return_original_supplier_code(self):
        with patch(
            "delivery_note.web.exception_transfer_files.resolve_supplier",
            return_value=SupplierIdentity("Other", "OTHER"),
        ):
            response = self.transfer()
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("不一致", response.json()["detail"])

    def test_file_limit_counts_sources_even_for_the_same_supplier(self):
        second = self.add_source(order=2)
        self.app.state.max_batch_upload_files = 1
        response = self.client.post(
            f"/api/batches/{self.batch_id}/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={
                "items": [
                    {
                        "exception_id": record_id,
                        "quantity": 3,
                        "full_site": "AMAZON:SEEKWAY:US",
                    }
                    for record_id in (self.exception_id, second)
                ]
            },
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertTrue(
            all(record["transferred_quantity"] == 0 for record in self.records())
        )

    def test_filename_sanitization_keeps_supplier_and_original_metadata(self):
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == self.batch_id)
            )
            source.original_name = "261008-KuangBiao:交货194箱.xlsx"
            session.commit()
        response = self.transfer(3)
        self.assertEqual(response.status_code, 201, response.text)
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == response.json()["id"])
            )
            self.assertEqual(source.original_name, "261008-KuangBiao_交货194箱.xlsx")
            self.assertEqual(source.supplier_code, "GYS-023")

    def test_self_check_failure_and_commit_failure_remove_every_file(self):
        for target, failure in (
            (
                "delivery_note.web.exception_transfer_files.read_delivery_workbook",
                ValueError("合成文件错误"),
            ),
            (
                "delivery_note.web.exception_transfers.Session.commit",
                RuntimeError("合成提交错误"),
            ),
        ):
            with self.subTest(target=target), patch(target, side_effect=failure):
                if isinstance(failure, ValueError):
                    self.assertEqual(self.transfer().status_code, 400)
                else:
                    with self.assertRaisesRegex(RuntimeError, "合成提交错误"):
                        self.transfer()
            with self.app.state.database.session() as session:
                self.assertEqual(len(list(session.scalars(select(Batch)))), 1)
                self.assertEqual(
                    len(list(session.scalars(select(ExceptionTransfer)))), 0
                )
            self.assertFalse(list((self.root / "storage" / "batches").rglob("*.xlsx")))
            self.assertFalse(
                list(
                    (self.root / "storage" / "temporary" / "exception-transfers").rglob(
                        "*.xlsx"
                    )
                )
            )

    def test_transfer_does_not_override_normal_split_restriction(self):
        response = self.client.put(
            f"/api/exceptions/{self.exception_id}/split",
            headers=self.headers,
            json={"parts": [{"quantity": 8}]},
        )
        self.assertEqual(response.status_code, 409)

    def test_file_reader_detects_short_site_normalization(self):
        from delivery_note.web.exception_transfer_files import TransferFile

        group = TransferFile("GYS-023", "261008-KuangBiao-194箱.xlsx")
        group.add("SKU-A", "AMAZON:SHOP:US站", 1)
        suppliers = pd.DataFrame(
            [["GYS-023", "KuangBiao", "启用"]],
            columns=["供应商编号", "供应商名称", "状态"],
        )
        with self.assertRaisesRegex(Exception, "自检失败"):
            group.write(self.root, suppliers)
