from tests.support.position_drafts import PositionDraftCase
from unittest.mock import patch

import pandas as pd

from delivery_note.input_inspection import write_position_workbook
from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from delivery_note.web.models import (
    AuditLog,
    InputDraft,
    InputVersion,
    PositionDraftRow,
)
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_draft_state import list_draft_rows


class PositionDraftTests(PositionDraftCase):
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
            self.assertEqual(
                session.query(AuditLog).filter_by(action="create_input_draft").count(),
                1,
            )
            self.assertEqual(
                session.query(AuditLog).filter_by(action="resume_input_draft").count(),
                0,
            )

    def test_create_bulk_inserts_initial_rows_without_adding_orm_rows(self):
        self.base_frame = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                ["SEEKWAY:CA", "SKU-B", "MSKU-B", "中尾", "备货"],
                ["SEEKWAY:UK", "SKU-C", "MSKU-C", "长尾", "不备货"],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )
        write_position_workbook(self.base_path, self.base_frame)

        with self.database.session() as session:
            original_add = session.add

            def add_non_row(instance, *args, **kwargs):
                self.assertNotIsInstance(instance, PositionDraftRow)
                return original_add(instance, *args, **kwargs)

            with patch.object(session, "add", side_effect=add_non_row):
                draft = create_or_resume_draft(
                    session,
                    self._version(session),
                    self.admin_id,
                )

            rows = list_draft_rows(session, draft.id)
            self.assertEqual([row.row_order for row in rows], [1, 2, 3])
            self.assertEqual([row.base_row_number for row in rows], [2, 3, 4])
            self.assertEqual(
                [row.change_type for row in rows],
                ["unchanged", "unchanged", "unchanged"],
            )
            self.assertEqual(
                [row.jiaji_sku for row in rows],
                ["SKU-A", "SKU-B", "SKU-C"],
            )

    def test_create_uses_fresh_active_version_instead_of_cached_prelock_state(self):
        replacement_path = self.root / "position-v2-create.xlsx"
        write_position_workbook(replacement_path, self.base_frame)
        with self.database.session() as session:
            stale_version = self._version(session)
            session.execute(
                InputVersion.__table__.update()
                .where(InputVersion.id == self.version_id)
                .values(active=False)
            )
            replacement = InputVersion(
                kind="position",
                name="position-v2-create",
                original_name="position-v2-create.xlsx",
                storage_path=str(replacement_path),
                active=True,
                created_by=self.admin_id,
            )
            session.add(replacement)
            session.flush()

            self.assertTrue(stale_version.active)
            created = create_or_resume_draft(session, stale_version, self.admin_id)

            self.assertEqual(created.base_version_id, replacement.id)

    def test_create_or_resume_locks_versions_before_reading_the_draft(self):
        with self.database.session() as session:
            version = self._version(session)
            calls: list[str] = []
            original_scalar = session.scalar
            original_scalars = session.scalars

            def record_scalar(statement, *args, **kwargs):
                calls.append(str(statement))
                return original_scalar(statement, *args, **kwargs)

            def record_scalars(statement, *args, **kwargs):
                calls.append(str(statement))
                return original_scalars(statement, *args, **kwargs)

            with (
                patch.object(session, "scalar", side_effect=record_scalar),
                patch.object(session, "scalars", side_effect=record_scalars),
            ):
                create_or_resume_draft(session, version, self.admin_id)

            relevant_calls = [
                statement
                for statement in calls
                if "input_versions" in statement or "input_drafts" in statement
            ]
            self.assertIn("input_versions", relevant_calls[0])
            self.assertIn("ORDER BY input_versions.id", relevant_calls[0])
            self.assertIn("input_drafts", relevant_calls[1])

    def test_concurrent_first_create_resumes_committed_winner(self):
        with self.database.session() as session:
            winner = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            session.commit()
            winner_id = winner.id

        with self.database.session() as session:
            original_scalar = session.scalar
            stale_lookup_used = False

            def scalar_with_stale_first_lookup(statement, *args, **kwargs):
                nonlocal stale_lookup_used
                if not stale_lookup_used and "FROM input_drafts" in str(statement):
                    stale_lookup_used = True
                    return None
                return original_scalar(statement, *args, **kwargs)

            with patch.object(
                session,
                "scalar",
                side_effect=scalar_with_stale_first_lookup,
            ):
                resumed = create_or_resume_draft(
                    session, self._version(session), self.admin_id
                )

            self.assertEqual(resumed.id, winner_id)
            self.assertEqual(session.query(InputDraft).count(), 1)
            self.assertEqual(
                session.query(AuditLog).filter_by(action="resume_input_draft").count(),
                0,
            )
