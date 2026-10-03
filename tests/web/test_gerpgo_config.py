from tests.support.web_api import WebApiCase
from unittest.mock import patch


import delivery_note.web.gerpgo_routes as gerpgo_routes_module
from delivery_note.gerpgo import GerpgoError, load_gerpgo_settings


class WebApiTests(WebApiCase):
    def test_admin_can_test_and_save_gerpgo_config(self):
        admin_headers = self.login("admin", "admin-pass")
        payload = {
            "base_url": "https://openapi.example.test/",
            "app_id": "app-001",
            "app_key": "secret-key",
        }

        with patch.object(
            gerpgo_routes_module.GerpgoClient,
            "authenticate",
        ) as authenticate:
            updated = self.client.put(
                "/api/admin/integrations/gerpgo",
                headers=admin_headers,
                json=payload,
            )

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(authenticate.call_count, 1)
        self.assertTrue(updated.json()["configured"])
        self.assertEqual(updated.json()["source"], "managed")
        self.assertEqual(updated.json()["base_url"], "https://openapi.example.test")
        self.assertEqual(updated.json()["app_id_hint"], "ap***01")
        self.assertNotIn("secret-key", updated.text)
        self.assertNotIn("app_key", updated.json())

        status_response = self.client.get(
            "/api/admin/integrations/gerpgo",
            headers=admin_headers,
        )
        self.assertEqual(status_response.status_code, 200, status_response.text)
        self.assertEqual(status_response.json(), updated.json())

        purchase_status = self.client.get(
            "/api/purchase-sync",
            headers=admin_headers,
        )
        self.assertTrue(purchase_status.json()["configured"])

        settings = load_gerpgo_settings(
            self.app.state.storage_root,
        )
        self.assertEqual(settings.app_id, "app-001")
        self.assertEqual(settings.app_key, "secret-key")

        audit_logs = self.client.get(
            "/api/audit-logs",
            headers=admin_headers,
        ).json()
        audit = next(
            item for item in audit_logs if item["action"] == "update_gerpgo_config"
        )
        self.assertNotIn("app_key", audit["details"])
        self.assertNotIn("secret-key", str(audit))

    @patch.dict("os.environ", {}, clear=True)
    def test_unconfigured_gerpgo_uses_official_default_url(self):
        admin_headers = self.login("admin", "admin-pass")

        response = self.client.get(
            "/api/admin/integrations/gerpgo",
            headers=admin_headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["configured"])
        self.assertEqual(
            response.json()["base_url"],
            "https://open.gerpgo.com/api/open",
        )

    def test_operator_cannot_update_gerpgo_config(self):
        admin_headers = self.login("admin", "admin-pass")
        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")

        response = self.client.put(
            "/api/admin/integrations/gerpgo",
            headers=operator_headers,
            json={
                "base_url": "https://openapi.example.test",
                "app_id": "app",
                "app_key": "key",
            },
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertFalse(
            (self.app.state.storage_root / "config" / "gerpgo.json").exists()
        )

    def test_failed_gerpgo_connection_does_not_save_config(self):
        admin_headers = self.login("admin", "admin-pass")
        with patch.object(
            gerpgo_routes_module.GerpgoClient,
            "authenticate",
            side_effect=GerpgoError("凭证无效"),
        ):
            response = self.client.put(
                "/api/admin/integrations/gerpgo",
                headers=admin_headers,
                json={
                    "base_url": "https://openapi.example.test",
                    "app_id": "wrong-app",
                    "app_key": "wrong-key",
                },
            )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("积加连接验证失败", response.json()["detail"])
        self.assertFalse(
            (self.app.state.storage_root / "config" / "gerpgo.json").exists()
        )
