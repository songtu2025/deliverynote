from tests.support.web_api import WebApiCase
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from unittest.mock import patch

from openpyxl import Workbook

import delivery_note.input_inspection as input_inspection_module

import delivery_note.web.caches as cache_module


class WebApiTests(WebApiCase):
    def test_input_version_inspection_reuses_summary_across_pages(self):
        admin_headers = self.login("admin", "admin-pass")
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["SKU", "店铺/站点", "品类A", "锁仓MKSU"])
        for index in range(30):
            sheet.append([f"SKU-{index}", "SEEKWAY:US", "水鞋", "锁"])
        payload = BytesIO()
        workbook.save(payload)
        uploaded = self.client.post(
            "/api/input-versions/product",
            headers=admin_headers,
            data={"name": "product-cache", "activate": "true"},
            files={
                "file": (
                    "product-cache.xlsx",
                    BytesIO(payload.getvalue()),
                )
            },
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        version_id = uploaded.json()["id"]

        with (
            patch.object(
                input_inspection_module,
                "_stream_xlsx_inspection",
                wraps=input_inspection_module._stream_xlsx_inspection,
            ) as inspect_full,
            patch.object(
                input_inspection_module,
                "_stream_xlsx_preview",
                wraps=input_inspection_module._stream_xlsx_preview,
            ) as inspect_page,
        ):
            summary = self.client.get(
                f"/api/input-versions/{version_id}/summary",
                headers=admin_headers,
            )
            inspection = self.client.get(
                f"/api/input-versions/{version_id}/inspection",
                headers=admin_headers,
            )
            preview = self.client.get(
                f"/api/input-versions/{version_id}/preview",
                headers=admin_headers,
            )
            next_page = self.client.get(
                (f"/api/input-versions/{version_id}/inspection?offset=20&limit=10"),
                headers=admin_headers,
            )

        for response in (summary, inspection, preview, next_page):
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(inspect_full.call_count, 1)
        self.assertEqual(inspect_page.call_count, 1)
        self.assertEqual(summary.json()["row_count"], 30)
        self.assertEqual(next_page.json()["preview"]["offset"], 20)
        self.assertEqual(next_page.json()["preview"]["limit"], 10)
        self.assertEqual(
            [row["SKU"] for row in next_page.json()["preview"]["rows"]],
            [f"SKU-{index}" for index in range(20, 30)],
        )

    def test_input_inspection_cache_is_bounded_with_bounded_pages(self):
        cache = cache_module.InputInspectionCache(
            max_entries=2,
            max_pages_per_version=2,
        )
        full_loads: list[int] = []

        def result(version_id, offset, limit):
            return {
                "summary": {
                    "kind": "product",
                    "row_count": 100,
                    "columns": ["SKU"],
                    "metrics": {},
                    "issues": [],
                },
                "preview": {
                    "kind": "product",
                    "columns": ["SKU"],
                    "rows": [{"SKU": f"SKU-{version_id}-{offset}"}],
                    "total": 100,
                    "offset": offset,
                    "limit": limit,
                },
            }

        def get_version(version_id):
            return cache.get(
                version_id,
                0,
                10,
                lambda: full_loads.append(version_id) or result(version_id, 0, 10),
                lambda summary: result(version_id, 0, 10)["preview"],
            )

        first = get_version(1)
        get_version(2)
        self.assertEqual(get_version(1), first)
        get_version(3)
        get_version(2)
        self.assertEqual(full_loads, [1, 2, 3, 2])

        page_cache = cache_module.InputInspectionCache(
            max_entries=1,
            max_pages_per_version=2,
        )
        page_loads: list[int] = []
        page_cache.get(
            1,
            0,
            10,
            lambda: result(1, 0, 10),
            lambda summary: result(1, 0, 10)["preview"],
        )
        for offset in (10, 20, 0):
            page_cache.get(
                1,
                offset,
                10,
                lambda: self.fail("页面淘汰不得触发完整检查"),
                lambda summary, current=offset: (
                    page_loads.append(current) or result(1, current, 10)["preview"]
                ),
            )
        self.assertEqual(page_loads, [10, 20, 0])

    def test_input_inspection_cache_single_flight_and_parallel_versions(self):
        cache = cache_module.InputInspectionCache(max_entries=4)
        same_version_loads = 0

        def result(version_id):
            return {
                "summary": {
                    "kind": "product",
                    "row_count": 1,
                    "columns": ["SKU"],
                    "metrics": {},
                    "issues": [],
                },
                "preview": {
                    "kind": "product",
                    "columns": ["SKU"],
                    "rows": [{"SKU": f"SKU-{version_id}"}],
                    "total": 1,
                    "offset": 0,
                    "limit": 20,
                },
            }

        def load_same_version():
            nonlocal same_version_loads
            same_version_loads += 1
            return result(1)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    cache.get,
                    1,
                    0,
                    20,
                    load_same_version,
                    lambda summary: result(1)["preview"],
                )
                for _ in range(2)
            ]
            same_results = [future.result(timeout=5) for future in futures]
        self.assertEqual(same_version_loads, 1)
        self.assertEqual(same_results[0], same_results[1])

        parallel_cache = cache_module.InputInspectionCache(max_entries=4)
        parallel_loads = Barrier(2)

        def load_parallel(version_id):
            parallel_loads.wait(timeout=2)
            return result(version_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    parallel_cache.get,
                    version_id,
                    0,
                    20,
                    lambda current=version_id: load_parallel(current),
                    lambda summary, current=version_id: result(current)["preview"],
                )
                for version_id in (1, 2)
            ]
            parallel_results = [future.result(timeout=5) for future in futures]
        self.assertEqual(
            [item["preview"]["rows"][0]["SKU"] for item in parallel_results],
            ["SKU-1", "SKU-2"],
        )

    def test_input_inspection_cache_retries_after_loader_failure(self):
        cache = cache_module.InputInspectionCache(max_entries=2)
        attempts = 0

        def load():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("broken workbook")
            return {
                "summary": {"row_count": 0},
                "preview": {"offset": 0, "limit": 20},
            }

        with self.assertRaisesRegex(ValueError, "broken workbook"):
            cache.get(1, 0, 20, load, lambda summary: {})
        recovered = cache.get(1, 0, 20, load, lambda summary: {})
        self.assertEqual(attempts, 2)
        self.assertEqual(recovered["summary"]["row_count"], 0)

        # 页面加载失败只重试该页，不应重新检查整个版本。
        def broken_page(_summary):
            raise ValueError("页面读取失败")

        with self.assertRaisesRegex(ValueError, "页面读取失败"):
            cache.get(1, 20, 20, load, broken_page)
        page = cache.get(1, 20, 20, load, lambda summary: {"offset": 20})
        repeated = cache.get(1, 20, 20, load, broken_page)
        self.assertEqual(page["preview"]["offset"], 20)
        self.assertEqual(repeated, page)
        self.assertEqual(attempts, 2)
