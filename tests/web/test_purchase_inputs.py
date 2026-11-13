"""采购资料与既有管理员维护和检查接口的集成。"""

from io import BytesIO
from unittest.mock import patch

from delivery_note.web.input_versions import INPUT_KINDS
from tests.web.purchase_entry_support import PurchaseEntryCase, workbook_payload


class PurchaseInputTests(PurchaseEntryCase):
    def test_removed_mapping_upload_is_rejected_without_creating_version(self) -> None:
        headers = self.login("admin", "admin-pass")
        before = self.client.get("/api/input-versions", headers=headers).json()
        response = self.client.post(
            "/api/input-versions/purchase_mapping",
            headers=headers,
            data={"name": "removed-mapping", "activate": "true"},
            files={
                "file": (
                    "mapping.xlsx",
                    BytesIO(
                        workbook_payload(
                            [
                                ["国家", "SKU", "店铺/站点", "MSKU"],
                                ["US", "SKU-A", "店铺/US", "MSKU-A"],
                            ]
                        )
                    ),
                )
            },
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(
            self.client.get("/api/input-versions", headers=headers).json(), before
        )

    def test_legacy_product_upload_succeeds_but_purchase_explains_missing_columns(
        self,
    ) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_purchase_inputs(headers)
        response = self.client.post(
            "/api/input-versions/product",
            headers=headers,
            data={"name": "legacy-product", "activate": "true"},
            files={
                "file": (
                    "legacy.xlsx",
                    BytesIO(
                        workbook_payload(
                            [
                                ["SKU", "店铺/站点", "品类A", "锁仓MKSU"],
                                ["SKU-A", "店铺/US", "合成品类", ""],
                            ]
                        )
                    ),
                )
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        preview = self.client.post(
            "/api/purchase-entry/preview",
            headers=headers,
            files={
                "file": (
                    "甲厂.xlsx",
                    BytesIO(self.purchase_files["source"].read_bytes()),
                )
            },
        )
        self.assertEqual(preview.status_code, 400, preview.text)
        for label in ("商品信息", "国家", "MSKU"):
            self.assertIn(label, preview.json()["detail"])
        self.assertEqual(
            list((self.app.state.storage_root / "purchase-entry").rglob("*")), []
        )

    def test_openapi_describes_upload_fields_and_binary_exports(self) -> None:
        schema = self.app.openapi()
        for action in ("preview", "export"):
            operation = schema["paths"][f"/api/purchase-entry/{action}"]["post"]
            body = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
            definition = schema["components"]["schemas"][body["$ref"].rsplit("/", 1)[1]]
            self.assertIn("file", definition["required"])
            if action == "export":
                self.assertIn("version_ids", definition["required"])
                self.assertEqual(definition["properties"]["mode"]["default"], "merged")
                response_types = operation["responses"]["200"]["content"]
                self.assertIn("application/zip", response_types)
                self.assertIn(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    response_types,
                )

    def test_new_inputs_upload_inspect_and_preserve_delivery_requirements(self) -> None:
        headers = self.login("admin", "admin-pass")
        versions = self.upload_purchase_inputs(headers)
        self.assertEqual(
            INPUT_KINDS, ("purchase", "product", "supplier", "position", "template")
        )
        self.assertEqual(len(versions), 4)
        for kind in ("product", "sku_warehouse", "purchase_template"):
            with self.subTest(kind=kind):
                response = self.client.get(
                    f"/api/input-versions/{versions[kind]}/inspection", headers=headers
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["summary"]["kind"], kind)
                self.assertTrue(response.json()["preview"]["columns"])
                if kind == "product":
                    self.assertIn("国家", response.json()["preview"]["columns"])
                    self.assertIn("MSKU", response.json()["preview"]["columns"])

    def test_new_inputs_require_admin_and_xlsx(self) -> None:
        admin = self.login("admin", "admin-pass")
        self.create_operator(admin)
        operator = self.login("operator", "operator-pass")
        for kind in ("sku_warehouse", "purchase_template"):
            for headers, suffix, status in (
                (operator, ".xlsx", 403),
                (admin, ".xls", 400),
            ):
                response = self.client.post(
                    f"/api/input-versions/{kind}",
                    headers=headers,
                    data={"name": "invalid", "activate": "true"},
                    files={"file": (f"invalid{suffix}", BytesIO(b"invalid"))},
                )
                self.assertEqual(response.status_code, status, response.text)

    def test_invalid_new_inputs_leave_no_files_or_versions(self) -> None:
        headers = self.login("admin", "admin-pass")
        before = self.client.get("/api/input-versions", headers=headers).json()
        for kind in ("sku_warehouse", "purchase_template"):
            for payload in (b"broken", workbook_payload([["错误列"], ["错误数据"]])):
                response = self.client.post(
                    f"/api/input-versions/{kind}",
                    headers=headers,
                    data={"name": f"broken-{kind}", "activate": "true"},
                    files={"file": ("broken.xlsx", BytesIO(payload))},
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertNotIn(str(self.root), response.json()["detail"])
        self.assertEqual(
            self.client.get("/api/input-versions", headers=headers).json(), before
        )
        self.assertEqual(
            list((self.app.state.storage_root / "master").rglob("*.xlsx")), []
        )

    def test_new_input_uploads_preserve_versions_when_too_large(self) -> None:
        headers = self.login("admin", "admin-pass")
        before = self.client.get("/api/input-versions", headers=headers).json()
        for kind in ("sku_warehouse", "purchase_template"):
            with patch.object(self.app.state, "max_upload_bytes", 4):
                response = self.client.post(
                    f"/api/input-versions/{kind}",
                    headers=headers,
                    data={"name": "oversized", "activate": "true"},
                    files={"file": ("oversized.xlsx", BytesIO(b"large"))},
                )
            self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(
            self.client.get("/api/input-versions", headers=headers).json(), before
        )
        self.assertEqual(
            [
                path
                for path in (self.app.state.storage_root / "master").rglob("*")
                if path.is_file()
            ],
            [],
        )
