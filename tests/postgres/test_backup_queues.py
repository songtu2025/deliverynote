from pathlib import Path
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.models import Job, PurchaseSyncJob, SelfOperatedInboundSyncJob
from scripts.backup.runtime import BackupConfig
from scripts.backup.services import active_job_count
from tests.support.backup import FakeRunner
from tests.support.postgres import PostgreSQLCase


class PostgreSQLQueueRunner(FakeRunner):
    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine

    def _counts(self, command: tuple[str, ...]) -> str:
        with self.engine.connect() as connection:
            return str(
                connection.execute(text(command[command.index("-c") + 1])).scalar_one()
            )


class BackupQueuePostgreSQLTests(PostgreSQLCase):
    def test_all_actual_queue_tables_use_the_same_active_status_definition(
        self,
    ) -> None:
        migrate_schema(self.database_url)
        database = Database(self.database_url)
        self.addCleanup(database.dispose)
        config = BackupConfig(
            compose_file=Path("compose.yaml"),
            env_file=Path(".env"),
            project_name="test",
            destination=Path("unused-backups"),
            lock_file=Path("unused.lock"),
        )
        with database.session() as session:
            user, batch, _ = self.create_batch(session, "备份队列统计")
            session.add_all(
                [
                    Job(batch_id=batch.id, kind="compute", status="succeeded"),
                    PurchaseSyncJob(created_by=user.id, status="succeeded"),
                    SelfOperatedInboundSyncJob(created_by=user.id, status="succeeded"),
                ]
            )
            session.commit()
        runner = PostgreSQLQueueRunner(cast(Engine, database.engine))
        tables = ("jobs", "purchase_sync_jobs", "self_operated_inbound_sync_jobs")
        for table in tables:
            for status in ("queued", "running", "succeeded", "failed"):
                with self.subTest(table=table, status=status):
                    with database.engine.begin() as connection:
                        for other in tables:
                            connection.execute(
                                text(f"UPDATE {other} SET status='succeeded'")
                            )
                        connection.execute(
                            text(f"UPDATE {table} SET status=:status"),
                            {"status": status},
                        )
                    self.assertEqual(
                        active_job_count(config, runner),
                        int(status in {"queued", "running"}),
                    )
        with database.engine.begin() as connection:
            for table in tables:
                connection.execute(text(f"UPDATE {table} SET status='running'"))
        self.assertEqual(active_job_count(config, runner), 3)
