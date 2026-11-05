from sqlalchemy import select

from delivery_note.web.models import Batch, BatchFile, ExceptionRecord, Job
from tests.support.web_api import WebApiCase


class ExceptionTransferCase(WebApiCase):
    def setUp(self):
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.versions = self.upload_active_versions(self.headers)
        response = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "转交合成批次"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.batch_id = response.json()["id"]
        self.exception_id = self.add_source()

    def add_source(self, supplier_code="GYS-023", sku="SKU-A", order=1):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "succeeded"
            source = BatchFile(
                batch_id=batch.id,
                original_name=(
                    f"261008-{'HaiLang' if supplier_code == 'GYS-024' else 'KuangBiao'}"
                    f"-{order}-交货194箱.xlsx"
                ),
                storage_path="synthetic",
                file_order=order,
                supplier_name="KuangBiao",
                supplier_code=supplier_code,
                delivery_total=20,
                import_total=12,
                manual_total=8,
            )
            session.add(source)
            session.flush()
            record = ExceptionRecord(
                batch_file_id=source.id,
                sku=sku,
                original_site="US",
                full_site="AMAZON:SEEKWAY:US",
                delivery_quantity=20,
                allocated_quantity=12,
                manual_quantity=8,
                reason="超出允许超收量",
                status="pending",
            )
            session.add(record)
            session.commit()
            return record.id

    def transfer(self, quantity=8, **changes):
        item = {
            "exception_id": self.exception_id,
            "quantity": quantity,
            "full_site": "AMAZON:SEEKWAY:US",
            **changes,
        }
        return self.client.post(
            f"/api/batches/{self.batch_id}/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={"items": [item]},
        )

    def records(self):
        return self.client.get(
            f"/api/batches/{self.batch_id}/exceptions", headers=self.headers
        ).json()

    def complete_export(self):
        with self.app.state.database.session() as session:
            export = session.scalar(
                select(Job).where(Job.batch_id == self.batch_id, Job.kind == "export")
            )
            self.assertEqual(export.status, "queued")
            export.status = "succeeded"
            session.commit()
