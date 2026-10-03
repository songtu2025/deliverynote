from tests.support.position_drafts import PositionDraftCase

import pandas as pd

from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from delivery_note.web.models import (
    AuditLog,
)
from delivery_note.web.position_draft_state import DraftConflictError
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_draft_state import list_draft_rows, validate_draft
from delivery_note.web.position_drafts import (
    discard_draft,
    mutate_draft_row,
)
from delivery_note.web.position_draft_replacement import replace_draft_from_frame


class PositionDraftTests(PositionDraftCase):
    def test_replace_preserves_base_identity_and_reports_diff(self):
        candidate = pd.DataFrame(
            [["SEEKWAY:CA", "SKU-B", "MSKU-B", "中尾", "备货"]],
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
            actions = [log.action for log in session.query(AuditLog).all()]
            self.assertIn("import_input_draft", actions)
            self.assertNotIn("replace_input_draft", actions)

    def test_replace_diff_is_relative_to_current_draft(self):
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            original = self._modify_original(session, draft)
            candidate = pd.DataFrame(
                [
                    [
                        original.store_site,
                        original.jiaji_sku,
                        original.msku,
                        original.scale_position,
                        original.stocking_position,
                    ]
                ],
                columns=POSITION_SOURCE_COLUMNS,
            )

            diff = replace_draft_from_frame(
                session,
                draft,
                draft.revision,
                self.admin_id,
                candidate,
            )

            self.assertEqual(
                diff,
                {"added": 0, "modified": 0, "deleted": 0, "unchanged": 1},
            )
            replaced = list_draft_rows(session, draft.id)[0]
            self.assertEqual(replaced.change_type, "modified")

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
            remaining_issues = validate_draft(session, draft)
            self.assertFalse(
                any(issue["severity"] == "error" for issue in remaining_issues)
            )
            self.assertEqual(
                {issue["code"] for issue in remaining_issues},
                {"row_count_cleared", "sites_cleared", "skus_cleared"},
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
            with self.assertRaises(DraftConflictError):
                mutate_draft_row(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    self.valid_row,
                )
