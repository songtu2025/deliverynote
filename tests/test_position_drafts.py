from tests.support.position_api import PositionApiCase
import unittest
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from delivery_note.web.models import (
    InputDraft,
    InputVersion,
)


































class PositionDraftApiTests(PositionApiCase):



































    def test_publish_commit_failure_rolls_back_database_and_generated_files(self):
        draft = self.create_draft()
        before_files = set((self.storage / "master" / "position").iterdir())

        def fail_publish_commit(session):
            if (
                session.bind is self.app.state.database.engine
                and "position_draft_pending_publish" in session.info
            ):
                raise RuntimeError("publish commit failed")

        event.listen(Session, "before_commit", fail_publish_commit)
        try:
            with self.assertRaisesRegex(RuntimeError, "publish commit failed"):
                self.client.post(
                    f"/api/input-drafts/{draft['id']}/publish",
                    headers=self.admin_headers,
                    json={
                        "revision": draft["revision"],
                        "name": "commit-failure-api",
                        "confirm_warnings": True,
                    },
                )
        finally:
            event.remove(Session, "before_commit", fail_publish_commit)

        with self.app.state.database.session() as session:
            versions = (
                session.query(InputVersion)
                .filter_by(kind="position")
                .order_by(InputVersion.id)
                .all()
            )
            persisted_draft = session.get(InputDraft, draft["id"])
            self.assertEqual(
                [(item.id, item.active) for item in versions],
                [(self.version["id"], True)],
            )
            self.assertEqual(persisted_draft.status, "editing")
            self.assertEqual(persisted_draft.revision, draft["revision"])
        self.assertEqual(
            set((self.storage / "master" / "position").iterdir()),
            before_files,
        )
        self.assertEqual(
            list((self.storage / "master" / "position").glob(".*.tmp.xlsx")),
            [],
        )

    def test_commit_failure_and_integrity_error_explicitly_roll_back(self):
        draft = self.create_draft()
        rollbacks = []

        def fail_commit(session):
            if session.bind is self.app.state.database.engine:
                raise RuntimeError("commit failed")

        def record_rollback(session):
            if session.bind is self.app.state.database.engine:
                rollbacks.append(session)

        event.listen(Session, "before_commit", fail_commit)
        event.listen(Session, "after_rollback", record_rollback)
        try:
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                self.client.post(
                    f"/api/input-drafts/{draft['id']}/rows",
                    headers=self.admin_headers,
                    json={"revision": draft["revision"], **self.valid_row},
                )
        finally:
            event.remove(Session, "before_commit", fail_commit)
            event.remove(Session, "after_rollback", record_rollback)
        self.assertEqual(len(rollbacks), 1)
        self.assertEqual(self.list_rows(draft["id"])["total"], 1)

        rollbacks.clear()
        event.listen(Session, "after_rollback", record_rollback)
        try:
            with patch(
                "delivery_note.web.position_draft_row_routes.mutate_draft_row",
                side_effect=IntegrityError("insert", {}, RuntimeError("duplicate")),
                create=True,
            ):
                conflict = self.client.post(
                    f"/api/input-drafts/{draft['id']}/rows",
                    headers=self.admin_headers,
                    json={"revision": draft["revision"], **self.valid_row},
                )
        finally:
            event.remove(Session, "after_rollback", record_rollback)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["code"], "draft_revision_conflict")
        self.assertEqual(len(rollbacks), 1)


if __name__ == "__main__":
    unittest.main()
