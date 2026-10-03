from tests.support.web_api import WebApiCase
from io import BytesIO


class WebApiTests(WebApiCase):
    def test_delivery_creation_with_files_is_atomic(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        invalid = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "校验失败的交货批次"},
            files={"files": ("异常交货单.xlsx", BytesIO(b"not-an-excel-file"))},
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(
            self.client.get("/api/batches", headers=headers).json(),
            [],
        )
        temporary_root = self.app.state.storage_root / "temporary" / "delivery-batches"
        self.assertEqual(list(temporary_root.glob("*")), [])

        created = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "带文件创建的交货批次"},
            files={"files": ("交货单.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["file_count"], 1)

    def test_delivery_creation_rejects_too_many_files_before_writing(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        self.app.state.max_batch_upload_files = 1

        response = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "文件过多"},
            files=[
                ("files", ("one.xlsx", BytesIO(self.delivery_bytes()))),
                ("files", ("two.xlsx", BytesIO(self.delivery_bytes()))),
            ],
        )

        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn("最多上传 1 份", response.json()["detail"])
        self.assertEqual(
            self.client.get("/api/batches", headers=headers).json(),
            [],
        )
        temporary_root = self.app.state.storage_root / "temporary" / "delivery-batches"
        self.assertFalse(temporary_root.exists())
