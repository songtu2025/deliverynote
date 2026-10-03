from tests.support.position_drafts import PositionDraftCase
from unittest.mock import patch


from delivery_note.excel_io import read_position_workbook
from delivery_note.input_inspection import write_position_workbook
from delivery_note.web.models import (
    AuditLog,
    InputDraft,
    InputVersion,
)
from delivery_note.web.position_draft_state import DraftConflictError
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_draft_state import list_draft_rows
from delivery_note.web.position_drafts import (
    mutate_draft_row,
    publish_draft,
)


class PositionDraftTests(PositionDraftCase):
    def test_publish_locks_position_versions_in_id_order(self):
        published_path = self.root / "ordered-lock-publish.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            statements: list[str] = []
            original_scalars = session.scalars

            def record_scalars(statement, *args, **kwargs):
                statements.append(str(statement))
                return original_scalars(statement, *args, **kwargs)

            with patch.object(session, "scalars", side_effect=record_scalars):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name="ordered-lock-publish",
                    storage_path=published_path,
                    confirm_warnings=True,
                )

            lock_statement = next(
                statement
                for statement in statements
                if "FROM input_versions" in statement and "FOR UPDATE" in statement
            )
            self.assertIn("ORDER BY input_versions.id", lock_statement)
            session.rollback()

    def test_publish_rejects_a_draft_when_its_base_is_no_longer_active(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            session.commit()
            draft_id = draft.id
            revision = draft.revision

        replacement_path = self.root / "position-v2.xlsx"
        write_position_workbook(replacement_path, self.base_frame)
        with self.database.session() as session:
            session.get(InputVersion, self.version_id).active = False
            replacement = InputVersion(
                kind="position",
                name="position-v2",
                original_name="position-v2.xlsx",
                storage_path=str(replacement_path),
                active=True,
                created_by=self.admin_id,
            )
            session.add(replacement)
            session.commit()
            replacement_id = replacement.id

        published_path = self.root / "position-v3.xlsx"
        with self.database.session() as session:
            draft = session.get(InputDraft, draft_id)
            with self.assertRaisesRegex(DraftConflictError, "当前启用的库位版本已变化"):
                publish_draft(
                    session,
                    draft,
                    revision,
                    self.admin_id,
                    name="position-v3",
                    storage_path=published_path,
                    confirm_warnings=True,
                )
            session.rollback()

        self.assertFalse(published_path.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
        with self.database.session() as session:
            self.assertEqual(session.get(InputDraft, draft_id).status, "editing")
            self.assertTrue(session.get(InputVersion, replacement_id).active)
            self.assertEqual(
                session.query(InputVersion).filter_by(name="position-v3").count(),
                0,
            )

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
