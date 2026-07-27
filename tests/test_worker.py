from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from delivery_note.pipeline import IMPORT_COLUMNS
from tests.asgi_client import SyncASGIClient
from delivery_note.web.api import create_app
from delivery_note.web.database import Database
from delivery_note.web.models import Batch, BatchFile, ExceptionRecord, Job

try:
    from delivery_note.worker import _fail_job, recover_stale_jobs, run_once
except ImportError:
    _fail_job = None
    recover_stale_jobs = None
    run_once = None


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
        sheet.append(["待交货", "KuangBiao", "SKU-A", "AMAZON:SEEKWAY:US", "水鞋-广州仓", 100])
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
        sheet.append(["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位", "已下单可售天数"])
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
        return {
            "purchase": purchase,
            "product": product,
            "supplier": supplier,
            "position": position,
            "template": template,
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
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=self.headers
        ).json()
        self.assertEqual(batch["status"], "succeeded")
        illegal_preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight", headers=self.headers
        )
        self.assertEqual(illegal_preflight.status_code, 409)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=self.headers).json()["status"],
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
                    {"quantity": 25, "destination": "水鞋-广州仓", "resolved": True},
                    {"quantity": 35, "resolved": False},
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
        self.assertTrue(
            merged_pending_sheet.cell(3, 6).value.endswith("-02-20箱")
        )
        archive_response = self.client.get(
            f"/api/batches/{batch_id}/download", headers=self.headers
        )
        self.assertEqual(archive_response.status_code, 200, archive_response.text)
        with ZipFile(BytesIO(archive_response.content)) as archive:
            names = sorted(archive.namelist())
            self.assertEqual(len(names), 2)
            self.assertFalse(any("merged" in name for name in names))
            second_book = load_workbook(
                BytesIO(archive.read(names[1])), data_only=True
            )

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
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=self.headers
        ).json()

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
                [(source.import_total, source.manual_total, source.import_rows) for source in sources],
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
