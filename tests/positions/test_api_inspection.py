from tests.support.position_api import PositionApiCase
from io import BytesIO

from openpyxl import Workbook

from delivery_note.web.models import (
    Batch,
    User,
)


class PositionDraftApiTests(PositionApiCase):
    def test_version_summary_preview_and_download(self):
        version_id = self.version["id"]
        summary = self.client.get(
            f"/api/input-versions/{version_id}/summary",
            headers=self.admin_headers,
        )
        preview = self.client.get(
            f"/api/input-versions/{version_id}/preview",
            headers=self.admin_headers,
        )
        inspection = self.client.get(
            f"/api/input-versions/{version_id}/inspection",
            headers=self.admin_headers,
        )
        download = self.client.get(
            f"/api/input-versions/{version_id}/download",
            headers=self.admin_headers,
        )

        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["metrics"]["sites"], 1)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["rows"][0]["积加SKU"], "SKU-A")
        self.assertEqual(preview.json()["total"], 1)
        self.assertEqual(preview.json()["limit"], 20)
        self.assertEqual(inspection.status_code, 200, inspection.text)
        self.assertEqual(
            inspection.json()["summary"]["metrics"]["sites"],
            1,
        )
        self.assertEqual(
            inspection.json()["preview"]["rows"][0]["积加SKU"],
            "SKU-A",
        )
        self.assertEqual(inspection.json()["preview"]["limit"], 20)
        self.assertEqual(download.status_code, 200, download.text)
        self.assertIn("position-v1.xlsx", download.headers["content-disposition"])
        self.assertGreater(len(download.content), 0)

        for suffix in ("preview", "inspection"):
            for query in ("offset=-1", "limit=0", "limit=201"):
                invalid = self.client.get(
                    f"/api/input-versions/{version_id}/{suffix}?{query}",
                    headers=self.admin_headers,
                )
                self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_shared_upload_limit_accepts_boundary_and_rejects_overflow_without_files(
        self,
    ):
        purchase_workbook = Workbook()
        purchase_sheet = purchase_workbook.active
        purchase_sheet.append(
            ["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"]
        )
        purchase_sheet.append(
            [
                "待交货",
                "KuangBiao",
                "SKU-A",
                "AMAZON:SEEKWAY:US",
                "水鞋-广州仓",
                100,
            ]
        )
        purchase_output = BytesIO()
        purchase_workbook.save(purchase_output)
        purchase_payload = purchase_output.getvalue()
        self.app.state.max_upload_bytes = len(purchase_payload)

        exact_version = self.client.post(
            "/api/input-versions/purchase",
            headers=self.admin_headers,
            data={"name": "purchase-limit-exact", "activate": "false"},
            files={"file": ("exact.xlsx", BytesIO(purchase_payload))},
        )
        self.assertEqual(exact_version.status_code, 201, exact_version.text)
        master_files = set((self.storage / "master" / "purchase").iterdir())
        oversized_version = self.client.post(
            "/api/input-versions/purchase",
            headers=self.admin_headers,
            data={"name": "purchase-limit-over", "activate": "false"},
            files={"file": ("over.xlsx", BytesIO(purchase_payload + b"x"))},
        )
        self.assertEqual(oversized_version.status_code, 413, oversized_version.text)
        self.assertEqual(
            set((self.storage / "master" / "purchase").iterdir()),
            master_files,
        )

        payload = self.position_bytes()
        self.app.state.max_upload_bytes = len(payload)
        draft = self.create_draft()
        exact_import = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("exact.xlsx", BytesIO(payload))},
        )
        self.assertEqual(exact_import.status_code, 200, exact_import.text)
        import_files = set((self.storage / "temporary" / "position-imports").iterdir())
        oversized_import = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("over.xlsx", BytesIO(payload + b"x"))},
        )
        self.assertEqual(oversized_import.status_code, 413, oversized_import.text)
        self.assertEqual(
            set((self.storage / "temporary" / "position-imports").iterdir()),
            import_files,
        )

        with self.app.state.database.session() as session:
            admin = session.query(User).filter_by(username="admin").one()
            batch = Batch(
                name="upload-limit",
                created_by=admin.id,
                purchase_version_id=self.version["id"],
                product_version_id=self.version["id"],
                supplier_version_id=self.version["id"],
                position_version_id=self.version["id"],
                template_version_id=self.version["id"],
            )
            session.add(batch)
            session.commit()
            batch_id = batch.id
        exact_batch = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=self.admin_headers,
            files={"file": ("exact.xlsx", BytesIO(payload))},
        )
        self.assertEqual(exact_batch.status_code, 201, exact_batch.text)
        batch_files = set(
            (self.storage / "batches" / str(batch_id) / "inputs").iterdir()
        )
        oversized_batch = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=self.admin_headers,
            files={"file": ("over.xlsx", BytesIO(payload + b"x"))},
        )
        self.assertEqual(oversized_batch.status_code, 413, oversized_batch.text)
        self.assertEqual(
            set((self.storage / "batches" / str(batch_id) / "inputs").iterdir()),
            batch_files,
        )
