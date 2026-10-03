from tests.support.position_drafts import PositionDraftCase
from pathlib import Path
from unittest.mock import patch


from delivery_note.web.models import (
    InputVersion,
)
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_drafts import (
    publish_draft,
)


class PositionDraftTests(PositionDraftCase):
    def test_publish_rejects_registered_version_path_without_overwriting_it(self):
        original_bytes = self.base_path.read_bytes()
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            self._modify_original(session, draft)

            with self.assertRaisesRegex(ValueError, "正式版本"):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name="unsafe-version",
                    storage_path=self.base_path,
                )

            self.assertEqual(self.base_path.read_bytes(), original_bytes)
            self.assertEqual(session.query(InputVersion).count(), 1)
            self.assertEqual(draft.status, "editing")

    def test_publish_rejects_resolved_alias_of_registered_version_path(self):
        original_bytes = self.base_path.read_bytes()
        alias_path = self.root / "position-alias.xlsx"
        alias_path.symlink_to(self.base_path)
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            self._modify_original(session, draft)

            with self.assertRaisesRegex(ValueError, "正式版本"):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name="alias-version",
                    storage_path=alias_path,
                )

            self.assertEqual(self.base_path.read_bytes(), original_bytes)
            self.assertTrue(alias_path.is_symlink())
            self.assertEqual(session.query(InputVersion).count(), 1)

    def test_publish_rejects_existing_unregistered_destination(self):
        existing_path = self.root / "unregistered.xlsx"
        existing_path.write_bytes(b"keep-me")
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )

            with self.assertRaisesRegex(ValueError, "目标文件已存在"):
                publish_draft(
                    session,
                    draft,
                    draft.revision,
                    self.admin_id,
                    name="existing-version",
                    storage_path=existing_path,
                )

            self.assertEqual(existing_path.read_bytes(), b"keep-me")
            self.assertEqual(session.query(InputVersion).count(), 1)

    def test_publish_writer_failure_removes_partial_temporary_file(self):
        published_path = self.root / "writer-failure.xlsx"

        def fail_after_partial_write(path, _frame):
            Path(path).write_bytes(b"partial")
            raise OSError("writer failed")

        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )

            with patch(
                "delivery_note.web.position_drafts.write_position_workbook",
                side_effect=fail_after_partial_write,
            ):
                with self.assertRaisesRegex(OSError, "writer failed"):
                    publish_draft(
                        session,
                        draft,
                        draft.revision,
                        self.admin_id,
                        name="writer-failure",
                        storage_path=published_path,
                    )

            self.assertFalse(published_path.exists())
            self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
            self.assertEqual(session.query(InputVersion).count(), 1)
            self.assertEqual(draft.status, "editing")
