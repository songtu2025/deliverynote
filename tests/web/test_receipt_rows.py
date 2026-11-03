from typing import Any

from delivery_note.web.models import BatchFile
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
