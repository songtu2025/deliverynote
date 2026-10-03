from tests.support.web_api import WebApiCase
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from unittest.mock import patch

from sqlalchemy import select

import delivery_note.web.batch_file_uploads as batch_file_uploads_module

from delivery_note.web.models import (
    BatchFile,
)


class WebApiTests(WebApiCase):
    def test_concurrent_batch_uploads_get_distinct_contiguous_orders(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "并发上传排序测试"},
        ).json()["id"]
        saved_uploads = Barrier(2)
        original_save_upload = batch_file_uploads_module._save_upload

        async def synchronized_save_upload(*args, **kwargs):
            await original_save_upload(*args, **kwargs)
            saved_uploads.wait(timeout=5)

        def upload(filename: str):
            return self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=admin_headers,
                files={"file": (filename, BytesIO(self.delivery_bytes()))},
            )

        filenames = ("KuangBiao-A.xlsx", "KuangBiao-B.xlsx")
        with (
            patch.object(
                batch_file_uploads_module,
                "_save_upload",
                new=synchronized_save_upload,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            responses = list(executor.map(upload, filenames))

        self.assertEqual(
            [response.status_code for response in responses],
            [201, 201],
            [response.text for response in responses],
        )
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=admin_headers
        ).json()
        self.assertEqual(
            [item["file_order"] for item in batch["files"]],
            [1, 2],
        )
        self.assertEqual(
            {item["original_name"] for item in batch["files"]},
            set(filenames),
        )

    def test_batch_file_limit_rejects_append_before_writing(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "普通追加数量上限"},
        ).json()["id"]
        self.app.state.max_batch_upload_files = 1
        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={"file": ("first.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(first.status_code, 201, first.text)
        input_root = self.app.state.storage_root / "batches" / str(batch_id) / "inputs"
        files_before = set(input_root.iterdir())

        with patch.object(
            batch_file_uploads_module,
            "_save_upload",
            wraps=batch_file_uploads_module._save_upload,
        ) as save_upload:
            rejected = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=admin_headers,
                files={"file": ("second.xlsx", BytesIO(self.delivery_bytes()))},
            )

        self.assertEqual(rejected.status_code, 413, rejected.text)
        self.assertIn("最多上传 1 份", rejected.json()["detail"])
        save_upload.assert_not_awaited()
        self.assertEqual(set(input_root.iterdir()), files_before)
        with self.app.state.database.session() as session:
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            ).all()
        self.assertEqual([source.original_name for source in sources], ["first.xlsx"])

    def test_concurrent_batch_appends_enforce_file_limit_after_writing(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "并发追加数量上限"},
        ).json()["id"]
        self.app.state.max_batch_upload_files = 1
        saved_uploads = Barrier(2)
        original_save_upload = batch_file_uploads_module._save_upload

        async def synchronized_save_upload(*args, **kwargs):
            await original_save_upload(*args, **kwargs)
            saved_uploads.wait(timeout=5)

        def upload(filename: str):
            return self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=admin_headers,
                files={"file": (filename, BytesIO(self.delivery_bytes()))},
            )

        with (
            patch.object(
                batch_file_uploads_module,
                "_save_upload",
                new=synchronized_save_upload,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            responses = list(executor.map(upload, ("first.xlsx", "second.xlsx")))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [201, 413],
            [response.text for response in responses],
        )
        rejected = next(
            response for response in responses if response.status_code == 413
        )
        self.assertIn("最多上传 1 份", rejected.json()["detail"])
        input_root = self.app.state.storage_root / "batches" / str(batch_id) / "inputs"
        self.assertEqual(len(list(input_root.iterdir())), 1)
        with self.app.state.database.session() as session:
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            ).all()
        self.assertEqual(len(sources), 1)
