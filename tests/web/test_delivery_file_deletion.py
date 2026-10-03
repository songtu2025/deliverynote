from tests.support.web_api import WebApiCase
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


from delivery_note.web.models import (
    Batch,
    BatchFile,
)


class WebApiTests(WebApiCase):
    def test_single_file_delete_succeeds_when_file_cleanup_fails(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "单文件清理失败"},
            files={"files": ("交货单.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        source_id = created.json()["files"][0]["id"]
        with self.app.state.database.session() as session:
            storage_path = Path(session.get(BatchFile, source_id).storage_path)

        with (
            patch.object(Path, "unlink", side_effect=PermissionError("denied")),
            self.assertLogs("delivery_note.web.api", level="WARNING"),
        ):
            deleted = self.client.delete(
                f"/api/batches/{batch_id}/files/{source_id}",
                headers=headers,
            )

        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["file_count"], 0)
        with self.app.state.database.session() as session:
            self.assertIsNone(session.get(BatchFile, source_id))
            self.assertEqual(session.get(Batch, batch_id).status, "draft")
        self.assertTrue(storage_path.is_file())

    def test_delivery_file_can_be_deleted_before_compute(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "文件纠错测试"},
        ).json()["id"]
        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={
                "file": ("260717-狂飙-A交货单.xlsx", BytesIO(self.delivery_bytes()))
            },
        ).json()
        second = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={
                "file": ("260717-狂飙-B交货单.xlsx", BytesIO(self.delivery_bytes()))
            },
        ).json()
        with self.app.state.database.session() as session:
            removed_path = Path(session.get(BatchFile, second["id"]).storage_path)
        self.assertTrue(removed_path.is_file())

        deleted = self.client.request(
            "DELETE",
            f"/api/batches/{batch_id}/files/{second['id']}",
            headers=admin_headers,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["status"], "draft")
        self.assertEqual(
            [(item["id"], item["file_order"]) for item in deleted.json()["files"]],
            [(first["id"], 1)],
        )
        self.assertFalse(removed_path.exists())

        self.client.post(f"/api/batches/{batch_id}/preflight", headers=admin_headers)
        self.client.post(f"/api/batches/{batch_id}/compute", headers=admin_headers)
        blocked = self.client.request(
            "DELETE",
            f"/api/batches/{batch_id}/files/{first['id']}",
            headers=admin_headers,
        )
        self.assertEqual(blocked.status_code, 409)
