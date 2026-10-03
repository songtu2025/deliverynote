from tests.support.position_drafts import PositionDraftCase

from sqlalchemy import event

from delivery_note.web.models import (
    InputVersion,
)
from delivery_note.web.position_draft_creation import create_or_resume_draft
from delivery_note.web.position_drafts import (
    publish_draft,
)


class PositionDraftTests(PositionDraftCase):
    def test_publish_rollback_removes_generated_files_and_version(self):
        published_path = self.root / "rolled-back.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="rolled-back-version",
                storage_path=published_path,
            )
            session.rollback()

            self.assertFalse(published_path.exists())
            self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
            self.assertEqual(session.query(InputVersion).count(), 1)
            self.assertTrue(session.get(InputVersion, self.version_id).active)

    def test_publish_commit_failure_then_rollback_removes_generated_files(self):
        published_path = self.root / "commit-failure.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="commit-failure-version",
                storage_path=published_path,
            )

            def fail_before_commit(_session):
                raise RuntimeError("commit failed")

            event.listen(session, "before_commit", fail_before_commit)
            try:
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    session.commit()
            finally:
                event.remove(session, "before_commit", fail_before_commit)
            session.rollback()

            self.assertFalse(published_path.exists())
            self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
            self.assertEqual(session.query(InputVersion).count(), 1)
            self.assertTrue(session.get(InputVersion, self.version_id).active)

    def test_publish_then_session_close_removes_temporary_file(self):
        published_path = self.root / "close-without-commit.xlsx"
        session = self.database.SessionLocal()
        try:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="close-without-commit",
                storage_path=published_path,
            )
        finally:
            session.close()

        self.assertFalse(published_path.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
        with self.database.session() as verification_session:
            self.assertEqual(verification_session.query(InputVersion).count(), 1)
            self.assertTrue(
                verification_session.get(InputVersion, self.version_id).active
            )

    def test_commit_hook_failure_then_close_removes_promoted_target(self):
        published_path = self.root / "commit-failure-close.xlsx"
        session = self.database.SessionLocal()
        draft = create_or_resume_draft(session, self._version(session), self.admin_id)
        publish_draft(
            session,
            draft,
            draft.revision,
            self.admin_id,
            name="commit-failure-close",
            storage_path=published_path,
        )

        def fail_after_promotion(_session):
            self.assertTrue(published_path.exists())
            raise RuntimeError("commit failed after promotion")

        event.listen(session, "before_commit", fail_after_promotion)
        try:
            with self.assertRaisesRegex(RuntimeError, "after promotion"):
                session.commit()
        finally:
            event.remove(session, "before_commit", fail_after_promotion)
            session.close()

        self.assertFalse(published_path.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
        with self.database.session() as verification_session:
            self.assertEqual(verification_session.query(InputVersion).count(), 1)
            self.assertTrue(
                verification_session.get(InputVersion, self.version_id).active
            )
