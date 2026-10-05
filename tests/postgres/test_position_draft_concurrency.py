from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic

import pandas as pd
from sqlalchemy import func, select, text

from delivery_note.inspection.workbooks import write_position_workbook
from delivery_note.migrations.runner import migrate_schema
from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from delivery_note.web.database import Database
from delivery_note.web.models import (
    AuditLog,
    InputDraft,
    InputVersion,
    PositionDraftRow,
)
from delivery_note.web.position_draft_creation import create_or_resume_draft
from tests.support.postgres import PostgreSQLCase


def waits_for_version_lock(database: Database, pid: int) -> bool:
    deadline = monotonic() + 5
    pause = Event()
    while monotonic() < deadline:
        with database.engine.connect() as connection:
            blocked = connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE pid = :pid AND wait_event_type = 'Lock' "
                    "AND query LIKE '%input_versions%')"
                ),
                {"pid": pid},
            )
        if blocked:
            return True
        pause.wait(0.02)
    return False


class PositionDraftConcurrencyTests(PostgreSQLCase):
    def test_two_creators_wait_for_version_lock_and_resume_one_draft(self) -> None:
        migrate_schema(self.database_url)
        database = Database(self.database_url)
        first_ready, second_ready, release = Event(), Event(), Event()
        second_pid: list[int] = []
        try:
            with TemporaryDirectory() as directory:
                path = Path(directory) / "position.xlsx"
                write_position_workbook(
                    path,
                    pd.DataFrame(
                        [["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"]],
                        columns=POSITION_SOURCE_COLUMNS,
                    ),
                )
                with database.session() as session:
                    user, _, versions = self.create_batch(session, "草稿并发测试")
                    version_id, user_id = versions["position"], user.id
                    version = session.get(InputVersion, version_id)
                    assert version is not None
                    version.storage_path = str(path)
                    session.commit()

                def create(first: bool) -> int:
                    with database.session() as session:
                        version = session.get(InputVersion, version_id)
                        assert version is not None
                        if not first:
                            pid = session.scalar(text("SELECT pg_backend_pid()"))
                            assert isinstance(pid, int)
                            second_pid.append(pid)
                            second_ready.set()
                        draft = create_or_resume_draft(session, version, user_id)
                        if first:
                            first_ready.set()
                            if not release.wait(timeout=10):
                                raise TimeoutError("等待释放草稿创建事务超时")
                        session.commit()
                        return draft.id

                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(create, True)
                    try:
                        self.assertTrue(first_ready.wait(timeout=10))
                        second = executor.submit(create, False)
                        self.assertTrue(second_ready.wait(timeout=10))
                        self.assertTrue(
                            waits_for_version_lock(database, second_pid[0]),
                            "第二个创建者必须等待库位版本锁",
                        )
                        self.assertFalse(second.done())
                    finally:
                        release.set()
                    self.assertEqual(
                        first.result(timeout=10), second.result(timeout=10)
                    )

                with database.session() as session:
                    self.assertEqual(
                        session.scalar(select(func.count(InputDraft.id))), 1
                    )
                    self.assertEqual(
                        session.scalar(select(func.count(PositionDraftRow.id))), 1
                    )
                    self.assertEqual(
                        session.scalar(
                            select(func.count(AuditLog.id)).where(
                                AuditLog.action == "create_input_draft"
                            )
                        ),
                        1,
                    )
        finally:
            release.set()
            database.dispose()
