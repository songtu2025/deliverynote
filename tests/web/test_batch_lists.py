from tests.support.web_api import WebApiCase

from sqlalchemy import event
from sqlalchemy.orm import Session


from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    SplitRecord,
)


class WebApiTests(WebApiCase):
    def test_unpaged_lists_reject_more_than_200_items_without_truncation(self):
        headers = self.login("admin", "admin-pass")
        version_ids = self.upload_active_versions(headers)
        with self.app.state.database.session() as session:
            session.add_all(
                Batch(
                    name=f"批次 {index}",
                    created_by=1,
                    **{
                        f"{kind}_version_id": version_id
                        for kind, version_id in version_ids.items()
                    },
                )
                for index in range(201)
            )
            session.commit()

        unpaged = self.client.get("/api/batches", headers=headers)
        self.assertEqual(unpaged.status_code, 422)
        self.assertIn("分页", unpaged.json()["detail"])
        paged = self.client.get("/api/batches?limit=200", headers=headers)
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(paged.json()["total"], 201)
        self.assertEqual(len(paged.json()["items"]), 200)

        with self.app.state.database.session() as session:
            batch = session.query(Batch).first()
            source = BatchFile(
                batch_id=batch.id,
                original_name="测试.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
            )
            session.add(source)
            session.flush()
            session.add_all(
                ExceptionRecord(
                    batch_file_id=source.id,
                    sku=f"SKU-{index}",
                    delivery_quantity=1,
                    allocated_quantity=0,
                    manual_quantity=1,
                    reason="未找到可交货采购需求",
                )
                for index in range(601)
            )
            session.commit()

        unpaged = self.client.get(
            f"/api/batches/{batch.id}/exceptions", headers=headers
        )
        self.assertEqual(unpaged.status_code, 422)
        self.assertIn("分页", unpaged.json()["detail"])
        paged = self.client.get(
            f"/api/batches/{batch.id}/exceptions?limit=200", headers=headers
        )
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(paged.json()["total"], 601)
        self.assertEqual(len(paged.json()["items"]), 200)

        searched = self.client.get(
            f"/api/batches/{batch.id}/exceptions?search=SKU", headers=headers
        )
        self.assertEqual(searched.status_code, 422)
        stream_sizes = []

        def record_stream(execute_state):
            if size := execute_state.execution_options.get("yield_per"):
                stream_sizes.append(size)

        event.listen(Session, "do_orm_execute", record_stream)
        try:
            searched_page = self.client.get(
                f"/api/batches/{batch.id}/exceptions?search=SKU&limit=200",
                headers=headers,
            )
        finally:
            event.remove(Session, "do_orm_execute", record_stream)
        self.assertEqual(searched_page.status_code, 200)
        self.assertEqual(searched_page.json()["total"], 601)
        self.assertEqual(stream_sizes, [200])
        last_page = self.client.get(
            f"/api/batches/{batch.id}/exceptions?search=SKU&offset=600&limit=10",
            headers=headers,
        )
        self.assertEqual(last_page.json()["total"], 601)
        self.assertEqual(
            [item["sku"] for item in last_page.json()["items"]],
            ["SKU-600"],
        )

    def test_batch_list_query_count_is_constant_as_batches_grow(self):
        admin_headers = self.login("admin", "admin-pass")
        version_ids = self.upload_active_versions(admin_headers)

        def add_batch(index: int) -> None:
            with self.app.state.database.session() as session:
                batch = Batch(
                    name=f"批次 {index}",
                    status="succeeded",
                    created_by=1,
                    purchase_version_id=version_ids["purchase"],
                    product_version_id=version_ids["product"],
                    supplier_version_id=version_ids["supplier"],
                    position_version_id=version_ids["position"],
                    template_version_id=version_ids["template"],
                )
                session.add(batch)
                session.flush()
                source = BatchFile(
                    batch_id=batch.id,
                    original_name=f"批次 {index}.xlsx",
                    storage_path=f"unused-{index}.xlsx",
                    file_order=1,
                    delivery_total=5,
                    import_total=2,
                    manual_total=3,
                    import_rows=[],
                )
                session.add(source)
                session.flush()
                exception = ExceptionRecord(
                    batch_file_id=source.id,
                    sku="SKU-A",
                    delivery_quantity=3,
                    allocated_quantity=0,
                    manual_quantity=3,
                    reason="数量超出采购余额",
                    status="resolved",
                )
                session.add(exception)
                session.flush()
                session.add_all(
                    [
                        SplitRecord(
                            exception_id=exception.id,
                            quantity=2,
                            destination="水鞋-广州仓",
                            site="AMAZON:SEEKWAY:US",
                            supplier_code="GYS-023",
                            sku="SKU-A",
                            resolved=True,
                        ),
                        SplitRecord(
                            exception_id=exception.id,
                            quantity=1,
                            sku="SKU-A",
                            resolved=False,
                        ),
                    ]
                )
                session.commit()

        add_batch(1)
        single, single_queries = self.get_with_query_count(
            "/api/batches",
            admin_headers,
        )
        for index in range(2, 11):
            add_batch(index)
        multiple, multiple_queries = self.get_with_query_count(
            "/api/batches",
            admin_headers,
        )

        self.assertEqual(single.status_code, 200, single.text)
        self.assertEqual(multiple.status_code, 200, multiple.text)
        self.assertEqual(single_queries, multiple_queries)
        self.assertLessEqual(multiple_queries, 8)
        self.assertEqual(
            [batch["name"] for batch in multiple.json()],
            [f"批次 {index}" for index in range(10, 0, -1)],
        )
        for batch in multiple.json():
            self.assertEqual(
                batch["summary"],
                {
                    "delivery_total": 5,
                    "import_total": 4,
                    "manual_total": 1,
                    "conserved": True,
                },
            )

        page, page_queries = self.get_with_query_count(
            "/api/batches?workflow=delivery&offset=2&limit=3",
            admin_headers,
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 10)
        self.assertEqual(page.json()["empty_draft_count"], 0)
        self.assertEqual(
            [batch["name"] for batch in page.json()["items"]],
            ["批次 8", "批次 7", "批次 6"],
        )
        self.assertTrue(
            all(batch["summary"]["conserved"] for batch in page.json()["items"])
        )
        self.assertLessEqual(page_queries, 9)

        searched = self.client.get(
            "/api/batches?workflow=delivery&search=批次 1&limit=3",
            headers=admin_headers,
        )
        self.assertEqual(searched.json()["total"], 2)
        self.assertEqual(
            [batch["name"] for batch in searched.json()["items"]],
            ["批次 10", "批次 1"],
        )
        invalid = self.client.get("/api/batches?limit=201", headers=admin_headers)
        self.assertEqual(invalid.status_code, 422)
