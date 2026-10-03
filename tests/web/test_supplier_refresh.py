from tests.support.web_api import WebApiCase
from io import BytesIO

from sqlalchemy import select


from delivery_note.web.models import (
    Batch,
    InputVersion,
)


class WebApiTests(WebApiCase):
    def test_admin_refreshes_draft_supplier_version_and_alias_preflight_passes(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        operator_headers = self.login("operator", "operator-pass")
        original_ids = self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "供应商别名批次"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]

        replacement = self.client.post(
            "/api/input-versions/supplier",
            headers=admin_headers,
            data={"name": "supplier-alias-v2", "activate": "true"},
            files={
                "file": (
                    "supplier-alias.xlsx",
                    BytesIO(
                        self.supplier_workbook_bytes(
                            [["STGYS001", "RUIZY", "启用", "瑞智雅|RIVBOS"]]
                        )
                    ),
                )
            },
        )
        self.assertEqual(replacement.status_code, 201, replacement.text)
        replacement_id = replacement.json()["id"]
        self.assertNotEqual(original_ids["supplier"], replacement_id)

        forbidden = self.client.post(
            f"/api/batches/{batch_id}/refresh-supplier-version",
            headers=operator_headers,
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        refreshed = self.client.post(
            f"/api/batches/{batch_id}/refresh-supplier-version",
            headers=admin_headers,
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["version_ids"]["supplier"], replacement_id)
        self.assertEqual(refreshed.json()["versions"]["supplier"]["id"], replacement_id)

        upload = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={
                "file": (
                    "260903-瑞智雅RIVBOS眼镜交货单-发货53箱 (1).xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=admin_headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")

        logs = self.client.get("/api/audit-logs", headers=admin_headers).json()
        refresh_log = next(
            log
            for log in logs
            if log["action"] == "refresh_batch_supplier_version"
            and log["entity_id"] == str(batch_id)
        )
        self.assertEqual(
            refresh_log["details"],
            {
                "previous_supplier_version_id": original_ids["supplier"],
                "supplier_version_id": replacement_id,
            },
        )

    def test_supplier_refresh_rejects_non_draft_and_missing_active_version(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "刷新状态限制"},
        )
        batch_id = created.json()["id"]

        for batch_status in ("running", "failed", "succeeded"):
            with self.subTest(status=batch_status):
                with self.app.state.database.session() as session:
                    batch = session.get(Batch, batch_id)
                    batch.status = batch_status
                    session.commit()
                response = self.client.post(
                    f"/api/batches/{batch_id}/refresh-supplier-version",
                    headers=admin_headers,
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("仅草稿状态", response.json()["detail"])

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "draft"
            for version in session.scalars(
                select(InputVersion).where(InputVersion.kind == "supplier")
            ):
                version.active = False
            session.commit()
        missing = self.client.post(
            f"/api/batches/{batch_id}/refresh-supplier-version",
            headers=admin_headers,
        )
        self.assertEqual(missing.status_code, 409, missing.text)
        self.assertIn("没有启用的供应商资料", missing.json()["detail"])
