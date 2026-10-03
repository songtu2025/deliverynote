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
    def test_nested_commit_then_outer_rollback_removes_publish_files(self):
        published_path = self.root / "nested-commit-outer-rollback.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="nested-commit-outer-rollback",
                storage_path=published_path,
            )

            with session.begin_nested():
                pass
            session.rollback()

            self.assertFalse(published_path.exists())
            self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
            self.assertEqual(session.query(InputVersion).count(), 1)
            self.assertTrue(session.get(InputVersion, self.version_id).active)

    def test_nested_rollback_then_outer_commit_keeps_version_and_file(self):
        published_path = self.root / "nested-rollback-outer-commit.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            published = publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="nested-rollback-outer-commit",
                storage_path=published_path,
            )

            nested = session.begin_nested()
            nested.rollback()
            session.commit()

            self.assertTrue(published_path.exists())
            self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
            self.assertTrue(session.get(InputVersion, published.id).active)
            self.assertFalse(session.get(InputVersion, self.version_id).active)

    def test_failed_root_commit_then_nested_commit_then_outer_rollback_cleans_files(
        self,
    ):
        published_path = self.root / "failed-root-nested-commit-rollback.xlsx"
        with self.database.session() as session:
            draft = create_or_resume_draft(
                session, self._version(session), self.admin_id
            )
            publish_draft(
                session,
                draft,
                draft.revision,
                self.admin_id,
                name="failed-root-nested-commit-rollback",
                storage_path=published_path,
            )

            def fail_after_promotion(_session):
                self.assertTrue(published_path.exists())
                raise RuntimeError("root commit failed after promotion")

            event.listen(session, "before_commit", fail_after_promotion)
            try:
                with self.assertRaisesRegex(RuntimeError, "root commit failed"):
                    session.commit()
            finally:
                event.remove(session, "before_commit", fail_after_promotion)

            with session.begin_nested():
                pass
            session.rollback()

            self.assertFalse(published_path.exists())
            self.assertEqual(list(self.root.glob(".*.tmp.xlsx")), [])
            versions = session.query(InputVersion).all()
            self.assertEqual(
                [(version.id, version.active) for version in versions],
                [(self.version_id, True)],
            )

    def test_publish_inside_rolled_back_savepoint_is_rejected_before_outer_commit(self):
        self._assert_nested_publish_rejected(
            name="nested-rollback-outer-commit-rejected",
            commit_savepoint=False,
            commit_outer=True,
        )

    def test_publish_inside_committed_savepoint_is_rejected_before_outer_rollback(self):
        self._assert_nested_publish_rejected(
            name="nested-commit-outer-rollback-rejected",
            commit_savepoint=True,
            commit_outer=False,
        )

    def test_publish_inside_committed_savepoint_is_rejected_before_outer_commit(self):
        self._assert_nested_publish_rejected(
            name="nested-commit-outer-commit-rejected",
            commit_savepoint=True,
            commit_outer=True,
        )
