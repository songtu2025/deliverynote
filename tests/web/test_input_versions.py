from tests.support.web_api import WebApiCase
from io import BytesIO


class WebApiTests(WebApiCase):
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
