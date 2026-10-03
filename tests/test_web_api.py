from tests.support.web_api import INPUT_KINDS, WebApiCase
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

import delivery_note.web.batch_preflight as batch_preflight_module
import delivery_note.web.input_version_routes as input_version_routes_module
from tests.asgi_client import SyncASGIClient

import delivery_note.web.api as web_api_module
import delivery_note.web.caches as cache_module
from delivery_note.web.api import create_app
from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    SplitRecord,
)



class WebApiTests(WebApiCase):



    def test_exception_contract_uses_stable_codes_and_workflow_actions(self):
        exception = ExceptionRecord(
            batch_file_id=1,
            sku="SKU-A",
            original_site="US",
            full_site="AMAZON:SEEKWAY:US",
            destination="",
            delivery_quantity=10,
            allocated_quantity=0,
            manual_quantity=10,
            reason="产品信息站点不唯一",
            status="pending",
        )
        ambiguous = web_api_module._exception_json(
            exception,
            [],
            self_operated=True,
        )
        self.assertEqual(ambiguous["reason_code"], "ambiguous_product_site")
        self.assertEqual(ambiguous["allowed_actions"], ["resolve_site"])

        exception.reason_code = "ambiguous_product_site"
        exception.reason = "更新后的展示文案"
        renamed = web_api_module._exception_json(
            exception,
            [],
            self_operated=True,
        )
        self.assertEqual(renamed["reason_code"], "ambiguous_product_site")
        self.assertEqual(renamed["allowed_actions"], ["resolve_site"])

        exception.reason_code = None
        exception.reason = "历史批次的未知原因"
        unknown = web_api_module._exception_json(
            exception,
            [],
            self_operated=True,
        )
        self.assertEqual(unknown["reason_code"], "unknown")
        self.assertEqual(unknown["allowed_actions"], [])


















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















































    def test_preflight_rejects_file_order_changed_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        batch_id = self.client.post(
            "/api/batches", headers=headers, json={"name": "预检并发测试"}
        ).json()["id"]
        file_ids = []
        for name in (
            "260717-狂飙-A交货单.xlsx",
            "260717-狂飙-B交货单.xlsx",
        ):
            response = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=headers,
                files={"file": (name, BytesIO(self.delivery_bytes()))},
            )
            self.assertEqual(response.status_code, 201, response.text)
            file_ids.append(response.json()["id"])

        original_reader = batch_preflight_module.read_delivery_workbook
        reordered = False

        def read_and_reorder(path):
            nonlocal reordered
            if not reordered:
                reordered = True
                response = self.client.put(
                    f"/api/batches/{batch_id}/files/order",
                    headers=headers,
                    json={"file_ids": list(reversed(file_ids))},
                )
                self.assertEqual(response.status_code, 200, response.text)
            return original_reader(path)

        with patch.object(
            batch_preflight_module, "read_delivery_workbook",
            side_effect=read_and_reorder,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=headers)
            .json()["status"],
            "draft",
        )
        compute = self.client.post(
            f"/api/batches/{batch_id}/compute", headers=headers
        )
        self.assertEqual(compute.status_code, 409, compute.text)

    def test_preflight_rejects_file_removed_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        batch_id = self.client.post(
            "/api/batches", headers=headers, json={"name": "预检删除测试"}
        ).json()["id"]
        uploaded = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={
                "file": (
                    "260717-狂飙-A交货单.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        ).json()
        original_reader = batch_preflight_module.read_delivery_workbook

        def read_and_remove(path):
            removed = self.client.delete(
                f"/api/batches/{batch_id}/files/{uploaded['id']}",
                headers=headers,
            )
            self.assertEqual(removed.status_code, 200, removed.text)
            return original_reader(path)

        with patch.object(
            batch_preflight_module, "read_delivery_workbook",
            side_effect=read_and_remove,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=headers)
            .json()["status"],
            "draft",
        )

    def test_preflight_rejects_inbound_replacement_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "自营仓预检并发测试"},
            files={
                "delivery_file": (
                    "260817-狂飙-质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        original_reader = batch_preflight_module.read_self_operated_delivery_workbook

        def read_and_replace(path):
            result = original_reader(path)
            replaced = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=headers,
                files={
                    "file": (
                        "更新后的收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    )
                },
            )
            self.assertEqual(replaced.status_code, 200, replaced.text)
            return result

        with patch.object(
            batch_preflight_module,
            "read_self_operated_delivery_workbook",
            side_effect=read_and_replace,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        batch = self.client.get(f"/api/batches/{batch_id}", headers=headers).json()
        self.assertEqual(batch["status"], "draft")
        self.assertEqual(
            batch["inbound_file"]["original_name"], "更新后的收货入库单.xlsx"
        )



    def test_versions_batch_order_preflight_and_compute_job(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        version_ids = self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")

        created = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "7 月交货批次"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(batch["version_ids"], version_ids)
        self.assertEqual(
            {kind: item["name"] for kind, item in batch["versions"].items()},
            {kind: f"{kind}-v1" for kind in INPUT_KINDS},
        )
        self.assertEqual(batch["jobs"], {})
        batch_id = batch["id"]

        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={
                "file": (
                    "260717-狂飙-A交货单-发货10箱.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        duplicate = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={
                "file": (
                    "260717-狂飙-A交货单-发货10箱.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        second = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={
                "file": (
                    "260717-狂飙-B交货单-发货20箱.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(second.status_code, 201, second.text)

        reordered = self.client.put(
            f"/api/batches/{batch_id}/files/order",
            headers=operator_headers,
            json={"file_ids": [second.json()["id"], first.json()["id"]]},
        )
        self.assertEqual(reordered.status_code, 200, reordered.text)
        self.assertEqual(
            [item["id"] for item in reordered.json()["files"]],
            [second.json()["id"], first.json()["id"]],
        )

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=operator_headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")

        first_start = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=operator_headers,
        )
        second_start = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=operator_headers,
        )
        self.assertEqual(first_start.status_code, 202, first_start.text)
        self.assertEqual(second_start.status_code, 202, second_start.text)
        self.assertEqual(first_start.json()["id"], second_start.json()["id"])
        self.assertEqual(first_start.json()["status"], "queued")
        job = self.client.get(
            f"/api/jobs/{first_start.json()['id']}",
            headers=operator_headers,
        )
        self.assertEqual(job.status_code, 200, job.text)
        self.assertEqual(job.json()["kind"], "compute")
        refreshed = self.client.get(
            f"/api/batches/{batch_id}", headers=operator_headers
        ).json()
        self.assertEqual(refreshed["jobs"]["compute"]["id"], job.json()["id"])
        self.assertEqual(refreshed["jobs"]["compute"]["status"], "queued")

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





    def test_preflight_rejects_invalid_excel_content(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "无效预检"},
        )
        batch_id = created.json()["id"]
        uploaded = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={"file": ("260717-狂飙-A交货单-发货10箱.xlsx", BytesIO(b"invalid"))},
        )
        self.assertEqual(uploaded.status_code, 201)

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=admin_headers,
        )
        self.assertEqual(preflight.status_code, 400)
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=admin_headers
        ).json()
        self.assertEqual(batch["status"], "draft")

    def test_split_review_is_quantity_safe_and_invalidates_export(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")
        batch_id = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "拆分测试"},
        ).json()["id"]

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "succeeded"
            source = BatchFile(
                batch_id=batch_id,
                original_name="260717-狂飙-A交货单-发货10箱.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
                supplier_name="KuangBiao",
                supplier_code="GYS-023",
                delivery_total=40,
                import_total=0,
                manual_total=40,
                document_note="260717-狂飙-01-10箱",
                import_rows=[],
            )
            session.add(source)
            session.flush()
            exception = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-A",
                original_site="US",
                full_site="AMAZON:SEEKWAY:US",
                destination="水鞋-广州仓",
                delivery_quantity=40,
                allocated_quantity=0,
                manual_quantity=40,
                reason="超出采购未交量",
                status="pending",
            )
            session.add(exception)
            session.commit()
            exception_id = exception.id

        invalid = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={"parts": [{"quantity": 39, "resolved": False}]},
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={
                "parts": [
                    {"quantity": 25, "destination": "仓A", "resolved": True},
                    {"quantity": 15, "destination": "仓B", "resolved": False},
                ]
            },
        )
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["status"], "partial")
        self.assertEqual(valid.json()["reason_code"], "purchase_balance_exceeded")
        self.assertEqual(valid.json()["allowed_actions"], ["split"])
        self.assertEqual(
            [part["quantity"] for part in valid.json()["parts"]],
            [25, 15],
        )
        batch_after_split = self.client.get(
            f"/api/batches/{batch_id}", headers=operator_headers
        ).json()
        summary = batch_after_split["summary"]
        self.assertEqual(
            (
                summary["delivery_total"],
                summary["import_total"],
                summary["manual_total"],
            ),
            (40, 25, 15),
        )
        self.assertEqual(
            (
                batch_after_split["files"][0]["import_total"],
                batch_after_split["files"][0]["manual_total"],
            ),
            (25, 15),
        )

        export = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=operator_headers,
        )
        repeated = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=operator_headers,
        )
        self.assertEqual(export.status_code, 202, export.text)
        self.assertEqual(export.json()["id"], repeated.json()["id"])
        blocked_split = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={"parts": [{"quantity": 40, "resolved": False}]},
        )
        self.assertEqual(blocked_split.status_code, 409)


if __name__ == "__main__":
    unittest.main()
