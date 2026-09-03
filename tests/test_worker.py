from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Lock
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
import pandas as pd

from delivery_note.pipeline import IMPORT_COLUMNS
from delivery_note.self_operated_inbound import INBOUND_TEMPLATE_COLUMNS
from tests.asgi_client import SyncASGIClient
from delivery_note.web.api import create_app
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    InputVersion,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)

try:
    from delivery_note.worker import (
        _consolidate_import_rows,
        _fail_job,
        _fetch_purchase_order_details,
        _fetch_incremental_purchase_order_details,
        build_parser,
        recover_stale_jobs,
        run_once,
    )
except ImportError:
    _consolidate_import_rows = None
    _fail_job = None
    recover_stale_jobs = None
    run_once = None


class WorkerExportConsolidationTests(unittest.TestCase):
    def test_purchase_details_use_eight_workers_and_keep_order(self):
        class DetailClient:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = Lock()

            def purchase_order_detail(self, po_code):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.03)
                with self.lock:
                    self.active -= 1
                return {"poCode": po_code}

        client = DetailClient()
        orders = [{"code": f"PO-{index}"} for index in range(8)]
        progress = []

        details = _fetch_purchase_order_details(
            client,
            orders,
            lambda count, po_code: progress.append((count, po_code)),
        )

        self.assertEqual(client.max_active, 8)
        self.assertEqual(
            [detail[1]["poCode"] for detail in details],
            [order["code"] for order in orders],
        )
        self.assertEqual(
            [count for count, _po_code in progress],
            list(range(1, 9)),
        )

    def test_incremental_details_reuse_cache_and_fallback_on_mismatch(self):
        from datetime import timezone

        from delivery_note.purchase_detail_cache import (
            build_purchase_detail_cache,
        )

        orders = [
            {"code": f"PO-{index}", "updateTime": "2026-08-27 08:00:00"}
            for index in range(20)
        ]
        details = [(order, {"poCode": order["code"], "balance": 1}) for order in orders]
        cached = build_purchase_detail_cache("source", details)["orders"]
        last_full = datetime.now(timezone.utc)

        class StableClient:
            def __init__(self):
                self.calls = []

            def purchase_order_detail(self, po_code):
                self.calls.append(po_code)
                return {"poCode": po_code, "balance": 1}

        stable = StableClient()
        fetched, stats, _ = _fetch_incremental_purchase_order_details(
            stable,
            orders,
            cached,
            last_full,
            lambda _count, _code: None,
            last_full,
        )

        self.assertEqual(len(stable.calls), 5)
        self.assertEqual(stats["cache_hit_count"], 15)
        self.assertEqual(stats["sampled_order_count"], 5)
        self.assertFalse(stats["incremental_fallback"])
        self.assertEqual([detail[1]["balance"] for detail in fetched], [1] * 20)

        class MismatchClient:
            def __init__(self):
                self.calls = []
                self.changed = False
                self.lock = Lock()

            def purchase_order_detail(self, po_code):
                with self.lock:
                    self.calls.append(po_code)
                    if not self.changed:
                        self.changed = True
                        return {"poCode": po_code, "balance": 2}
                return {"poCode": po_code, "balance": 1}

        mismatch = MismatchClient()
        fetched, stats, _ = _fetch_incremental_purchase_order_details(
            mismatch,
            orders,
            cached,
            last_full,
            lambda _count, _code: None,
            last_full,
        )

        self.assertEqual(len(mismatch.calls), 25)
        self.assertTrue(stats["incremental_fallback"])
        self.assertEqual(stats["sample_mismatch_count"], 1)
        self.assertEqual([detail[1]["balance"] for detail in fetched], [1] * 20)

    def test_multiple_delivery_notes_are_preserved_in_stable_order(self):
        self.assertIsNotNone(_consolidate_import_rows, "导入行合并函数尚未实现")
        if _consolidate_import_rows is None:
            return

        rows = pd.DataFrame(
            [
                ["仓A", "GYS-001", "SKU-A", 10, "站点A", "单据A", "原因"],
                ["仓A", "GYS-001", "SKU-A", 5, "站点A", "单据A", "原因：5"],
                ["仓A", "GYS-001", "SKU-A", 3, "站点A", "单据A", "其他备注"],
                ["仓A", "GYS-001", "SKU-A", 2, "站点A", "单据A", "原因"],
            ],
            columns=IMPORT_COLUMNS,
        )

        result = _consolidate_import_rows(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["*本次交货量"], 20)
        self.assertEqual(result.iloc[0]["交货备注"], "原因：5；其他备注")


class WorkerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(run_once, "Worker 尚未实现")
        self.assertIsNotNone(recover_stale_jobs, "任务恢复尚未实现")
        if run_once is None or recover_stale_jobs is None:
            self.skipTest("Worker 尚未实现")
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database_url = f"sqlite+pysqlite:///{self.root / 'worker.db'}"
        self.storage_root = self.root / "storage"
        self.app = create_app(
            database_url=self.database_url,
            storage_root=self.storage_root,
            bootstrap_admin=("admin", "admin-pass"),
        )
        self.client = SyncASGIClient(self.app)
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        self.headers = {"Authorization": f"Bearer {login.json()['token']}"}
        self.inputs = self.create_master_inputs(self.root)
        self.upload_versions()

    def tearDown(self):
        if hasattr(self, "client"):
            self.client.close()
        if hasattr(self, "app"):
            self.app.state.database.dispose()
        if hasattr(self, "directory"):
            self.directory.cleanup()

    @staticmethod
    def create_master_inputs(root: Path) -> dict[str, Path]:
        purchase = root / "purchase.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"])
        sheet.append(
            ["待交货", "KuangBiao", "SKU-A", "AMAZON:SEEKWAY:US", "水鞋-广州仓", 100]
        )
        workbook.save(purchase)

        product = root / "product.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["SKU", "店铺/站点", "品类A", "锁仓MKSU"])
        sheet.append(["SKU-A", "SEEKWAY:US", "水鞋", "锁"])
        workbook.save(product)

        supplier = root / "supplier.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["供应商编号", "供应商名称", "状态"])
        sheet.append(["GYS-023", "KuangBiao", "启用"])
        workbook.save(supplier)

        position = root / "position.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "MSKU_视图"
        sheet.append(
            ["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位", "已下单可售天数"]
        )
        sheet.append(["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货", 90])
        workbook.save(position)

        template = root / "template.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet["A1"] = "模板提示"
        sheet.merge_cells("A1:G1")
        sheet.append(IMPORT_COLUMNS)
        sheet.append(["示例仓", "示例供应商", "示例SKU", 1, "示例站点", "", ""])
        workbook.save(template)

        inbound_template = root / "inbound_template.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "批量入库"
        sheet.append(INBOUND_TEMPLATE_COLUMNS)
        sheet.append(["示例"] + [""] * (len(INBOUND_TEMPLATE_COLUMNS) - 1))
        workbook.save(inbound_template)
        return {
            "purchase": purchase,
            "product": product,
            "supplier": supplier,
            "position": position,
            "template": template,
            "inbound_template": inbound_template,
        }

    @staticmethod
    def create_delivery(path: Path, quantity: int) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "汇总"
        sheet.append([])
        sheet.append([])
        sheet.append([])
        sheet.append(["SKU", "US站", "总计"])
        sheet.append(["SKU-A", quantity, quantity])
        workbook.save(path)
        return path

    @staticmethod
    def create_self_operated_delivery(path: Path, quantity: int) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "明细"
        sheet.append([])
        sheet.append([])
        sheet.append([])
        sheet.append(["积加SKU", "实收数量", "站点", "交货单号"])
        sheet.append(["SKU-A", quantity, "US站", "LN2608179025"])
        workbook.save(path)
        return path

    @staticmethod
    def create_self_operated_inbound(path: Path) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        source_columns = [
            column for column in INBOUND_TEMPLATE_COLUMNS if column != "最大可收货"
        ]
        sheet.append(source_columns + ["供应商"])
        for site, inbound_number in (
            ("AMAZON:RIVMOUNT:US", "IN-R"),
            ("AMAZON:SEEKWAY:US", "IN-S"),
        ):
            values = {column: "" for column in INBOUND_TEMPLATE_COLUMNS}
            values.update(
                {
                    "入库单号": inbound_number,
                    "入库仓": "自营仓",
                    "SKU": "SKU-A",
                    "平台站点": site,
                    "关联采购单": f"PO-20260801-{site}",
                    "关联交货单/调拨单": "LN2608179025",
                    "应收货": 10,
                }
            )
            sheet.append([values[column] for column in source_columns] + ["KuangBiao"])
        workbook.save(path)
        return path

    def upload_versions(self):
        for kind, path in self.inputs.items():
            with path.open("rb") as upload:
                response = self.client.post(
                    f"/api/input-versions/{kind}",
                    headers=self.headers,
                    data={"name": f"{kind}-v1", "activate": "true"},
                    files={"file": (path.name, upload)},
                )
            self.assertEqual(response.status_code, 201, response.text)

    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    @patch("delivery_note.worker.GerpgoClient.from_config")
    def test_purchase_sync_creates_inactive_candidate(self, client_factory):
        api_client = client_factory.return_value
        api_client.list_purchase_orders.return_value = [
            {"code": "PO-1", "invoicesStatusName": "待交货"}
        ]
        api_client.purchase_order_detail.return_value = {
            "warehouseProcureItemVos": [
                {
                    "procureItemVos": [
                        {
                            "product": "SKU-A",
                            "supplierCode": "GYS-023",
                            "supplierName": "接口供应商",
                            "arrivalMarketName": "共享",
                            "deliveryWarehouseName": "水鞋-广州仓",
                            "balanceQuantity": 12,
                        }
                    ]
                }
            ]
        }

        started = self.client.post(
            "/api/purchase-sync",
            headers=self.headers,
        )
        self.assertEqual(started.status_code, 201, started.text)
        job_id = started.json()["id"]

        completed_id = run_once(self.database_url, self.storage_root)

        self.assertEqual(completed_id, job_id)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                job = session.get(PurchaseSyncJob, job_id)
                self.assertEqual(job.status, "succeeded", job.error_message)
                self.assertIsNotNone(job.candidate_version_id)
                candidate = session.get(
                    InputVersion,
                    job.candidate_version_id,
                )
                self.assertFalse(candidate.active)
                rows = pd.read_excel(candidate.storage_path)
                self.assertEqual(rows.iloc[0]["未交量"], 12)
                self.assertEqual(rows.iloc[0]["供应商"], "接口供应商")
                self.assertEqual(rows.iloc[0]["平台站点"], "共享")
                self.assertEqual(job.issues[0]["code"], "shared_site")
        finally:
            database.dispose()

    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    @patch("delivery_note.worker.GerpgoClient.from_config")
    def test_self_operated_inbound_sync_creates_candidate(self, client_factory):
        client_factory.return_value.list_self_operated_inbound_orders.return_value = [
            {
                "orderNo": "IN-1",
                "orderType": "purchase",
                "orderStatus": "WAIT_INBOUND",
                "warehouseName": "自营仓",
                "purchaseCode": "PO-1",
                "releatedCode": "LN2608179025",
                "supplierName": "KuangBiao",
                "orderItemResultList": [
                    {
                        "sku": "SKU-A",
                        "marketName": "共享",
                        "arriveNum": 10,
                    }
                ],
            }
        ]
        started = self.client.post(
            "/api/self-operated-inbound-sync",
            headers=self.headers,
        )
        self.assertEqual(started.status_code, 201, started.text)
        job_id = started.json()["id"]

        completed_id = run_once(self.database_url, self.storage_root)

        self.assertEqual(completed_id, job_id)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                job = session.get(SelfOperatedInboundSyncJob, job_id)
                self.assertEqual(job.status, "succeeded", job.error_message)
                candidate = session.get(InputVersion, job.candidate_version_id)
                self.assertFalse(candidate.active)
                rows = pd.read_excel(candidate.storage_path)
                self.assertEqual(rows.iloc[0]["入库单号"], "IN-1")
                self.assertEqual(rows.iloc[0]["平台站点"], "共享")
                self.assertEqual(job.issues[0]["code"], "shared_site")
        finally:
            database.dispose()

    @patch(
        "delivery_note.worker._claim_self_operated_inbound_sync_job",
        return_value=None,
    )
    @patch("delivery_note.worker._claim_purchase_sync_job")
    @patch("delivery_note.worker._claim_job")
    def test_inbound_worker_only_claims_inbound_queue(
        self,
        claim_batch,
        claim_purchase,
        claim_inbound,
    ):
        completed_id = run_once(
            self.database_url,
            self.storage_root,
            "inbound-sync",
        )

        self.assertIsNone(completed_id)
        claim_batch.assert_not_called()
        claim_purchase.assert_not_called()
        claim_inbound.assert_called_once()

    def test_worker_queue_argument_defaults_to_all(self):
        parser = build_parser()

        self.assertEqual(parser.parse_args([]).queue, "all")
        self.assertEqual(
            parser.parse_args(["--queue", "purchase-sync"]).queue,
            "purchase-sync",
        )

    def create_batch(self, delivery_paths: list[Path]) -> tuple[int, int]:
        created = self.client.post(
            "/api/batches",
            headers=self.headers,
            json={"name": "Worker 集成测试"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        for path in delivery_paths:
            with path.open("rb") as upload:
                response = self.client.post(
                    f"/api/batches/{batch_id}/files",
                    headers=self.headers,
                    files={"file": (path.name, upload)},
                )
            self.assertEqual(response.status_code, 201, response.text)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=self.headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        job = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=self.headers,
        )
        self.assertEqual(job.status_code, 202, job.text)
        return batch_id, job.json()["id"]

    def test_compute_split_export_and_zip_are_end_to_end(self):
        first = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 80
        )
        second = self.create_delivery(
            self.root / "260717-狂飙-B交货单-发货20箱.xlsx", 80
        )
        batch_id, compute_job_id = self.create_batch([first, second])

        self.assertEqual(run_once(self.database_url, self.storage_root), compute_job_id)
        batch = self.client.get(f"/api/batches/{batch_id}", headers=self.headers).json()
        self.assertEqual(batch["status"], "succeeded")
        illegal_preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight", headers=self.headers
        )
        self.assertEqual(illegal_preflight.status_code, 409)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=self.headers).json()[
                "status"
            ],
            "succeeded",
        )
        self.assertEqual(
            [(item["import_total"], item["manual_total"]) for item in batch["files"]],
            [(80, 0), (20, 60)],
        )
        exceptions = self.client.get(
            f"/api/batches/{batch_id}/exceptions", headers=self.headers
        ).json()
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]["manual_quantity"], 60)
        self.assertEqual(exceptions[0]["scale_position"], "短尾")
        self.assertEqual(exceptions[0]["stocking_position"], "备货")
        self.assertEqual(exceptions[0]["ordered_days"], 90)

        split = self.client.put(
            f"/api/exceptions/{exceptions[0]['id']}/split",
            headers=self.headers,
            json={
                "parts": [
                    {
                        "quantity": 25,
                        "destination": "水鞋-广州仓",
                        "delivery_note": "超出采购未交量",
                        "resolved": True,
                    },
                    {
                        "quantity": 35,
                        "delivery_note": "超出采购未交量",
                        "resolved": False,
                    },
                ]
            },
        )
        self.assertEqual(split.status_code, 200, split.text)
        self.assertEqual(split.json()["scale_position"], "短尾")
        self.assertEqual(split.json()["stocking_position"], "备货")
        self.assertEqual(split.json()["ordered_days"], 90)
        export = self.client.post(
            f"/api/batches/{batch_id}/export", headers=self.headers
        )
        self.assertEqual(export.status_code, 202, export.text)
        export_job_id = export.json()["id"]
        self.assertEqual(run_once(self.database_url, self.storage_root), export_job_id)

        completed = self.client.get(
            f"/api/batches/{batch_id}", headers=self.headers
        ).json()
        self.assertTrue(completed["download_ready"])
        self.assertTrue(completed["merged_download_ready"])
        self.assertTrue(all(item["download_ready"] for item in completed["files"]))
        merged_response = self.client.get(
            f"/api/batches/{batch_id}/download-merged", headers=self.headers
        )
        self.assertEqual(merged_response.status_code, 200, merged_response.text)
        merged_book = load_workbook(
            BytesIO(merged_response.content),
            data_only=True,
        )
        merged_import_sheet = merged_book["交货导入"]
        merged_pending_sheet = merged_book["待处理导入"]
        self.assertEqual(merged_import_sheet.cell(3, 1).value, "示例仓")
        self.assertEqual(
            sum(
                merged_import_sheet.cell(row, 4).value or 0
                for row in range(4, merged_import_sheet.max_row + 1)
            ),
            125,
        )
        self.assertEqual(
            sum(
                merged_pending_sheet.cell(row, 4).value or 0
                for row in range(3, merged_pending_sheet.max_row + 1)
            ),
            35,
        )
        merged_import_notes = [
            merged_import_sheet.cell(row, 6).value
            for row in range(4, merged_import_sheet.max_row + 1)
        ]
        self.assertTrue(merged_import_notes[0].endswith("-01-10箱"))
        self.assertTrue(
            all(note.endswith("-02-20箱") for note in merged_import_notes[1:])
        )
        self.assertTrue(merged_pending_sheet.cell(3, 6).value.endswith("-02-20箱"))
        archive_response = self.client.get(
            f"/api/batches/{batch_id}/download", headers=self.headers
        )
        self.assertEqual(archive_response.status_code, 200, archive_response.text)
        with ZipFile(BytesIO(archive_response.content)) as archive:
            names = sorted(archive.namelist())
            self.assertEqual(len(names), 2)
            self.assertFalse(any("merged" in name for name in names))
            second_book = load_workbook(BytesIO(archive.read(names[1])), data_only=True)

        import_sheet = second_book["交货导入"]
        pending_sheet = second_book["待处理导入"]
        import_total = sum(
            import_sheet.cell(row, 4).value or 0
            for row in range(4, import_sheet.max_row + 1)
        )
        pending_total = sum(
            pending_sheet.cell(row, 4).value or 0
            for row in range(3, pending_sheet.max_row + 1)
        )
        self.assertEqual((import_total, pending_total), (45, 35))
        import_records = [
            [import_sheet.cell(row, column).value for column in range(1, 8)]
            for row in range(4, import_sheet.max_row + 1)
        ]
        self.assertEqual(len(import_records), 1)
        self.assertEqual(import_records[0][3], 45)
        self.assertEqual(import_records[0][6], "超出采购未交量：60")
        self.assertIsNone(run_once(self.database_url, self.storage_root))
        repeated = self.client.post(
            f"/api/batches/{batch_id}/export", headers=self.headers
        )
        self.assertEqual(repeated.json()["id"], export_job_id)
        self.assertEqual(repeated.json()["status"], "succeeded")

        with self.app.state.database.session() as session:
            stored_batch = session.get(Batch, batch_id)
            merged_path = Path(stored_batch.zip_path).with_name(
                f"batch-{batch_id}-merged.xlsx"
            )
        merged_path.unlink()
        self.assertEqual(
            self.client.get(
                f"/api/batches/{batch_id}/download-merged",
                headers=self.headers,
            ).status_code,
            404,
        )
        regenerated = self.client.post(
            f"/api/batches/{batch_id}/export", headers=self.headers
        )
        self.assertEqual(regenerated.json()["id"], export_job_id)
        self.assertEqual(regenerated.json()["status"], "queued")
        self.assertEqual(run_once(self.database_url, self.storage_root), export_job_id)
        self.assertEqual(
            self.client.get(
                f"/api/batches/{batch_id}/download-merged",
                headers=self.headers,
            ).status_code,
            200,
        )

    def test_compute_uses_the_overreceipt_rule_locked_when_batch_was_created(self):
        first_rule = self.client.post(
            "/api/overreceipt-rule-versions",
            headers=self.headers,
            json={
                "name": "允许短尾超收 50",
                "short_tail_limit": 50,
                "medium_tail_limit": 20,
                "long_tail_limit": 10,
                "allowed_warehouses": ["水鞋-广州仓"],
            },
        )
        self.assertEqual(first_rule.status_code, 201, first_rule.text)
        first = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 80
        )
        second = self.create_delivery(
            self.root / "260717-狂飙-B交货单-发货20箱.xlsx", 80
        )
        batch_id, compute_job_id = self.create_batch([first, second])

        replacement_rule = self.client.post(
            "/api/overreceipt-rule-versions",
            headers=self.headers,
            json={
                "name": "停止自动超收",
                "short_tail_limit": 0,
                "medium_tail_limit": 0,
                "long_tail_limit": 0,
                "allowed_warehouses": [],
            },
        )
        self.assertEqual(replacement_rule.status_code, 201, replacement_rule.text)

        self.assertEqual(run_once(self.database_url, self.storage_root), compute_job_id)
        batch = self.client.get(f"/api/batches/{batch_id}", headers=self.headers).json()

        self.assertEqual(batch["overreceipt_rule"]["id"], first_rule.json()["id"])
        self.assertEqual(
            [(item["import_total"], item["manual_total"]) for item in batch["files"]],
            [(80, 0), (70, 10)],
        )
        self.assertEqual(
            batch["files"][1]["import_total"] + batch["files"][1]["manual_total"],
            80,
        )
        exceptions = self.client.get(
            f"/api/batches/{batch_id}/exceptions", headers=self.headers
        ).json()
        self.assertEqual(exceptions[0]["reason"], "超出允许超收量")
        self.assertEqual(exceptions[0]["manual_quantity"], 10)
        self.assertEqual(exceptions[0]["purchase_allocated_quantity"], 20)
        self.assertEqual(exceptions[0]["overreceipt_allocated_quantity"], 50)
        self.assertEqual(exceptions[0]["overreceipt_remaining_quantity"], 0)

        export = self.client.post(
            f"/api/batches/{batch_id}/export", headers=self.headers
        )
        self.assertEqual(export.status_code, 202, export.text)
        self.assertEqual(
            run_once(self.database_url, self.storage_root),
            export.json()["id"],
        )
        archive_response = self.client.get(
            f"/api/batches/{batch_id}/download", headers=self.headers
        )
        with ZipFile(BytesIO(archive_response.content)) as archive:
            names = sorted(archive.namelist())
            second_book = load_workbook(
                BytesIO(archive.read(names[1])),
                data_only=True,
            )
        import_sheet = second_book["交货导入"]
        pending_sheet = second_book["待处理导入"]
        self.assertEqual(
            [import_sheet.cell(2, column).value for column in range(1, 8)],
            IMPORT_COLUMNS,
        )
        self.assertEqual(
            sum(
                import_sheet.cell(row, 4).value or 0
                for row in range(4, import_sheet.max_row + 1)
            ),
            70,
        )
        self.assertEqual(pending_sheet.cell(3, 4).value, 10)
        self.assertEqual(pending_sheet.cell(3, 7).value, "超出允许超收量：10")

    def test_self_operated_site_choice_recomputes_and_exports_inbound_workbook(self):
        product = self.root / "product-ambiguous.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["SKU", "店铺/站点", "品类A", "锁仓MKSU"])
        sheet.append(["SKU-A", "RIVMOUNT:US", "水鞋", "锁"])
        sheet.append(["SKU-A", "SEEKWAY:US", "水鞋", "锁"])
        workbook.save(product)
        with product.open("rb") as upload:
            product_version = self.client.post(
                "/api/input-versions/product",
                headers=self.headers,
                data={"name": "product-ambiguous", "activate": "true"},
                files={"file": (product.name, upload)},
            )
        self.assertEqual(product_version.status_code, 201, product_version.text)
        rule = self.client.post(
            "/api/self-operated-overreceipt-rule-versions",
            headers=self.headers,
            json={"name": "自营仓超收 5 件", "allowance": 5},
        )
        self.assertEqual(rule.status_code, 201, rule.text)

        created = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "自营仓 Worker 集成测试"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        delivery = self.create_self_operated_delivery(
            self.root / "260817-狂飙-质检交货单.xlsx",
            18,
        )
        inbound = self.create_self_operated_inbound(self.root / "自营仓收货入库单.xlsx")
        with delivery.open("rb") as upload:
            source = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=self.headers,
                files={"file": (delivery.name, upload)},
            )
        self.assertEqual(source.status_code, 201, source.text)
        with inbound.open("rb") as upload:
            inbound_upload = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=self.headers,
                files={"file": (inbound.name, upload)},
            )
        self.assertEqual(inbound_upload.status_code, 200, inbound_upload.text)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=self.headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        compute = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=self.headers,
        )
        self.assertEqual(compute.status_code, 202, compute.text)
        self.assertEqual(
            run_once(self.database_url, self.storage_root),
            compute.json()["id"],
        )

        exceptions = self.client.get(
            f"/api/batches/{batch_id}/exceptions",
            headers=self.headers,
        ).json()
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]["reason"], "产品信息站点不唯一")
        self.assertIn("AMAZON:RIVMOUNT:US", exceptions[0]["full_site"])
        self.assertIn("AMAZON:SEEKWAY:US", exceptions[0]["full_site"])
        selected = self.client.put(
            f"/api/exceptions/{exceptions[0]['id']}/self-operated-site",
            headers=self.headers,
            json={"full_site": "AMAZON:RIVMOUNT:US"},
        )
        self.assertEqual(selected.status_code, 202, selected.text)
        self.assertEqual(
            run_once(self.database_url, self.storage_root),
            selected.json()["id"],
        )

        batch = self.client.get(
            f"/api/batches/{batch_id}",
            headers=self.headers,
        ).json()
        self.assertEqual(batch["summary"]["delivery_total"], 18)
        self.assertEqual(batch["summary"]["import_total"], 15)
        self.assertEqual(batch["summary"]["manual_total"], 3)
        exceptions = self.client.get(
            f"/api/batches/{batch_id}/exceptions",
            headers=self.headers,
        ).json()
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]["reason"], "超出允许超收量")
        self.assertEqual(exceptions[0]["manual_quantity"], 3)

        with self.app.state.database.session() as session:
            stored_batch = session.get(Batch, batch_id)
            stored_batch.error_message = "历史导出失败"
            session.commit()
        export = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=self.headers,
        )
        self.assertEqual(export.status_code, 202, export.text)
        self.assertEqual(
            run_once(self.database_url, self.storage_root),
            export.json()["id"],
        )
        refreshed_batch = self.client.get(
            f"/api/batches/{batch_id}", headers=self.headers
        ).json()
        self.assertIsNone(refreshed_batch["error_message"])
        result = self.client.get(
            f"/api/batch-files/{batch['files'][0]['id']}/download",
            headers=self.headers,
        )
        self.assertEqual(result.status_code, 200, result.text)
        output = load_workbook(BytesIO(result.content), data_only=True)
        output_sheet = output["批量入库"]
        self.assertEqual(output_sheet.cell(2, 8).value, "AMAZON:RIVMOUNT:US")
        self.assertEqual(output_sheet.cell(2, 12).value, 10)
        self.assertEqual(output_sheet.cell(2, 17).value, 15)
        self.assertEqual(output_sheet.cell(2, 18).value, "未分配库位")
        self.assertIsNone(output_sheet.cell(2, 19).value)
        self.assertEqual(output_sheet.cell(2, 20).value, "规则允许超收：5")

    def test_stale_job_recovers_and_failed_batch_persists_no_partial_results(self):
        valid = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 80
        )
        second = self.create_delivery(
            self.root / "260717-狂飙-B交货单-发货20箱.xlsx", 20
        )
        batch_id, job_id = self.create_batch([valid, second])

        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            job.status = "running"
            job.claim_token = "old-claim"
            job.heartbeat_at = datetime.utcnow() - timedelta(hours=2)
            sources = (
                session.query(BatchFile)
                .filter_by(batch_id=batch_id)
                .order_by(BatchFile.file_order)
                .all()
            )
            Path(sources[1].storage_path).write_bytes(b"not-an-excel-file")
            session.commit()
        recovered = recover_stale_jobs(
            self.database_url,
            stale_after=timedelta(minutes=30),
        )
        self.assertEqual(recovered, 1)
        with self.app.state.database.session() as session:
            self.assertIsNone(session.get(Job, job_id).claim_token)
        self.assertEqual(run_once(self.database_url, self.storage_root), job_id)

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            sources = session.query(BatchFile).filter_by(batch_id=batch_id).all()
            exceptions = (
                session.query(ExceptionRecord)
                .join(BatchFile)
                .filter(BatchFile.batch_id == batch_id)
                .all()
            )
            job = session.get(Job, job_id)
            self.assertEqual(batch.status, "failed")
            self.assertEqual(job.status, "failed")
            self.assertTrue(job.error_message)
            self.assertEqual(
                [
                    (source.import_total, source.manual_total, source.import_rows)
                    for source in sources
                ],
                [(0, 0, []), (0, 0, [])],
            )
            self.assertEqual(exceptions, [])

    def test_stale_worker_cannot_overwrite_new_claim(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 20
        )
        batch_id, job_id = self.create_batch([delivery])
        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            job.status = "running"
            job.claim_token = "new-claim"
            job.error_message = None
            batch = session.get(Batch, batch_id)
            batch.status = "running"
            session.commit()

        _fail_job(self.app.state.database, job_id, "old-claim", "旧 Worker 失败")

        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            batch = session.get(Batch, batch_id)
            self.assertEqual(job.status, "running")
            self.assertEqual(job.claim_token, "new-claim")
            self.assertIsNone(job.error_message)
            self.assertEqual(batch.status, "running")


class WorkerProcessLifecycleTests(unittest.TestCase):
    def test_worker_exits_cleanly_on_sigterm(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database_url = f"sqlite+pysqlite:///{root / 'worker.db'}"
            database = Database(database_url)
            database.create_schema()
            database.dispose()
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "delivery_note.worker",
                    "--database-url",
                    database_url,
                    "--storage-root",
                    str(root / "storage"),
                    "--poll-interval",
                    "0.05",
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(2)
                self.assertIsNone(process.poll(), "Worker 在收到信号前意外退出")
                process.terminate()
                returncode = process.wait(timeout=5)
                stdout, stderr = process.communicate()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        self.assertEqual(returncode, 0, f"stdout={stdout}\nstderr={stderr}")


if __name__ == "__main__":
    unittest.main()
