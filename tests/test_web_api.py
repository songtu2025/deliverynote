from tests.support.web_api import WebApiCase
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Lock
import unittest
from unittest.mock import patch

from httpx2 import ASGITransport, AsyncClient
import pandas as pd
from sqlalchemy import delete, event
from sqlalchemy.orm import Session

import delivery_note.web.input_version_routes as input_version_routes_module
from tests.asgi_client import SyncASGIClient

import delivery_note.web.caches as cache_module
from delivery_note.web.api import create_app
from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    SplitRecord,
)



class WebApiTests(WebApiCase):





















    def test_upload_parsing_runs_off_loop_and_obeys_concurrency_limit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                database_url=f"sqlite+pysqlite:///{root / 'parse-limit.db'}",
                storage_root=root / "storage",
                bootstrap_admin=("admin", "admin-pass"),
                max_concurrent_upload_parses=1,
            )
            client = SyncASGIClient(app)
            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin-pass"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            counter_lock = Lock()
            concurrent_parses = Barrier(2)
            active = 0
            maximum_active = 0
            observed_running_loops = []

            def slow_validation(_kind, _path):
                nonlocal active, maximum_active
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    observed_running_loops.append(False)
                else:
                    observed_running_loops.append(True)
                with counter_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    concurrent_parses.wait(timeout=0.3)
                except BrokenBarrierError:
                    pass
                with counter_lock:
                    active -= 1

            async def upload_versions():
                async def keep_event_loop_awake():
                    while True:
                        await asyncio.sleep(0.01)

                heartbeat = asyncio.create_task(keep_event_loop_awake())
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://testserver",
                ) as async_client:
                    try:
                        return await asyncio.gather(
                            *(
                                async_client.post(
                                    f"/api/input-versions/{kind}",
                                    headers=headers,
                                    data={
                                        "name": f"{kind}-threaded",
                                        "activate": "false",
                                    },
                                    files={
                                        "file": (
                                            f"{kind}.xlsx",
                                            BytesIO(b"content"),
                                        )
                                    },
                                )
                                for kind in ("purchase", "product")
                            )
                        )
                    finally:
                        heartbeat.cancel()
                        with suppress(asyncio.CancelledError):
                            await heartbeat

            try:
                with patch.object(
                    input_version_routes_module,
                    "_validate_input_version",
                    side_effect=slow_validation,
                ):
                    responses = asyncio.run(upload_versions())
            finally:
                client.close()
                app.state.database.dispose()

        self.assertTrue(
            all(response.status_code == 201 for response in responses),
            [response.text for response in responses],
        )
        self.assertEqual(observed_running_loops, [False, False])
        self.assertEqual(maximum_active, 1)





















































    def test_batch_reads_bulk_load_exception_splits(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "批量读取测试"},
        ).json()["id"]

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "succeeded"
            source = BatchFile(
                batch_id=batch_id,
                original_name="批量读取测试.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
                supplier_name="KuangBiao",
                supplier_code="GYS-023",
                delivery_total=10,
                import_total=0,
                manual_total=10,
                import_rows=[],
            )
            session.add(source)
            session.flush()
            for index in range(10):
                exception = ExceptionRecord(
                    batch_file_id=source.id,
                    sku="SKU-A",
                    original_site="US",
                    full_site="AMAZON:SEEKWAY:US",
                    destination="水鞋-广州仓",
                    delivery_quantity=1,
                    allocated_quantity=0,
                    manual_quantity=1,
                    reason=f"批量读取测试 {index}",
                    status="resolved",
                )
                session.add(exception)
                session.flush()
                session.add(
                    SplitRecord(
                        exception_id=exception.id,
                        quantity=1,
                        destination="水鞋-广州仓",
                        site="AMAZON:SEEKWAY:US",
                        supplier_code="GYS-023",
                        sku="SKU-A",
                        resolved=True,
                    )
                )
            session.commit()

        loaded_exceptions = []

        def record_loaded(_session, instance):
            if isinstance(instance, (ExceptionRecord, SplitRecord)):
                loaded_exceptions.append(instance)

        event.listen(Session, "loaded_as_persistent", record_loaded)
        try:
            detail, detail_queries = self.get_with_query_count(
                f"/api/batches/{batch_id}",
                admin_headers,
            )
            listed, list_queries = self.get_with_query_count(
                "/api/batches",
                admin_headers,
            )
        finally:
            event.remove(Session, "loaded_as_persistent", record_loaded)
        self.assertEqual(loaded_exceptions, [])
        original_reader = cache_module.read_position_workbook
        with patch.object(
            cache_module,
            "read_position_workbook",
            wraps=original_reader,
        ) as reader:
            exceptions, exception_queries = self.get_with_query_count(
                f"/api/batches/{batch_id}/exceptions",
                admin_headers,
            )
            repeated_exceptions = self.client.get(
                f"/api/batches/{batch_id}/exceptions",
                headers=admin_headers,
            )

        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(exceptions.status_code, 200, exceptions.text)
        self.assertEqual(
            repeated_exceptions.status_code,
            200,
            repeated_exceptions.text,
        )
        self.assertEqual(detail.json()["summary"]["import_total"], 10)
        listed_batch = next(
            batch for batch in listed.json() if batch["id"] == batch_id
        )
        self.assertEqual(
            listed_batch,
            {key: detail.json()[key] for key in listed_batch},
        )
        self.assertEqual(len(exceptions.json()), 10)
        self.assertEqual(repeated_exceptions.json(), exceptions.json())
        self.assertEqual(reader.call_count, 1)
        self.assertLessEqual(detail_queries, 15)
        self.assertLessEqual(list_queries, 8)
        self.assertLessEqual(exception_queries, 8)

        loaded_page_records = []

        def record_page(_session, instance):
            if isinstance(instance, (ExceptionRecord, SplitRecord)):
                loaded_page_records.append(instance)

        event.listen(Session, "loaded_as_persistent", record_page)
        try:
            page, page_queries = self.get_with_query_count(
                f"/api/batches/{batch_id}/exceptions?offset=2&limit=3",
                admin_headers,
            )
        finally:
            event.remove(Session, "loaded_as_persistent", record_page)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 10)
        self.assertEqual(len(page.json()["items"]), 3)
        self.assertEqual(
            sum(isinstance(record, ExceptionRecord) for record in loaded_page_records),
            3,
        )
        self.assertEqual(
            sum(isinstance(record, SplitRecord) for record in loaded_page_records),
            3,
        )
        self.assertEqual(page.json()["stats"]["resolved_count"], 10)
        self.assertLessEqual(page_queries, 10)

        filtered = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&review_scope=unfinished",
            headers=admin_headers,
        )
        self.assertEqual(filtered.json()["total"], 0)
        self.assertEqual(filtered.json()["stats"]["total_count"], 10)

        reason = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&reason=批量读取测试 4",
            headers=admin_headers,
        )
        self.assertEqual(reason.json()["total"], 1)
        self.assertEqual(reason.json()["items"][0]["reason"], "批量读取测试 4")

        filters = self.client.get(
            f"/api/batches/{batch_id}/exceptions/filters",
            headers=admin_headers,
        )
        self.assertEqual(filters.status_code, 200, filters.text)
        self.assertEqual(len(filters.json()["reasons"]), 10)
        self.assertEqual(filters.json()["sites"], ["AMAZON:SEEKWAY:US"])
        self.assertEqual(filters.json()["scales"], ["短尾"])
        self.assertEqual(filters.json()["stocking"], ["备货"])

        by_position = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&scale_position=短尾",
            headers=admin_headers,
        )
        self.assertEqual(by_position.json()["total"], 10)
        self.assertEqual(len(by_position.json()["items"]), 3)

        by_position_search = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&search=短尾",
            headers=admin_headers,
        )
        self.assertEqual(by_position_search.json()["total"], 10)
        position_page = self.client.get(
            f"/api/batches/{batch_id}/exceptions"
            "?offset=3&limit=3&search=短尾&scale_position=短尾",
            headers=admin_headers,
        )
        self.assertEqual(position_page.json()["total"], 10)
        self.assertEqual(
            [item["reason"] for item in position_page.json()["items"]],
            [f"批量读取测试 {index}" for index in range(3, 6)],
        )

        invalid = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=201",
            headers=admin_headers,
        )
        self.assertEqual(invalid.status_code, 422)

        first_exception_id = exceptions.json()[0]["id"]
        with self.app.state.database.session() as session:
            first_exception = session.get(ExceptionRecord, first_exception_id)
            first_exception.status = "pending"
            session.execute(
                delete(SplitRecord).where(
                    SplitRecord.exception_id == first_exception_id
                )
            )
            session.commit()
        updated = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3",
            headers=admin_headers,
        )
        self.assertEqual(updated.json()["stats"]["unfinished_count"], 1)
        self.assertEqual(updated.json()["stats"]["unfinished_quantity"], 1)
        self.assertEqual(updated.json()["stats"]["resolved_count"], 9)

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
            f"/api/batches/{batch.id}/exceptions"
            "?search=SKU&offset=600&limit=10",
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
        self.assertTrue(all(
            batch["summary"]["conserved"] for batch in page.json()["items"]
        ))
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
        invalid = self.client.get(
            "/api/batches?limit=201", headers=admin_headers
        )
        self.assertEqual(invalid.status_code, 422)

    def test_position_frame_cache_evicts_least_recent_version(self):
        cache = cache_module.PositionFrameCache(max_entries=2)
        loaded_versions = []

        def read_frame(path):
            version_id = int(path.stem)
            loaded_versions.append(version_id)
            return pd.DataFrame({"version_id": [version_id]})

        with patch.object(
            cache_module,
            "read_position_workbook",
            side_effect=read_frame,
        ):
            first_frame = cache.get(1, Path("1.xlsx"))
            cache.get(2, Path("2.xlsx"))
            self.assertIs(cache.get(1, Path("1.xlsx")), first_frame)
            cache.get(3, Path("3.xlsx"))
            cache.get(2, Path("2.xlsx"))

        self.assertEqual(loaded_versions, [1, 2, 3, 2])

    def test_position_frame_cache_serializes_concurrent_misses(self):
        cache = cache_module.PositionFrameCache(max_entries=2)
        concurrent_reads = Barrier(2)

        def read_frame(_path):
            try:
                concurrent_reads.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
            return pd.DataFrame({"version_id": [1]})

        with patch.object(
            cache_module,
            "read_position_workbook",
            side_effect=read_frame,
        ) as reader:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(cache.get, 1, Path("1.xlsx")) for _ in range(2)
                ]
                frames = [future.result(timeout=5) for future in futures]

        self.assertEqual(reader.call_count, 1)
        self.assertIs(frames[0], frames[1])








if __name__ == "__main__":
    unittest.main()
