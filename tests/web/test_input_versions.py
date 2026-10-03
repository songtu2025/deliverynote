from io import BytesIO

from delivery_note.inbound.models import INBOUND_TEMPLATE_COLUMNS
from delivery_note.processing.models import IMPORT_COLUMNS
from tests.support.excel import make_import_template, make_template_preview_workbook
from tests.support.web_api import WebApiCase


class WebApiTests(WebApiCase):
    def test_uploaded_template_summary_and_preview_use_active_sheet(self) -> None:
        admin_headers = self.login("admin", "admin-pass")
        for kind, columns in (
            ("template", IMPORT_COLUMNS),
            ("inbound_template", INBOUND_TEMPLATE_COLUMNS),
        ):
            with self.subTest(kind=kind):
                workbook = make_template_preview_workbook(kind)
                payload = BytesIO()
                workbook.save(payload)
                uploaded = self.client.post(
                    f"/api/input-versions/{kind}",
                    headers=admin_headers,
                    data={"name": f"active-{kind}", "activate": "false"},
                    files={"file": ("template.xlsx", BytesIO(payload.getvalue()))},
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.text)
                version_id = uploaded.json()["id"]
                result = self.client.get(
                    f"/api/input-versions/{version_id}/inspection?offset=0&limit=1",
                    headers=admin_headers,
                )
                summary = self.client.get(
                    f"/api/input-versions/{version_id}/summary", headers=admin_headers
                )
                page = self.client.get(
                    f"/api/input-versions/{version_id}/preview?offset=1&limit=1",
                    headers=admin_headers,
                )
                for response in (result, summary, page):
                    self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(result.json()["summary"], summary.json())
                self.assertEqual(summary.json()["columns"], columns)
                self.assertEqual(summary.json()["row_count"], 2)
                self.assertEqual(
                    result.json()["preview"]["rows"][0][columns[0]], "活动示例"
                )
                self.assertEqual(page.json()["rows"][0][columns[0]], "活动数据")
                self.assertEqual(page.json()["columns"], columns)
                self.assertIsNone(page.json()["rows"][0][columns[-1]])
                self.assertIsNone(page.json()["rows"][0][columns[-2]])

    def test_template_upload_rejects_empty_example_without_changing_versions(
        self,
    ) -> None:
        admin_headers = self.login("admin", "admin-pass")
        before = self.client.get("/api/input-versions", headers=admin_headers).json()
        for mode in ("missing", "sparse", "empty"):
            with self.subTest(mode=mode):
                workbook = make_import_template()
                sheet = workbook.worksheets[0]
                if mode == "empty":
                    for cell in sheet[3]:
                        cell.value = ""
                else:
                    sheet.delete_rows(3)
                    if mode == "sparse":
                        sheet["A4"] = "示例行之外的内容"
                payload = BytesIO()
                workbook.save(payload)
                response = self.client.post(
                    "/api/input-versions/template",
                    headers=admin_headers,
                    data={"name": f"empty-template-{mode}", "activate": "true"},
                    files={"file": ("template.xlsx", BytesIO(payload.getvalue()))},
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(
                    response.json()["detail"],
                    "输入版本校验失败：官方模板缺少第 3 行示例格式",
                )
                after = self.client.get(
                    "/api/input-versions", headers=admin_headers
                ).json()
                self.assertEqual(after, before)
                uploaded = self.app.state.storage_root / "master" / "template"
                self.assertEqual(list(uploaded.glob("*")), [])

    def test_input_version_activation_keeps_one_active_version(self):
        admin_headers = self.login("admin", "admin-pass")
        created_ids = []
        for name, activate in (("purchase-v1", "true"), ("purchase-v2", "false")):
            response = self.client.post(
                "/api/input-versions/purchase",
                headers=admin_headers,
                data={"name": name, "activate": activate},
                files={
                    "file": (
                        f"{name}.xlsx",
                        BytesIO(self.workbook_bytes("purchase")),
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            created_ids.append(response.json()["id"])

        activated = self.client.post(
            f"/api/input-versions/{created_ids[1]}/activate",
            headers=admin_headers,
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        versions = self.client.get("/api/input-versions", headers=admin_headers).json()
        active_ids = [
            version["id"]
            for version in versions
            if version["kind"] == "purchase" and version["active"]
        ]
        self.assertEqual(active_ids, [created_ids[1]])

    def test_position_bootstrap_upload_is_allowed(self):
        admin_headers = self.login("admin", "admin-pass")

        response = self.client.post(
            "/api/input-versions/position",
            headers=admin_headers,
            data={"name": "position-bootstrap", "activate": "true"},
            files={
                "file": (
                    "position-bootstrap.xlsx",
                    BytesIO(self.workbook_bytes("position")),
                )
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["active"])

    def test_invalid_input_version_is_rejected_before_activation(self):
        admin_headers = self.login("admin", "admin-pass")
        response = self.client.post(
            "/api/input-versions/purchase",
            headers=admin_headers,
            data={"name": "broken-purchase", "activate": "true"},
            files={"file": ("broken.xlsx", BytesIO(b"not-an-excel-file"))},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("输入版本校验失败", response.json()["detail"])
        versions = self.client.get("/api/input-versions", headers=admin_headers).json()
        self.assertEqual(
            [version["kind"] for version in versions],
            ["inbound_template", "template"],
        )
        purchase_root = self.app.state.storage_root / "master" / "purchase"
        self.assertEqual(list(purchase_root.glob("*")), [])

    def test_supplier_upload_rejects_cross_supplier_identifier_conflicts(self):
        admin_headers = self.login("admin", "admin-pass")
        response = self.client.post(
            "/api/input-versions/supplier",
            headers=admin_headers,
            data={"name": "ambiguous-suppliers", "activate": "true"},
            files={
                "file": (
                    "supplier.xlsx",
                    BytesIO(
                        self.supplier_workbook_bytes(
                            [
                                ["GYS-1", "瑞智", "启用", "RIV"],
                                ["GYS-2", "瑞智雅", "启用", "RIVBOS"],
                            ]
                        )
                    ),
                )
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Excel 行 2, 3", response.json()["detail"])
        self.assertIn("匹配歧义", response.json()["detail"])
        versions = self.client.get("/api/input-versions", headers=admin_headers).json()
        self.assertFalse(
            any(version["name"] == "ambiguous-suppliers" for version in versions)
        )
