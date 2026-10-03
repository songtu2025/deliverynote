from tests.support.position_drafts import PositionDraftCase


from delivery_note.web.models import (
    AuditLog,
)
from delivery_note.web.position_draft_state import DraftConflictError
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_draft_state import list_draft_rows
from delivery_note.web.position_drafts import (
    mutate_draft_row,
)


class PositionDraftTests(PositionDraftCase):
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

            with self.assertRaises(DraftConflictError):
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

            with self.assertRaises(DraftConflictError):
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

    def test_row_mutations_do_not_create_audit_log_noise(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            added = mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                self.valid_row,
            )
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                dict(self.valid_row, stocking_position="不备货"),
                row_id=added.id,
            )
            mutate_draft_row(
                session,
                draft,
                draft.revision,
                self.admin_id,
                {},
                row_id=added.id,
                delete=True,
            )

            actions = [log.action for log in session.query(AuditLog).all()]
            self.assertEqual(actions, ["create_input_draft"])
