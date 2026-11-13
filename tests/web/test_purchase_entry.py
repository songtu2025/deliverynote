"""采购单独立入口的权限、上传和版本锁定契约。"""

from io import BytesIO
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from httpx2 import Response
from openpyxl import load_workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from delivery_note.web.models import AuditLog, InputVersion
from delivery_note.purchase_entry.models import PurchaseConversion
from delivery_note.web import purchase_entry_service
from sqlalchemy import select
from tests.web.purchase_entry_support import PurchaseEntryCase, workbook_payload


class PurchaseEntryTests(PurchaseEntryCase):
    def _post(
        self,
        action: str,
        headers: dict[str, str],
        versions: dict[str, int] | None = None,
        *,
        mode: str = "merged",
        upload: tuple[str, bytes] | None = None,
    ) -> Response:
        filename, payload = upload or (
            "甲厂-采购单.xlsx",
            self.purchase_files["source"].read_bytes(),
        )
        return self.client.post(
            f"/api/purchase-entry/{action}",
            headers=headers,
            data={"mode": mode, "version_ids": json.dumps(versions or {})},
            files={
                "file": (
                    filename,
                    BytesIO(payload),
                )
            },
        )

    def _temporary_files(self) -> list[Path]:
        return list((self.app.state.storage_root / "purchase-entry").rglob("*"))

    def test_preview_and_export_require_login(self) -> None:
        for action in ("preview", "export"):
            response = self.client.post(
                f"/api/purchase-entry/{action}",
                data={"mode": "merged", "version_ids": "{}"},
                files={"file": ("purchase.xlsx", BytesIO(b"invalid"))},
            )
            self.assertEqual(response.status_code, 401, response.text)

    def test_preview_explains_missing_active_inputs(self) -> None:
        headers = self.login("admin", "admin-pass")
        response = self.client.post(
            "/api/purchase-entry/preview",
            headers=headers,
            files={"file": ("purchase.xlsx", BytesIO(b"invalid"))},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("供应商资料", response.json()["detail"])
        self.assertIn("商品信息", response.json()["detail"])
        self.assertIn("SKU仓库", response.json()["detail"])

    def test_operator_preview_and_export_excel_and_zip_without_persisting_result(
        self,
    ) -> None:
        admin = self.login("admin", "admin-pass")
        versions = self.upload_purchase_inputs(admin)
        self.create_operator(admin)
        operator = self.login("operator", "operator-pass")
        preview = self._post("preview", operator)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["versions"], versions)
        self.assertEqual(preview.json()["row_count"], 3)
        self.assertEqual(preview.json()["total_quantity"], 60)
        self.assertEqual(self._temporary_files(), [])
        for mode, mime in (
            (
                "merged",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            ("split", "application/zip"),
        ):
            response = self._post("export", operator, versions, mode=mode)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["content-type"], mime)
            self.assertIn("attachment", response.headers["content-disposition"])
            payloads = [response.content]
            if mode == "split":
                with ZipFile(BytesIO(response.content)) as archive:
                    self.assertEqual(len(archive.namelist()), 2)
                    payloads = [archive.read(name) for name in archive.namelist()]
            quantities = 0
            for payload in payloads:
                workbook = load_workbook(BytesIO(payload), read_only=True)
                self.assertEqual(workbook.sheetnames, ["采购单录入模板"])
                sheet = workbook.active
                assert isinstance(sheet, ReadOnlyWorksheet)
                for row in sheet.iter_rows(min_row=3, values_only=True):
                    quantity = row[15]
                    assert isinstance(quantity, int) and not isinstance(quantity, bool)
                    quantities += quantity
                workbook.close()
            self.assertEqual(quantities, 60)
            self.assertEqual(self._temporary_files(), [])
        with self.app.state.database.session() as session:
            audit = session.scalars(
                select(AuditLog).where(AuditLog.action == "export_purchase_entry")
            ).all()
            self.assertEqual(len(audit), 2)
            self.assertEqual(audit[0].details["versions"], versions)
            self.assertNotIn("preview", audit[0].details)

    def test_export_keeps_preview_versions_after_new_inputs_activated(self) -> None:
        headers = self.login("admin", "admin-pass")
        versions = self.upload_purchase_inputs(headers)
        preview = self._post("preview", headers)
        self.assertEqual(preview.status_code, 200, preview.text)
        rows_by_kind: dict[str, list[list[object]]] = {
            "sku_warehouse": [
                ["SKU", "仓库"],
                ["SKU-A", "新仓库"],
                ["SKU-B", "新仓库"],
            ],
            "product": [
                ["国家", "SKU", "店铺/站点", "MSKU", "品类A", "锁仓MKSU"],
                ["US", "SKU-A", "新店铺/US", "新MSKU", "合成品类", ""],
            ],
        }
        for kind, rows in rows_by_kind.items():
            response = self.client.post(
                f"/api/input-versions/{kind}",
                headers=headers,
                data={"name": f"{kind}-v2", "activate": "true"},
                files={"file": ("v2.xlsx", BytesIO(workbook_payload(rows)))},
            )
            self.assertEqual(response.status_code, 201, response.text)
        exported = self._post("export", headers, preview.json()["versions"])
        self.assertEqual(exported.status_code, 200, exported.text)
        workbook = load_workbook(BytesIO(exported.content), read_only=True)
        sheet = workbook.active
        assert isinstance(sheet, ReadOnlyWorksheet)
        self.assertEqual(sheet["J3"].value, "普通仓")
        self.assertEqual(sheet["L3"].value, "AMAZON:店铺/US")
        self.assertEqual(sheet["N3"].value, "MSKU-A")
        workbook.close()
        self.assertEqual(versions, preview.json()["versions"])

    def test_invalid_files_modes_and_versions_are_rejected_and_cleaned(self) -> None:
        headers = self.login("admin", "admin-pass")
        versions = self.upload_purchase_inputs(headers)
        for action in ("preview", "export"):
            for filename, payload, status in (
                ("purchase.xls", b"invalid", 400),
                ("purchase.xlsx", b"invalid", 400),
                ("purchase.xlsx", self.purchase_files["source"].read_bytes(), 413),
            ):
                with self.subTest(action=action, filename=filename, status=status):
                    limit = 5 if status == 413 else 104857600
                    with patch.object(self.app.state, "max_upload_bytes", limit):
                        response = self._post(
                            action,
                            headers,
                            versions,
                            upload=(filename, payload),
                        )
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertNotIn(str(self.root), response.json()["detail"])
                    self.assertEqual(self._temporary_files(), [])
        invalid_versions = [
            dict(),
            {**versions, "supplier": -1},
            {**versions, "supplier": versions["product"]},
            {
                ("purchase_mapping" if kind == "product" else kind): value
                for kind, value in versions.items()
            },
        ]
        for value in invalid_versions:
            response = self._post("export", headers, value)
            self.assertEqual(response.status_code, 400, response.text)
        response = self._post("export", headers, versions, mode="unknown")
        self.assertEqual(response.status_code, 400, response.text)

    def test_failed_conversion_does_not_leave_temporary_files(self) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_purchase_inputs(headers)
        response = self._post(
            "preview",
            headers,
            upload=("未知供应商.xlsx", self.purchase_files["source"].read_bytes()),
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._temporary_files(), [])

    def test_export_validates_locked_template_before_conversion(self) -> None:
        headers = self.login("admin", "admin-pass")
        versions = self.upload_purchase_inputs(headers)
        with self.app.state.database.session() as session:
            version = session.get(InputVersion, versions["purchase_template"])
            version.storage_path = str(self.purchase_files["source"])
            session.commit()
        with patch(
            "delivery_note.web.purchase_entry_service.convert_purchase"
        ) as convert:
            response = self._post("export", headers, versions)
        self.assertEqual(response.status_code, 400, response.text)
        convert.assert_not_called()
        self.assertEqual(self._temporary_files(), [])

    def test_export_rejects_invalid_version_json_and_missing_locked_file(self) -> None:
        headers = self.login("admin", "admin-pass")
        versions = self.upload_purchase_inputs(headers)
        for encoded in (
            "not-json",
            "[]",
            "null",
            json.dumps({**versions, "supplier": True}),
        ):
            response = self.client.post(
                "/api/purchase-entry/export",
                headers=headers,
                data={"mode": "merged", "version_ids": encoded},
                files={
                    "file": (
                        "甲厂.xlsx",
                        BytesIO(self.purchase_files["source"].read_bytes()),
                    )
                },
            )
            self.assertEqual(response.status_code, 400, response.text)
        with self.app.state.database.session() as session:
            version = session.get(InputVersion, versions["product"])
            Path(version.storage_path).unlink()
        response = self._post("export", headers, versions)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertNotIn(str(self.root), response.json()["detail"])
        self.assertEqual(self._temporary_files(), [])

    def test_corrupt_xlsx_archive_returns_a_readable_error_and_cleans_upload(
        self,
    ) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_purchase_inputs(headers)
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("unexpected.txt", "broken workbook")
        response = self._post(
            "preview", headers, upload=("甲厂.xlsx", buffer.getvalue())
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._temporary_files(), [])

    def test_purchase_conversion_runs_in_the_worker_thread(self) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_purchase_inputs(headers)
        original = purchase_entry_service.convert_purchase
        observed = []

        def inspect_loop(
            path: Path, filename: str, supplier: Path, product: Path, warehouse: Path
        ) -> PurchaseConversion:
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            observed.append(True)
            return original(path, filename, supplier, product, warehouse)

        with patch.object(
            purchase_entry_service, "convert_purchase", side_effect=inspect_loop
        ):
            response = self._post("preview", headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(observed, [True])
