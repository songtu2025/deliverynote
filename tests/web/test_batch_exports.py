"""批次下载边界和导出冲突回退的回归测试。"""

from unittest.mock import patch

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from delivery_note.web.models import Batch, BatchFile, Job
from tests.support.web_api import WebApiCase


class BatchExportTests(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.upload_active_versions(self.headers)
        created = self.client.post(
            "/api/batches", headers=self.headers, json={"name": "导出契约测试"}
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.batch_id = created.json()["id"]
        with self.app.state.database.session() as session:
            session.get(Batch, self.batch_id).status = "succeeded"
            session.commit()

    def test_downloads_reject_missing_records_and_files(self) -> None:
        with self.app.state.database.session() as session:
            session.get(Batch, self.batch_id).zip_path = str(self.root / "missing.zip")
            source = BatchFile(
                batch_id=self.batch_id,
                original_name="交货.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
                result_path=str(self.root / "missing.xlsx"),
            )
            session.add(source)
            session.commit()
            file_id = source.id
        paths = (
            f"/api/batches/{self.batch_id}/download",
            f"/api/batches/{self.batch_id}/download-merged",
            f"/api/batch-files/{file_id}/download",
            "/api/batches/999999/download",
            "/api/batches/999999/download-merged",
            "/api/batch-files/999999/download",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get(path, headers=self.headers).status_code, 404
                )

    def test_export_reuses_existing_job_after_commit_conflict(self) -> None:
        with self.app.state.database.session() as session:
            job = Job(batch_id=self.batch_id, kind="export", status="queued")
            session.add(job)
            session.commit()
            job_id = job.id
        conflict = IntegrityError("commit", {}, RuntimeError("并发冲突"))
        with patch.object(Session, "commit", side_effect=conflict):
            response = self.client.post(
                f"/api/batches/{self.batch_id}/export", headers=self.headers
            )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["id"], job_id)
        self.assertEqual(response.json()["status"], "queued")
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.query(Job).filter_by(batch_id=self.batch_id).count(), 1
            )

    def test_export_propagates_conflict_without_existing_job(self) -> None:
        conflict = IntegrityError("commit", {}, RuntimeError("并发冲突"))
        with patch.object(Session, "commit", side_effect=conflict):
            with self.assertRaises(IntegrityError):
                self.client.post(
                    f"/api/batches/{self.batch_id}/export", headers=self.headers
                )
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.query(Job).filter_by(batch_id=self.batch_id).count(), 0
            )
