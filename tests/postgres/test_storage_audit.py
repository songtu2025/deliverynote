"""验证审计在真实 PostgreSQL 中只读且采用一致的引用快照。"""

from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from delivery_note.web.models import Batch, BatchFile
from scripts.audit_storage import audit_storage, read_session
from tests.support.postgres import PostgreSQLCase


class StorageAuditPostgresTests(PostgreSQLCase):
    def test_readonly_audit_reports_actual_file_state_and_rejects_writes(self) -> None:
        with self.batch_api("succeeded", file_count=1) as values:
            app, _, _, batch_id, file_ids = values
            root = Path(app.state.storage_root)
            path = root / "source.xlsx"
            path.write_bytes(b"sample")
            with app.state.database.session() as session:
                source = session.get(BatchFile, file_ids[0])
                source.storage_path = str(path)
                name = session.scalar(select(Batch.name).where(Batch.id == batch_id))
                session.commit()
            report = audit_storage(self.database_url, root)
            self.assertEqual(report["status"], "complete")
            self.assertEqual(
                next(
                    entry["category"]
                    for entry in report["entries"]
                    if entry["path"] == "source.xlsx"
                ),
                "normal_reference",
            )
            with read_session(self.database_url) as session:
                self.assertEqual(
                    session.scalar(text("SHOW transaction_read_only")), "on"
                )
                with self.assertRaises(DatabaseError):
                    session.execute(text("UPDATE batches SET name='不可写入'"))
            with app.state.database.session() as session:
                self.assertEqual(
                    session.scalar(select(Batch.name).where(Batch.id == batch_id)), name
                )
            path.unlink()
            self.assertEqual(
                audit_storage(self.database_url, root)["counts"]["missing_reference"], 1
            )

    def test_reference_reads_remain_in_the_same_snapshot(self) -> None:
        with self.batch_api("succeeded", file_count=1) as values:
            app, _, _, _, file_ids = values
            statement = select(BatchFile.storage_path).where(
                BatchFile.id == file_ids[0]
            )
            with read_session(self.database_url) as reader:
                previous = reader.scalar(statement)
                with app.state.database.session() as writer:
                    source = writer.get(BatchFile, file_ids[0])
                    source.storage_path = "/isolated-new-generation.xlsx"
                    writer.commit()
                self.assertEqual(reader.scalar(statement), previous)
                self.assertEqual(
                    reader.scalar(text("SHOW transaction_isolation")), "repeatable read"
                )
            with app.state.database.session() as session:
                self.assertEqual(
                    session.scalar(statement), "/isolated-new-generation.xlsx"
                )
