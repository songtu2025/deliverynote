from tests.support.web_api import WebApiCase
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
import pandas as pd


from delivery_note.web.models import (
    InputVersion,
    SelfOperatedBatch,
    SelfOperatedInboundSyncJob,
)


class WebApiTests(WebApiCase):
    def test_self_operated_batch_uses_active_api_inbound_version(self):
        headers = self.login("admin", "admin-pass")
        for kind in ("product", "supplier"):
            response = self.client.post(
                f"/api/input-versions/{kind}",
                headers=headers,
                data={"name": f"{kind}-api-batch", "activate": "true"},
                files={
                    "file": (
                        f"{kind}.xlsx",
                        BytesIO(self.workbook_bytes(kind)),
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)

        inbound_path = self.root / "api-inbound.xlsx"
        inbound_path.write_bytes(self.self_operated_inbound_bytes())
        with self.app.state.database.session() as session:
            version = InputVersion(
                kind="self_operated_inbound",
                name="积加待入库-测试版",
                original_name="积加待入库.xlsx",
                storage_path=str(inbound_path),
                active=True,
                created_by=1,
            )
            session.add(version)
            session.commit()
            inbound_version_id = version.id

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "使用 API 待入库数据的批次"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                )
            },
        )

        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(
            batch["version_ids"]["self_operated_inbound"],
            inbound_version_id,
        )
        self.assertEqual(
            batch["versions"]["self_operated_inbound"]["name"],
            "积加待入库-测试版",
        )
        self.assertEqual(
            batch["inbound_file"]["original_name"],
            "积加待入库.xlsx",
        )

        previous_upload = None
        for filename in ("首次替换.xlsx", "再次替换.xlsx"):
            replaced = self.client.post(
                f"/api/self-operated-batches/{batch['id']}/inbound-file",
                headers=headers,
                files={"file": (filename, BytesIO(self.self_operated_inbound_bytes()))},
            )
            self.assertEqual(replaced.status_code, 200, replaced.text)
            self.assertTrue(inbound_path.is_file(), "不能删除共享 API 版本文件")
            if previous_upload is not None:
                self.assertFalse(previous_upload.exists())
            with self.app.state.database.session() as session:
                profile = session.get(SelfOperatedBatch, batch["id"])
                previous_upload = Path(profile.inbound_storage_path)
            self.assertTrue(previous_upload.is_file())
        downloaded = self.client.get(
            f"/api/input-versions/{inbound_version_id}/download", headers=headers
        )
        self.assertEqual(downloaded.status_code, 200, downloaded.text)

    def test_self_operated_candidate_preview_has_stable_row_numbers(self):
        admin_headers = self.login("admin", "admin-pass")
        candidate_path = self.root / "self-operated-candidate.xlsx"
        workbook = load_workbook(BytesIO(self.self_operated_inbound_bytes()))
        columns = [cell.value for cell in workbook.active[1]]
        second_row = [cell.value for cell in workbook.active[2]]
        second_row[columns.index("SKU")] = "SKU-B"
        second_row[columns.index("供应商")] = None
        workbook.active.append(second_row)
        workbook.save(candidate_path)
        with self.app.state.database.session() as session:
            version = InputVersion(
                kind="self_operated_inbound",
                name="待入库候选版本",
                original_name="self-operated-candidate.xlsx",
                storage_path=str(candidate_path),
                active=False,
                created_by=1,
            )
            session.add(version)
            session.flush()
            job = SelfOperatedInboundSyncJob(
                status="succeeded",
                created_by=1,
                candidate_version_id=version.id,
                issues=[
                    {
                        "severity": "warning",
                        "message": "共享站点数据不能参与正常入库匹配",
                        "order_no": "IN-1",
                        "sku": "SKU-A",
                        "source_site": "AMAZON:SEEKWAY:US",
                        "supplier_code": "GYS-023",
                        "supplier_name": "KuangBiao",
                        "code": "shared_site",
                    }
                ],
            )
            session.add(job)
            session.commit()
            job_id = job.id

        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")
        preview = self.client.get(
            f"/api/self-operated-inbound-sync/{job_id}/preview?limit=100",
            headers=operator_headers,
        )

        self.assertEqual(preview.status_code, 200, preview.text)
        payload = preview.json()
        self.assertEqual(payload["columns"], columns)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["rows"][0]["_row_number"], 1)
        self.assertEqual(payload["rows"][0]["入库单号"], "IN-1")
        self.assertEqual(payload["rows"][0]["SKU"], "SKU-A")
        self.assertEqual(payload["rows"][0]["应收货"], 10)
        self.assertEqual(payload["rows"][1]["_row_number"], 2)
        self.assertEqual(payload["rows"][1]["SKU"], "SKU-B")
        self.assertIsNone(payload["rows"][1]["供应商"])

        limited = self.client.get(
            f"/api/self-operated-inbound-sync/{job_id}/preview?limit=1",
            headers=operator_headers,
        )
        self.assertEqual(limited.status_code, 200, limited.text)
        self.assertEqual(limited.json()["total"], 2)
        self.assertEqual(limited.json()["rows"], payload["rows"][:1])

        issues = self.client.get(
            f"/api/self-operated-inbound-sync/{job_id}/issues",
            headers=operator_headers,
        )
        self.assertEqual(issues.status_code, 200, issues.text)
        issue = issues.json()[0]
        self.assertEqual(issue["warehouse"], "自营仓")
        self.assertEqual(issue["remaining_quantity"], 10)
        self.assertEqual(issue["purchase_code"], "PO-20260801")
        self.assertEqual(issue["related_code"], "LN2608179025")

        download = self.client.get(
            f"/api/self-operated-inbound-sync/{job_id}/issues/download",
            headers=operator_headers,
        )
        self.assertEqual(download.status_code, 200, download.text)
        issue_frame = pd.read_excel(BytesIO(download.content))
        self.assertEqual(issue_frame.loc[0, "入库仓"], "自营仓")
        self.assertEqual(issue_frame.loc[0, "剩余应收货"], 10)
