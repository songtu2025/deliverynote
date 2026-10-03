from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from delivery_note.inspection.workbooks import write_position_workbook
from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from delivery_note.web.database import Database, sqlite_url
from delivery_note.web.models import (
    InputVersion,
    User,
)
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_draft_state import list_draft_rows
from delivery_note.web.position_drafts import (
    mutate_draft_row,
    publish_draft,
)


class PositionDraftCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = Database(sqlite_url(self.root / "test.db"))
        self.database.create_schema()
        self.base_path = self.root / "position-v1.xlsx"
        self.base_frame = pd.DataFrame(
            [["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"]],
            columns=POSITION_SOURCE_COLUMNS,
        )
        write_position_workbook(self.base_path, self.base_frame)
        with self.database.session() as session:
            admin = User(
                username="admin",
                password_hash="unused",
                role="admin",
            )
            session.add(admin)
            session.flush()
            version = InputVersion(
                kind="position",
                name="position-v1",
                original_name="position-v1.xlsx",
                storage_path=str(self.base_path),
                active=True,
                created_by=admin.id,
            )
            session.add(version)
            session.commit()
            self.admin_id = admin.id
            self.version_id = version.id
        self.valid_row = {
            "store_site": "SEEKWAY:CA",
            "jiaji_sku": "SKU-B",
            "msku": "MSKU-B",
            "scale_position": "中尾",
            "stocking_position": "备货",
        }

    def tearDown(self):
        self.database.dispose()
        self.temporary_directory.cleanup()

    def _version(self, session):
        return session.get(InputVersion, self.version_id)

    def _modify_original(self, session, draft, stocking_position="不备货"):
        original = list_draft_rows(session, draft.id)[0]
        values = {
            "store_site": original.store_site,
            "jiaji_sku": original.jiaji_sku,
            "msku": original.msku,
            "scale_position": original.scale_position,
            "stocking_position": stocking_position,
        }
        mutate_draft_row(
            session,
            draft,
            draft.revision,
            self.admin_id,
            values,
            row_id=original.id,
        )
        return original

    def _assert_nested_publish_rejected(
        self,
        *,
        name: str,
        commit_savepoint: bool,
        commit_outer: bool,
    ):
        published_path = self.root / f"{name}.xlsx"
        session = self.database.SessionLocal()
        try:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            nested = session.begin_nested()
            with self.assertRaisesRegex(ValueError, "不能在嵌套事务中发布"):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name=name,
                    storage_path=published_path,
                )
            if commit_savepoint:
                nested.commit()
            else:
                nested.rollback()
            if commit_outer:
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()

        self.assertFalse(published_path.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
        with self.database.session() as verification_session:
            versions = verification_session.query(InputVersion).all()
            self.assertEqual(
                [(version.id, version.active) for version in versions],
                [(self.version_id, True)],
            )
