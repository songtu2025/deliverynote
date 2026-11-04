from delivery_note.processing.models import IMPORT_COLUMNS
from delivery_note.web.models import Batch, BatchFile, SelfOperatedBatch
from tests.support.web_api import WebApiCase


class ImportRowsTests(WebApiCase):
    def setUp(self):
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.upload_active_versions(self.headers)
        response = self.client.post(
            "/api/batches", headers=self.headers, json={"name": "合成读取批次"}
        )
        self.batch_id = response.json()["id"]
        self.path = f"/api/batches/{self.batch_id}/import-rows"
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "succeeded"
            for order in (2, 1):
                session.add(
                    BatchFile(
                        batch_id=self.batch_id,
                        original_name=f"File-{order}.xlsx",
                        storage_path="unused",
                        file_order=order,
                        import_rows=[
                            dict(
                                zip(
                                    IMPORT_COLUMNS,
                                    [
                                        "Warehouse-A",
                                        "Supplier",
                                        f"SKU-{order}-{index}",
                                        index + 1,
                                        "Store:US",
                                        "单据",
                                        "交货",
                                    ],
                                )
                            )
                            for index in range(2)
                        ],
                    )
                )
            session.commit()

    def test_pages_keep_file_and_row_order(self):
        response = self.client.get(
            self.path, headers=self.headers, params={"offset": 1, "limit": 2}
        )
        self.assertEqual(response.status_code, 200, response.text)
        page = response.json()
        self.assertEqual(page["total"], 4)
        self.assertEqual([row["sku"] for row in page["items"]], ["SKU-1-1", "SKU-2-0"])
        first = page["items"][0]
        self.assertEqual(first["file_name"], "File-1.xlsx")
        self.assertEqual(first["row_index"], 1)
        self.assertEqual(first["quantity"], 2)
        self.assertEqual(first["supplier_code"], "Supplier")
        self.assertEqual(first["document_note"], "单据")
        self.assertEqual(first["delivery_note"], "交货")
        self.assertEqual(first["warehouse"], "Warehouse-A")
        self.assertEqual(first["site"], "Store:US")
        self.assertIsInstance(first["file_id"], int)
        self.assertEqual(
            self.client.get(
                self.path, headers=self.headers, params={"offset": 4}
            ).json(),
            {"items": [], "total": 4, "kind": "delivery"},
        )

    def test_search_matches_only_supported_fields_before_paging(self):
        for search, count in (
            (" sku-1 ", 2),
            ("store:us", 4),
            ("WAREHOUSE", 4),
            ("fILE-2", 2),
            ("单据", 0),
            ("missing", 0),
        ):
            with self.subTest(search=search):
                response = self.client.get(
                    self.path,
                    headers=self.headers,
                    params={"search": search, "limit": 1, "offset": 1},
                )
                self.assertEqual(response.json()["total"], count)
                self.assertEqual(len(response.json()["items"]), int(count > 1))

    def test_uncomputed_delivery_return_empty(self):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "draft"
            session.commit()
        self.assertEqual(
            self.client.get(self.path, headers=self.headers).json(),
            {"items": [], "total": 0, "kind": "delivery"},
        )

    def test_inbound_saved_rows_pagination_search_and_uncomputed(self):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            session.add(
                SelfOperatedBatch(
                    batch_id=batch.id, template_version_id=batch.template_version_id
                )
            )
            for source in session.query(BatchFile).filter_by(batch_id=self.batch_id):
                source.import_rows = [
                    {
                        "入库单号": f"WV-{index}",
                        "关联采购单": "PO-A",
                        "关联交货单/调拨单": "LN-A",
                        "入库仓": "合成仓",
                        "SKU": f"SKU-{index}",
                        "平台站点": "Store:US",
                        "本次入库": index + 1,
                        "超收原因": None,
                    }
                    for index in range(2)
                ]
            session.commit()
        page = self.client.get(
            self.path, headers=self.headers, params={"offset": 1, "limit": 2}
        ).json()
        self.assertEqual(page["kind"], "inbound")
        self.assertEqual(page["total"], 4)
        self.assertEqual([row["row_index"] for row in page["items"]], [1, 0])
        self.assertEqual(
            page["items"][0],
            {
                "inbound_no": "WV-1",
                "po_code": "PO-A",
                "delivery_no": "LN-A",
                "warehouse": "合成仓",
                "sku": "SKU-1",
                "site": "Store:US",
                "quantity": 2,
                "overreceipt_reason": None,
                "file_id": page["items"][0]["file_id"],
                "file_name": "File-1.xlsx",
                "row_index": 1,
            },
        )
        for search, count in (
            (" wv-1 ", 2),
            ("po-a", 4),
            ("合成仓", 4),
            ("store:us", 4),
            ("file-2", 2),
            ("sku-1", 2),
            ("LN-A", 0),
        ):
            with self.subTest(search=search):
                result = self.client.get(
                    self.path,
                    headers=self.headers,
                    params={"search": search, "offset": 1, "limit": 1},
                ).json()
                self.assertEqual(result["total"], count)
                self.assertEqual(len(result["items"]), int(count > 1))
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "draft"
            session.commit()
        self.assertEqual(
            self.client.get(self.path, headers=self.headers).json(),
            {"items": [], "total": 0, "kind": "inbound"},
        )

    def test_empty_saved_rows_return_empty(self):
        with self.app.state.database.session() as session:
            for source in session.query(BatchFile).filter_by(batch_id=self.batch_id):
                source.import_rows = []
            session.commit()
        self.assertEqual(
            self.client.get(self.path, headers=self.headers).json(),
            {"items": [], "total": 0, "kind": "delivery"},
        )

    def test_authentication_missing_batch_and_pagination_validation(self):
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(
            self.client.get(
                "/api/batches/999999/import-rows", headers=self.headers
            ).status_code,
            404,
        )
        for params in ({"offset": -1}, {"limit": 0}, {"limit": 201}):
            self.assertEqual(
                self.client.get(
                    self.path, headers=self.headers, params=params
                ).status_code,
                422,
            )

    def test_openapi_exposes_read_only_paginated_route(self):
        schema = self.app.openapi()["paths"]["/api/batches/{batch_id}/import-rows"]
        self.assertEqual(set(schema), {"get"})
        self.assertEqual(
            {item["name"] for item in schema["get"]["parameters"]},
            {"batch_id", "offset", "limit", "search"},
        )
