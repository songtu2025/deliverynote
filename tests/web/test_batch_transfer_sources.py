from sqlalchemy import event

from delivery_note.web.models import Batch, BatchFile, ExceptionTransfer
from tests.support.exception_transfers import ExceptionTransferCase


class BatchTransferSourcesTests(ExceptionTransferCase):
    def test_multiple_origin_batches_remain_separate(self):
        target_id = self.transfer(1).json()["id"]
        target = self.client.get(
            f"/api/batches/{target_id}", headers=self.headers
        ).json()
        first_source_id = self.batch_id
        other = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "另一个来源批次"},
        ).json()
        self.batch_id = other["id"]
        other_exception = self.add_source()
        with self.app.state.database.session() as session:
            session.add(
                ExceptionTransfer(
                    exception_id=other_exception,
                    quantity=2,
                    full_site="AMAZON:SEEKWAY:US",
                    target_batch_id=target_id,
                    target_file_id=target["files"][0]["id"],
                    created_by=1,
                )
            )
            session.commit()
        detail = self.client.get(
            f"/api/batches/{target_id}", headers=self.headers
        ).json()
        self.assertEqual(
            [
                (source["batch_id"], source["quantity"])
                for source in detail["transfer_sources"]
            ],
            [(first_source_id, 1), (other["id"], 2)],
        )

    def test_detail_groups_partial_transfers_and_deduplicates_target_files(self):
        target = self.transfer(2).json()
        target_id = target["id"]
        target_detail = self.client.get(
            f"/api/batches/{target_id}", headers=self.headers
        ).json()
        target_file_id = target_detail["files"][0]["id"]
        another_exception = self.add_source(order=2)
        with self.app.state.database.session() as session:
            second_file = BatchFile(
                batch_id=target_id,
                original_name="另一目标.xlsx",
                storage_path="unused",
                file_order=2,
            )
            session.add(second_file)
            session.flush()
            for exception_id, quantity, file_id in (
                (self.exception_id, 1, target_file_id),
                (another_exception, 3, second_file.id),
            ):
                session.add(
                    ExceptionTransfer(
                        exception_id=exception_id,
                        quantity=quantity,
                        full_site="AMAZON:SEEKWAY:US",
                        target_batch_id=target_id,
                        target_file_id=file_id,
                        created_by=1,
                    )
                )
            second_file_id = second_file.id
            source_name = session.get(Batch, self.batch_id).name
            session.commit()
        detail = self.client.get(
            f"/api/batches/{target_id}", headers=self.headers
        ).json()
        self.assertEqual(
            detail["transfer_sources"],
            [
                {
                    "batch_id": self.batch_id,
                    "batch_name": source_name,
                    "record_count": 3,
                    "quantity": 6,
                    "file_ids": [target_file_id, second_file_id],
                }
            ],
        )

    def test_plain_delivery_has_no_sources_and_list_does_not_query_transfers(self):
        response = self.client.post(
            "/api/batches", headers=self.headers, json={"name": "普通合成批次"}
        )
        self.assertEqual(response.json()["transfer_sources"], [])
        batch_id = response.json()["id"]
        detail = self.client.get(f"/api/batches/{batch_id}", headers=self.headers)
        self.assertEqual(detail.json()["transfer_sources"], [])
        queries = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            queries.append(statement)

        engine = self.app.state.database.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            listing = self.client.get("/api/batches?limit=10", headers=self.headers)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertFalse(
            any("exception_transfers" in statement for statement in queries)
        )
        self.assertTrue(
            all("transfer_sources" not in item for item in listing.json()["items"])
        )
