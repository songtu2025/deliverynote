from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from delivery_note.excel_io import read_position_workbook
from delivery_note.input_inspection import write_position_workbook
from delivery_note.pipeline import POSITION_SOURCE_COLUMNS
from delivery_note.web.database import Database, sqlite_url
from delivery_note.web.models import AuditLog, InputVersion, User
from delivery_note.web.position_drafts import (
    DraftConflict,
    create_or_resume_draft,
    discard_draft,
    list_draft_rows,
    mutate_draft_row,
    publish_draft,
    replace_draft_from_frame,
    validate_draft,
)


class PositionDraftTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = Database(sqlite_url(self.root / "test.db"))
        self.database.create_schema()
        self.base_path = self.root / "position-v1.xlsx"
        self.base_frame = pd.DataFrame(
            [["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货", 90]],
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
            "ordered_days": "60",
        }

    def tearDown(self):
        self.database.dispose()
        self.temporary_directory.cleanup()

    def _version(self, session):
        return session.get(InputVersion, self.version_id)

    def test_create_or_resume_copies_active_version_once(self):
        with self.database.session() as session:
            created = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            resumed = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            rows = list_draft_rows(session, created.id)

            self.assertEqual(resumed.id, created.id)
            self.assertEqual(created.revision, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].base_row_number, 2)
            self.assertEqual(rows[0].change_type, "unchanged")
            self.assertFalse(rows[0].deleted)
            self.assertEqual(rows[0].ordered_days, "90")
            self.assertEqual(
                session.query(AuditLog).filter_by(action="create_input_draft").count(),
                1,
            )

    def test_stale_revision_is_rejected(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            original_revision = draft.revision
            mutate_draft_row(
                session,
                draft,
                original_revision,
                self.admin_id,
                self.valid_row,
            )

            with self.assertRaises(DraftConflict):
                mutate_draft_row(
                    session,
                    draft,
                    original_revision,
                    self.admin_id,
                    self.valid_row,
                )

    def test_concurrent_session_with_stale_revision_is_rejected(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            session.commit()
            draft_id = draft.id

        first_session = self.database.SessionLocal()
        stale_session = self.database.SessionLocal()
        try:
            first_draft = first_session.get(type(draft), draft_id)
            stale_draft = stale_session.get(type(draft), draft_id)
            mutate_draft_row(
                first_session,
                first_draft,
                1,
                self.admin_id,
                self.valid_row,
            )
            first_session.commit()

            with self.assertRaises(DraftConflict):
                mutate_draft_row(
                    stale_session,
                    stale_draft,
                    1,
                    self.admin_id,
                    self.valid_row,
                )
        finally:
            stale_session.rollback()
            stale_session.close()
            first_session.close()

    def test_original_rows_track_changes_and_added_rows_delete_physically(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            original = list_draft_rows(session, draft.id)[0]
            changed = {
                "store_site": original.store_site,
                "jiaji_sku": original.jiaji_sku,
                "msku": original.msku,
                "scale_position": original.scale_position,
                "stocking_position": "不备货",
                "ordered_days": original.ordered_days,
            }

            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                changed,
                row_id=original.id,
            )
            self.assertEqual(original.change_type, "modified")

            original_values = {
                "store_site": "SEEKWAY:US",
                "jiaji_sku": "SKU-A",
                "msku": "MSKU-A",
                "scale_position": "短尾",
                "stocking_position": "备货",
                "ordered_days": "90",
            }
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                original_values,
                row_id=original.id,
            )
            self.assertEqual(original.change_type, "unchanged")

            added = mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                self.valid_row,
            )
            self.assertEqual(added.change_type, "added")
            self.assertIsNone(added.base_row_number)

            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                {},
                row_id=added.id,
                delete=True,
            )
            self.assertNotIn(
                added.id,
                [row.id for row in list_draft_rows(session, draft.id)],
            )

            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                {},
                row_id=original.id,
                delete=True,
            )
            self.assertTrue(original.deleted)
            self.assertEqual(original.change_type, "deleted")

    def test_replace_preserves_base_identity_and_reports_diff(self):
        candidate = pd.DataFrame(
            [["SEEKWAY:CA", "SKU-B", "MSKU-B", "中尾", "备货", 60]],
            columns=POSITION_SOURCE_COLUMNS,
        )
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            diff = replace_draft_from_frame(
                session,
                draft,
                draft.revision,
                self.admin_id,
                candidate,
            )
            rows = list_draft_rows(session, draft.id)

            self.assertEqual(
                diff,
                {"added": 1, "modified": 0, "deleted": 1, "unchanged": 0},
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].change_type, "added")
            self.assertIsNone(rows[0].base_row_number)
            self.assertEqual(rows[1].change_type, "deleted")
            self.assertEqual(rows[1].base_row_number, 2)
            self.assertTrue(rows[1].deleted)
            self.assertEqual(validate_draft(session, draft), [])

    def test_validation_excludes_soft_deleted_rows(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            original = list_draft_rows(session, draft.id)[0]
            invalid_row = dict(self.valid_row, store_site="")
            invalid = mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                invalid_row,
            )
            self.assertIn(
                "empty_site",
                {issue["code"] for issue in validate_draft(session, draft)},
            )

            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                {},
                row_id=invalid.id,
                delete=True,
            )
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                {},
                row_id=original.id,
                delete=True,
            )
            self.assertEqual(validate_draft(session, draft), [])

    def test_publish_creates_new_active_version_without_overwriting_base(self):
        published_path = self.root / "position-v2.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            original = list_draft_rows(session, draft.id)[0]
            values = {
                "store_site": original.store_site,
                "jiaji_sku": original.jiaji_sku,
                "msku": original.msku,
                "scale_position": original.scale_position,
                "stocking_position": "不备货",
                "ordered_days": original.ordered_days,
            }
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                values,
                row_id=original.id,
            )
            published = publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="position-v2",
                storage_path=published_path,
            )
            session.commit()

            self.assertNotEqual(published.id, self.version_id)
            self.assertTrue(published.active)
            self.assertEqual(draft.status, "published")
            self.assertFalse(session.get(InputVersion, self.version_id).active)
            self.assertEqual(
                read_position_workbook(self.base_path).iloc[0]["备货定位"],
                "备货",
            )
            self.assertEqual(
                read_position_workbook(published_path).iloc[0]["备货定位"],
                "不备货",
            )
            self.assertEqual(
                session.query(AuditLog).filter_by(action="publish_input_draft").count(),
                1,
            )

    def test_publish_rejects_errors_and_requires_warning_confirmation(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            original = list_draft_rows(session, draft.id)[0]
            warning_values = {
                "store_site": original.store_site,
                "jiaji_sku": original.jiaji_sku,
                "msku": original.msku,
                "scale_position": "未知",
                "stocking_position": original.stocking_position,
                "ordered_days": original.ordered_days,
            }
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                warning_values,
                row_id=original.id,
            )
            with self.assertRaisesRegex(ValueError, "确认警告"):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name="warning-version",
                    storage_path=self.root / "warning.xlsx",
                )

            error_values = dict(warning_values, store_site="")
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                error_values,
                row_id=original.id,
            )
            with self.assertRaisesRegex(ValueError, "错误"):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name="error-version",
                    storage_path=self.root / "error.xlsx",
                    confirm_warnings=True,
                )

    def test_discard_marks_draft_and_prevents_further_mutation(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            discarded = discard_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
            )

            self.assertEqual(discarded.status, "discarded")
            with self.assertRaises(DraftConflict):
                mutate_draft_row(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    self.valid_row,
                )


if __name__ == "__main__":
    unittest.main()
