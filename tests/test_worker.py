from tests.support.worker import WorkerCase
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from sqlalchemy import select

import delivery_note.workers.export_files as export_files_module
import delivery_note.workers.scheduler as scheduler_module
import delivery_note.workers.compute_delivery as compute_module
import delivery_note.workers.leases as lease_module
from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
    SelfOperatedSiteResolution,
)

from delivery_note.workers.scheduler import _fail_job
from delivery_note.worker import (
    recover_stale_jobs,
    run_once,
)




class WorkerIntegrationTests(WorkerCase):












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
        self.assertEqual(exceptions[0]["reason_code"], "purchase_balance_exceeded")
        with self.app.state.database.session() as session:
            stored = session.get(ExceptionRecord, exceptions[0]["id"])
            self.assertEqual(stored.reason_code, "purchase_balance_exceeded")
        self.assertEqual(exceptions[0]["scale_position"], "短尾")
        self.assertEqual(exceptions[0]["stocking_position"], "备货")
        self.assertNotIn("ordered_days", exceptions[0])

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
        self.assertNotIn("ordered_days", split.json())
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
            first_export_dir = Path(stored_batch.zip_path).parent
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
        with self.app.state.database.session() as session:
            stored_batch = session.get(Batch, batch_id)
            second_export_dir = Path(stored_batch.zip_path).parent
        self.assertNotEqual(second_export_dir, first_export_dir)
        self.assertFalse(first_export_dir.exists())
        self.assertTrue(second_export_dir.is_dir())

        second_merged_path = second_export_dir / f"batch-{batch_id}-merged.xlsx"
        second_merged_path.unlink()
        retried = self.client.post(
            f"/api/batches/{batch_id}/export", headers=self.headers
        )
        self.assertEqual(retried.json()["status"], "queued")
        with (
            patch.object(
                export_files_module.shutil,
                "rmtree",
                side_effect=PermissionError("denied"),
            ),
            self.assertLogs("delivery_note.worker", level="WARNING"),
        ):
            self.assertEqual(
                run_once(self.database_url, self.storage_root),
                export_job_id,
            )
        with self.app.state.database.session() as session:
            stored_batch = session.get(Batch, batch_id)
            stored_job = session.get(Job, export_job_id)
            third_export_dir = Path(stored_batch.zip_path).parent
            self.assertEqual(stored_batch.status, "succeeded")
            self.assertEqual(stored_job.status, "succeeded")
        self.assertNotEqual(third_export_dir, second_export_dir)
        self.assertTrue(third_export_dir.is_dir())
        self.assertTrue(second_export_dir.is_dir())



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
        rejected = self.client.put(
            f"/api/exceptions/{exceptions[0]['id']}/self-operated-site",
            headers=self.headers,
            json={"full_site": "AMAZON:OTHER:US"},
        )
        self.assertEqual(rejected.status_code, 400)
        with self.app.state.database.session() as session:
            self.assertIsNone(
                session.scalar(
                    select(SelfOperatedSiteResolution).where(
                        SelfOperatedSiteResolution.batch_id == batch_id
                    )
                )
            )
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

    def test_self_operated_multi_file_order_shares_balances_and_exports_all_formats(
        self,
    ):
        rule = self.client.post(
            "/api/self-operated-overreceipt-rule-versions",
            headers=self.headers,
            json={"name": "自营仓批次共享超收 5 件", "allowance": 5},
        )
        self.assertEqual(rule.status_code, 201, rule.text)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "自营仓多质检单 Worker 测试"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]

        first_path = self.create_self_operated_delivery(
            self.root / "260817-狂飙-A质检交货单.xlsx",
            10,
        )
        second_path = self.create_self_operated_delivery(
            self.root / "260817-狂飙-B质检交货单.xlsx",
            8,
        )
        uploaded = []
        for source_path in (first_path, second_path):
            with source_path.open("rb") as upload:
                response = self.client.post(
                    f"/api/batches/{batch_id}/files",
                    headers=self.headers,
                    files={"file": (source_path.name, upload)},
                )
            self.assertEqual(response.status_code, 201, response.text)
            uploaded.append(response.json())

        reordered = self.client.put(
            f"/api/batches/{batch_id}/files/order",
            headers=self.headers,
            json={"file_ids": [uploaded[1]["id"], uploaded[0]["id"]]},
        )
        self.assertEqual(reordered.status_code, 200, reordered.text)
        inbound_path = self.create_self_operated_inbound(
            self.root / "自营仓多质检单待入库.xlsx"
        )
        with inbound_path.open("rb") as upload:
            inbound = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=self.headers,
                files={"file": (inbound_path.name, upload)},
            )
        self.assertEqual(inbound.status_code, 200, inbound.text)

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

        computed = self.client.get(
            f"/api/batches/{batch_id}",
            headers=self.headers,
        ).json()
        self.assertEqual(
            [
                (
                    source["original_name"],
                    source["import_total"],
                    source["manual_total"],
                )
                for source in computed["files"]
            ],
            [
                ("260817-狂飙-B质检交货单.xlsx", 8, 0),
                ("260817-狂飙-A质检交货单.xlsx", 7, 3),
            ],
        )
        self.assertEqual(
            computed["summary"],
            {
                "delivery_total": 18,
                "import_total": 15,
                "manual_total": 3,
                "conserved": True,
            },
        )

        export = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=self.headers,
        )
        self.assertEqual(export.status_code, 202, export.text)
        self.assertEqual(
            run_once(self.database_url, self.storage_root),
            export.json()["id"],
        )
        exported = self.client.get(
            f"/api/batches/{batch_id}",
            headers=self.headers,
        ).json()
        self.assertTrue(exported["download_ready"])
        self.assertTrue(exported["merged_download_ready"])
        self.assertTrue(all(source["download_ready"] for source in exported["files"]))

        merged_response = self.client.get(
            f"/api/batches/{batch_id}/download-merged",
            headers=self.headers,
        )
        self.assertEqual(merged_response.status_code, 200, merged_response.text)
        merged_book = load_workbook(BytesIO(merged_response.content), data_only=True)
        merged_sheet = merged_book["批量入库"]
        self.assertEqual(merged_sheet.max_row, 2)
        self.assertEqual(
            sum(
                merged_sheet.cell(row, 17).value or 0
                for row in range(2, merged_sheet.max_row + 1)
            ),
            15,
        )

        archive_response = self.client.get(
            f"/api/batches/{batch_id}/download",
            headers=self.headers,
        )
        self.assertEqual(archive_response.status_code, 200, archive_response.text)
        with ZipFile(BytesIO(archive_response.content)) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                [
                    "260817-狂飙-A质检交货单_积加入库.xlsx",
                    "260817-狂飙-B质检交货单_积加入库.xlsx",
                ],
            )

        for source in exported["files"]:
            response = self.client.get(
                f"/api/batch-files/{source['id']}/download",
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)

        with self.app.state.database.session() as session:
            stored_batch = session.get(Batch, batch_id)
            first_export_dir = Path(stored_batch.zip_path).parent
            merged_path = first_export_dir / f"batch-{batch_id}-merged.xlsx"
        merged_path.unlink()
        regenerated = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=self.headers,
        )
        self.assertEqual(regenerated.status_code, 202, regenerated.text)
        self.assertEqual(regenerated.json()["status"], "queued")
        self.assertEqual(
            run_once(self.database_url, self.storage_root),
            export.json()["id"],
        )
        with self.app.state.database.session() as session:
            stored_batch = session.get(Batch, batch_id)
            second_export_dir = Path(stored_batch.zip_path).parent
        self.assertNotEqual(second_export_dir, first_export_dir)
        self.assertFalse(first_export_dir.exists())
        self.assertTrue(second_export_dir.is_dir())


    def test_self_operated_multi_file_compute_failure_persists_no_partial_result(self):
        created = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "自营仓多文件原子计算"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        source_paths = [
            self.create_self_operated_delivery(
                self.root / "260817-狂飙-原子-A.xlsx",
                5,
            ),
            self.create_self_operated_delivery(
                self.root / "260817-狂飙-原子-B.xlsx",
                5,
            ),
        ]
        for source_path in source_paths:
            with source_path.open("rb") as upload:
                response = self.client.post(
                    f"/api/batches/{batch_id}/files",
                    headers=self.headers,
                    files={"file": (source_path.name, upload)},
                )
            self.assertEqual(response.status_code, 201, response.text)
        inbound_path = self.create_self_operated_inbound(
            self.root / "自营仓原子计算待入库.xlsx"
        )
        with inbound_path.open("rb") as upload:
            response = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=self.headers,
                files={"file": (inbound_path.name, upload)},
            )
        self.assertEqual(response.status_code, 200, response.text)
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

        with self.app.state.database.session() as session:
            sources = session.scalars(
                select(BatchFile)
                .where(BatchFile.batch_id == batch_id)
                .order_by(BatchFile.file_order)
            ).all()
            Path(sources[1].storage_path).write_bytes(b"invalid")

        with self.assertLogs("delivery_note.worker", level="ERROR"):
            self.assertEqual(
                run_once(self.database_url, self.storage_root),
                compute.json()["id"],
            )
        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            ).all()
            exceptions = session.scalars(
                select(ExceptionRecord)
                .join(BatchFile)
                .where(BatchFile.batch_id == batch_id)
            ).all()
            self.assertEqual(batch.status, "failed")
            self.assertEqual(
                [
                    (source.import_total, source.manual_total, source.import_rows)
                    for source in sources
                ],
                [(0, 0, []), (0, 0, [])],
            )
            self.assertEqual(exceptions, [])

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
        with self.assertLogs("delivery_note.worker", level="ERROR"):
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

    def test_stale_recovery_only_scans_the_selected_queue(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        _batch_id, batch_job_id = self.create_batch([delivery])
        stale_at = datetime.utcnow() - timedelta(hours=2)
        with self.app.state.database.session() as session:
            batch_job = session.get(Job, batch_job_id)
            batch_job.status = "running"
            batch_job.attempts = 1
            batch_job.claim_token = "batch-claim"
            batch_job.heartbeat_at = stale_at
            purchase_job = PurchaseSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=1,
                claim_token="purchase-claim",
                heartbeat_at=stale_at,
            )
            inbound_job = SelfOperatedInboundSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=1,
                claim_token="inbound-claim",
                heartbeat_at=stale_at,
            )
            session.add_all([purchase_job, inbound_job])
            session.commit()
            purchase_job_id = purchase_job.id
            inbound_job_id = inbound_job.id

        recovered = recover_stale_jobs(
            self.database_url,
            stale_after=timedelta(minutes=30),
            queue="purchase-sync",
        )

        self.assertEqual(recovered, 1)
        with self.app.state.database.session() as session:
            self.assertEqual(session.get(Job, batch_job_id).status, "running")
            self.assertEqual(
                session.get(PurchaseSyncJob, purchase_job_id).status,
                "queued",
            )
            self.assertEqual(
                session.get(SelfOperatedInboundSyncJob, inbound_job_id).status,
                "running",
            )

    def test_stale_jobs_stop_at_retry_cap_and_batch_can_be_retried_manually(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        batch_id, batch_job_id = self.create_batch([delivery])
        stale_at = datetime.utcnow() - timedelta(hours=2)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "running"
            batch_job = session.get(Job, batch_job_id)
            batch_job.status = "running"
            batch_job.attempts = 3
            batch_job.claim_token = "batch-claim"
            batch_job.heartbeat_at = stale_at
            purchase_job = PurchaseSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=3,
                claim_token="purchase-claim",
                heartbeat_at=stale_at,
            )
            inbound_job = SelfOperatedInboundSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=3,
                claim_token="inbound-claim",
                heartbeat_at=stale_at,
            )
            session.add_all([purchase_job, inbound_job])
            session.commit()
            purchase_job_id = purchase_job.id
            inbound_job_id = inbound_job.id

        recovered = recover_stale_jobs(
            self.database_url,
            stale_after=timedelta(minutes=30),
            max_attempts=3,
        )

        self.assertEqual(recovered, 3)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch_job = session.get(Job, batch_job_id)
            purchase_job = session.get(PurchaseSyncJob, purchase_job_id)
            inbound_job = session.get(
                SelfOperatedInboundSyncJob,
                inbound_job_id,
            )
            self.assertEqual(batch.status, "failed")
            self.assertEqual(batch_job.status, "failed")
            self.assertIsNotNone(batch_job.finished_at)
            self.assertEqual(purchase_job.status, "failed")
            self.assertIsNone(purchase_job.active_slot)
            self.assertEqual(inbound_job.status, "failed")
            self.assertIsNone(inbound_job.active_slot)

        retried = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=self.headers,
        )
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["attempts"], 3)
        self.assertEqual(
            run_once(self.database_url, self.storage_root, queue="batch"),
            batch_job_id,
        )
        with self.app.state.database.session() as session:
            retried_job = session.get(Job, batch_job_id)
            self.assertEqual(retried_job.status, "succeeded")
            self.assertEqual(retried_job.attempts, 4)

    def test_background_heartbeat_runs_during_blocking_execution_and_stops(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        _batch_id, job_id = self.create_batch([delivery])
        execution_started = Event()
        release_execution = Event()
        heartbeat_seen = Event()
        original_heartbeat = scheduler_module._heartbeat

        def block_execution(*_args):
            execution_started.set()
            self.assertTrue(release_execution.wait(2))

        def observe_heartbeat(*args):
            original_heartbeat(*args)
            heartbeat_seen.set()

        result = []
        with (
            patch.object(lease_module, "LEASE_HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(
                scheduler_module,
                "_execute_compute",
                side_effect=block_execution,
            ),
            patch.object(
                scheduler_module,
                "_heartbeat",
                side_effect=observe_heartbeat,
            ) as beat,
        ):
            thread = Thread(
                target=lambda: result.append(
                    run_once(self.database_url, self.storage_root, queue="batch")
                )
            )
            thread.start()
            self.assertTrue(execution_started.wait(2))
            self.assertTrue(heartbeat_seen.wait(2))
            release_execution.set()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            heartbeat_count = beat.call_count
            time.sleep(0.05)
            self.assertEqual(beat.call_count, heartbeat_count)

        self.assertEqual(result, [job_id])

    def test_lost_lease_is_logged_and_cannot_be_overwritten(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        batch_id, job_id = self.create_batch([delivery])
        execution_started = Event()
        release_execution = Event()
        lease_lost = Event()
        original_heartbeat = scheduler_module._heartbeat
        original_process = compute_module.process_delivery_batch

        def block_execution(*args, **kwargs):
            execution_started.set()
            self.assertTrue(release_execution.wait(2))
            return original_process(*args, **kwargs)

        def observe_lease_loss(*args):
            try:
                original_heartbeat(*args)
            except lease_module.LostJobLeaseError:
                lease_lost.set()
                raise

        result = []
        with self.assertLogs("delivery_note.worker", level="ERROR") as logs:
            with (
                patch.object(
                    lease_module,
                    "LEASE_HEARTBEAT_INTERVAL_SECONDS",
                    0.01,
                ),
                patch.object(
                    compute_module,
                    "process_delivery_batch",
                    side_effect=block_execution,
                ),
                patch.object(
                    scheduler_module,
                    "_heartbeat",
                    side_effect=observe_lease_loss,
                ),
            ):
                thread = Thread(
                    target=lambda: result.append(
                        run_once(
                            self.database_url,
                            self.storage_root,
                            queue="batch",
                        )
                    )
                )
                thread.start()
                self.assertTrue(execution_started.wait(2))
                with self.app.state.database.session() as session:
                    job = session.get(Job, job_id)
                    original_claim_prefix = job.claim_token[:8]
                    job.claim_token = "replacement-claim"
                    batch = session.get(Batch, batch_id)
                    batch.status = "running"
                    session.commit()
                self.assertTrue(lease_lost.wait(2))
                release_execution.set()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

        self.assertEqual(result, [job_id])
        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            batch = session.get(Batch, batch_id)
            self.assertEqual(job.status, "running")
            self.assertEqual(job.claim_token, "replacement-claim")
            self.assertEqual(batch.status, "running")
        log_output = "\n".join(logs.output)
        self.assertIn(f"queue=batch job_id={job_id}", log_output)
        self.assertIn(f"claim={original_claim_prefix}", log_output)
        self.assertIn("Traceback", log_output)

    def test_successful_finalize_stops_heartbeat_before_terminal_state(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        _batch_id, job_id = self.create_batch([delivery])
        heartbeat_after_terminal = Event()
        original_execute = scheduler_module._execute_compute
        original_heartbeat = scheduler_module._heartbeat

        def delay_after_finalize(*args):
            original_execute(*args)
            time.sleep(0.05)

        def observe_heartbeat(database, current_job_id, claim_token):
            with database.session() as session:
                if session.get(Job, current_job_id).status != "running":
                    heartbeat_after_terminal.set()
            original_heartbeat(database, current_job_id, claim_token)

        with (
            patch.object(lease_module, "LEASE_HEARTBEAT_INTERVAL_SECONDS", 0.005),
            patch.object(
                scheduler_module,
                "_execute_compute",
                side_effect=delay_after_finalize,
            ),
            patch.object(
                scheduler_module,
                "_heartbeat",
                side_effect=observe_heartbeat,
            ),
            patch.object(scheduler_module.LOGGER, "exception") as log_failure,
        ):
            completed_id = run_once(
                self.database_url,
                self.storage_root,
                queue="batch",
            )

        self.assertEqual(completed_id, job_id)
        self.assertFalse(heartbeat_after_terminal.is_set())
        log_failure.assert_not_called()
        with self.app.state.database.session() as session:
            self.assertEqual(session.get(Job, job_id).status, "succeeded")

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




if __name__ == "__main__":
    unittest.main()
