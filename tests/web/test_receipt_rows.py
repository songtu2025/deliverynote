from typing import Any

from sqlalchemy import select

from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    SelfOperatedBatch,
)
from delivery_note.web.receipt_state import receipt_signature
from tests.support.exception_transfers import ExceptionTransferCase
from tests.support.web_api import WebApiCase


class ReceiptRowsTests(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.upload_active_versions(self.headers)
        response = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "合成核对排序"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.batch_id = response.json()["id"]
        with self.app.state.database.session() as session:
            for file_order in (2, 1):
                rows = [
                    {
                        "sku": f"{file_order}-{status}-{index}",
                        "issue": "站点待核对" if status == "issue" else "",
                        "notice": "未匹配，进入待处理"
                        if index == 1 or status == "notice"
                        else "",
                    }
                    for index in (1, 2)
                    for status in ("checked", "notice", "issue")
                ]
                for row in rows:
                    if "checked" in row["sku"]:
                        del row["notice"]
                session.add(
                    BatchFile(
                        batch_id=self.batch_id,
                        original_name=f"合成来源-{file_order}.xlsx",
                        storage_path="synthetic",
                        file_order=file_order,
                        supplier_name="合成供应商",
                        receipt_context={
                            "delivery_numbers": [f"LN-{file_order}"],
                            "rows": rows,
                        },
                    )
                )
            session.commit()
        self.expected_skus = [
            f"{file_order}-{status}-{index}"
            for status in ("issue", "notice", "checked")
            for file_order in (1, 2)
            for index in (1, 2)
        ]

    def receipt_rows(self, **params: Any) -> dict[str, Any]:
        response = self.client.get(
            f"/api/batches/{self.batch_id}/receipts",
            headers=self.headers,
            params=params,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_status_sort_preserves_file_and_row_order(self) -> None:
        data = self.receipt_rows()
        self.assertEqual(data["total"], 12)
        self.assertEqual([row["sku"] for row in data["items"]], self.expected_skus)
        first = data["items"][0]
        self.assertEqual(first["filename"], "合成来源-1.xlsx")
        self.assertEqual(first["supplier"], "合成供应商")
        self.assertEqual(first["delivery_numbers"], ["LN-1"])
        self.assertIsInstance(first["file_id"], int)

    def test_pagination_slices_after_sorting(self) -> None:
        for page in range(1, 5):
            with self.subTest(page=page):
                data = self.receipt_rows(page=page, page_size=3)
                offset = (page - 1) * 3
                self.assertEqual(data["total"], 12)
                self.assertEqual(
                    [row["sku"] for row in data["items"]],
                    self.expected_skus[offset : offset + 3],
                )

    def test_issues_only_excludes_notices_and_keeps_pagination(self) -> None:
        data = self.receipt_rows(issues_only="true")
        self.assertEqual(data["total"], 4)
        self.assertEqual([row["sku"] for row in data["items"]], self.expected_skus[:4])
        page = self.receipt_rows(issues_only="true", page=2, page_size=3)
        self.assertEqual(page["total"], 4)
        self.assertEqual(page["items"], data["items"][3:])


class ReceiptSiteRouteTests(ExceptionTransferCase):
    def setUp(self):
        super().setUp()
        with self.app.state.database.session() as session:
            record = session.get(ExceptionRecord, self.exception_id)
            self.file_id = record.batch_file_id
            source = session.get(BatchFile, self.file_id)
            source.receipt_context = {
                "delivery_numbers": ["LN-SYNTHETIC"],
                "rows": [
                    {
                        "sku": "SKU-A",
                        "original_site": "US",
                        "candidates": ["AMAZON:SEEKWAY:US"],
                    }
                ],
            }
            profile = session.get(SelfOperatedBatch, self.batch_id)
            batch = session.get(Batch, self.batch_id)
            self.snapshot = {
                "path": "frozen.json",
                "signature": receipt_signature(batch, profile, [source]),
                "captured_at": "2026-11-04",
            }
            profile.receipt_snapshot = {**self.snapshot, "summary": {"issue_count": 0}}
            self.handling = {
                "allowances": [{"quantity": 3}],
                "offline": [{"quantity": 2}],
            }
            profile.manual_handling = self.handling
            session.commit()
        self.endpoint = (
            f"/api/batches/{self.batch_id}/files/{self.file_id}/receipt-site"
        )
        self.choice = {
            "sku": "SKU-A",
            "original_site": "US",
            "full_site": "AMAZON:SEEKWAY:US",
        }

    def test_computed_site_choice_preserves_snapshot_and_manual_inputs(self):
        response = self.client.put(
            self.endpoint, headers=self.headers, json=self.choice
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "queued")
        with self.app.state.database.session() as session:
            profile = session.get(SelfOperatedBatch, self.batch_id)
            source = session.get(BatchFile, self.file_id)
            batch = session.get(Batch, self.batch_id)
            self.assertEqual(profile.receipt_snapshot, self.snapshot)
            self.assertEqual(profile.manual_handling, self.handling)
            self.assertEqual(
                receipt_signature(batch, profile, [source]), self.snapshot["signature"]
            )
            self.assertEqual(source.receipt_sites, {"SKU-A\tUS": "AMAZON:SEEKWAY:US"})
            self.assertIsNone(source.receipt_context)
            job = session.scalar(
                select(Job).where(Job.batch_id == self.batch_id, Job.kind == "prepare")
            )
            self.assertEqual(job.status, "queued")

    def test_site_choice_rejects_transfer_links_without_changing_input(self):
        self.assertEqual(self.transfer(1).status_code, 201)
        response = self.client.put(
            self.endpoint, headers=self.headers, json=self.choice
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("转交", response.json()["detail"])
        with self.app.state.database.session() as session:
            self.assertFalse(session.get(BatchFile, self.file_id).receipt_sites)

    def test_site_choice_keeps_precompute_states_supported(self):
        for status in ("draft", "preflight_ready", "failed"):
            with self.subTest(status=status):
                with self.app.state.database.session() as session:
                    for job in session.scalars(
                        select(Job).where(Job.batch_id == self.batch_id)
                    ):
                        session.delete(job)
                    session.get(Batch, self.batch_id).status = status
                    session.get(BatchFile, self.file_id).receipt_context = {
                        "rows": [
                            {**self.choice, "candidates": [self.choice["full_site"]]}
                        ]
                    }
                    session.commit()
                response = self.client.put(
                    self.endpoint, headers=self.headers, json=self.choice
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "queued")

    def test_site_choice_rejects_active_jobs_and_keeps_previous_result(self):
        for status in ("queued", "running"):
            with self.subTest(status=status):
                with self.app.state.database.session() as session:
                    job = session.scalar(
                        select(Job).where(Job.batch_id == self.batch_id)
                    )
                    if job is None:
                        job = Job(batch_id=self.batch_id, kind="export", status=status)
                        session.add(job)
                    job.status = status
                    session.commit()
                response = self.client.put(
                    self.endpoint, headers=self.headers, json=self.choice
                )
                self.assertEqual(response.status_code, 409, response.text)
                with self.app.state.database.session() as session:
                    source = session.get(BatchFile, self.file_id)
                    self.assertFalse(source.receipt_sites)
                    self.assertIsNotNone(source.receipt_context)
                    self.assertEqual(
                        session.get(Batch, self.batch_id).status, "succeeded"
                    )
