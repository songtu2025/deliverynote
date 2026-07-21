from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from delivery_note.excel_io import read_position_workbook
from delivery_note.input_inspection import write_position_workbook
from delivery_note.pipeline import POSITION_SOURCE_COLUMNS
from delivery_note.web.api import create_app
from delivery_note.web.database import Database, sqlite_url
from delivery_note.web.models import (
    AuditLog,
    Batch,
    InputDraft,
    InputVersion,
    User,
)
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
from tests.asgi_client import SyncASGIClient


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

    def _modify_original(self, session, draft, stocking_position="不备货"):
        original = list_draft_rows(session, draft.id)[0]
        values = {
            "store_site": original.store_site,
            "jiaji_sku": original.jiaji_sku,
            "msku": original.msku,
            "scale_position": original.scale_position,
            "stocking_position": stocking_position,
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
            self.assertEqual(
                session.query(AuditLog).filter_by(action="resume_input_draft").count(),
                0,
            )

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
                        original.ordered_days,
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
                dict(self.valid_row, ordered_days="61"),
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
        draft = create_or_resume_draft(
            session, self._version(session), self.admin_id
        )
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

    def test_failed_root_commit_then_nested_commit_then_outer_rollback_cleans_files(self):
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


class PositionDraftApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.storage = self.root / "storage"
        self.app = create_app(
            database_url=sqlite_url(self.root / "api.db"),
            storage_root=self.storage,
            bootstrap_admin=("admin", "admin-pass"),
        )
        self.client = SyncASGIClient(self.app)
        self.admin_headers = self.login("admin", "admin-pass")
        operator = self.client.post(
            "/api/users",
            headers=self.admin_headers,
            json={
                "username": "operator",
                "password": "operator-pass",
                "role": "operator",
            },
        )
        self.assertEqual(operator.status_code, 201, operator.text)
        self.operator_headers = self.login("operator", "operator-pass")
        self.version = self.upload_position()
        self.valid_row = {
            "store_site": "SEEKWAY:CA",
            "jiaji_sku": "SKU-B",
            "msku": "MSKU-B",
            "scale_position": "中尾",
            "stocking_position": "备货",
            "ordered_days": "60",
        }

    def tearDown(self):
        self.client.close()
        self.app.state.database.dispose()
        self.temporary_directory.cleanup()

    def login(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    @staticmethod
    def position_bytes(rows: list[list] | None = None) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "MSKU_视图"
        sheet.append(POSITION_SOURCE_COLUMNS)
        if rows is None:
            rows = [["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货", 90]]
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def upload_position(self, name: str = "position-v1") -> dict:
        response = self.client.post(
            "/api/input-versions/position",
            headers=self.admin_headers,
            data={"name": name, "activate": "true"},
            files={
                "file": (
                    f"{name}.xlsx",
                    BytesIO(self.position_bytes()),
                )
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_draft(self) -> dict:
        response = self.client.post(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        )
        self.assertIn(response.status_code, {200, 201}, response.text)
        return response.json()

    def list_rows(self, draft_id: int, **params) -> dict:
        response = self.client.get(
            f"/api/input-drafts/{draft_id}/rows",
            headers=self.admin_headers,
            params=params,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_version_summary_preview_and_download(self):
        version_id = self.version["id"]
        summary = self.client.get(
            f"/api/input-versions/{version_id}/summary",
            headers=self.admin_headers,
        )
        preview = self.client.get(
            f"/api/input-versions/{version_id}/preview?limit=20",
            headers=self.admin_headers,
        )
        download = self.client.get(
            f"/api/input-versions/{version_id}/download",
            headers=self.admin_headers,
        )

        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["metrics"]["sites"], 1)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["rows"][0]["积加SKU"], "SKU-A")
        self.assertEqual(preview.json()["total"], 1)
        self.assertEqual(download.status_code, 200, download.text)
        self.assertIn("position-v1.xlsx", download.headers["content-disposition"])
        self.assertGreater(len(download.content), 0)

        for query in ("offset=-1", "limit=0", "limit=201"):
            invalid = self.client.get(
                f"/api/input-versions/{version_id}/preview?{query}",
                headers=self.admin_headers,
            )
            self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_shared_upload_limit_accepts_boundary_and_rejects_overflow_without_files(self):
        payload = self.position_bytes()
        self.app.state.max_upload_bytes = len(payload)

        exact_version = self.client.post(
            "/api/input-versions/position",
            headers=self.admin_headers,
            data={"name": "position-limit-exact", "activate": "false"},
            files={"file": ("exact.xlsx", BytesIO(payload))},
        )
        self.assertEqual(exact_version.status_code, 201, exact_version.text)
        master_files = set((self.storage / "master" / "position").iterdir())
        oversized_version = self.client.post(
            "/api/input-versions/position",
            headers=self.admin_headers,
            data={"name": "position-limit-over", "activate": "false"},
            files={"file": ("over.xlsx", BytesIO(payload + b"x"))},
        )
        self.assertEqual(oversized_version.status_code, 413, oversized_version.text)
        self.assertEqual(
            set((self.storage / "master" / "position").iterdir()),
            master_files,
        )

        draft = self.create_draft()
        exact_import = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("exact.xlsx", BytesIO(payload))},
        )
        self.assertEqual(exact_import.status_code, 200, exact_import.text)
        import_files = set(
            (self.storage / "temporary" / "position-imports").iterdir()
        )
        oversized_import = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("over.xlsx", BytesIO(payload + b"x"))},
        )
        self.assertEqual(oversized_import.status_code, 413, oversized_import.text)
        self.assertEqual(
            set((self.storage / "temporary" / "position-imports").iterdir()),
            import_files,
        )

        with self.app.state.database.session() as session:
            admin = session.query(User).filter_by(username="admin").one()
            batch = Batch(
                name="upload-limit",
                created_by=admin.id,
                purchase_version_id=self.version["id"],
                product_version_id=self.version["id"],
                supplier_version_id=self.version["id"],
                position_version_id=self.version["id"],
                template_version_id=self.version["id"],
            )
            session.add(batch)
            session.commit()
            batch_id = batch.id
        exact_batch = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=self.admin_headers,
            files={"file": ("exact.xlsx", BytesIO(payload))},
        )
        self.assertEqual(exact_batch.status_code, 201, exact_batch.text)
        batch_files = set(
            (self.storage / "batches" / str(batch_id) / "inputs").iterdir()
        )
        oversized_batch = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=self.admin_headers,
            files={"file": ("over.xlsx", BytesIO(payload + b"x"))},
        )
        self.assertEqual(oversized_batch.status_code, 413, oversized_batch.text)
        self.assertEqual(
            set((self.storage / "batches" / str(batch_id) / "inputs").iterdir()),
            batch_files,
        )

    def test_missing_inspection_and_draft_resources_return_404(self):
        for suffix in ("summary", "preview", "download"):
            response = self.client.get(
                f"/api/input-versions/999/{suffix}",
                headers=self.admin_headers,
            )
            self.assertEqual(response.status_code, 404, response.text)

        no_draft = self.client.get(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        )
        self.assertEqual(no_draft.status_code, 404, no_draft.text)

        missing_requests = (
            ("GET", "/api/input-drafts/999/rows", {}),
            ("POST", "/api/input-drafts/999/rows", {"json": {"revision": 1, **self.valid_row}}),
            ("PUT", "/api/input-drafts/999/rows/999", {"json": {"revision": 1, **self.valid_row}}),
            ("DELETE", "/api/input-drafts/999/rows/999", {"json": {"revision": 1}}),
            ("POST", "/api/input-drafts/999/rows/bulk-delete", {"json": {"revision": 1, "row_ids": [999]}}),
            ("POST", "/api/input-drafts/999/import-apply", {"json": {"revision": 1, "token": "missing"}}),
            ("GET", "/api/input-drafts/999/download", {}),
            ("POST", "/api/input-drafts/999/validate", {}),
            ("POST", "/api/input-drafts/999/publish", {"json": {"revision": 1, "name": "missing", "confirm_warnings": True}}),
            ("POST", "/api/input-drafts/999/discard", {"json": {"revision": 1}}),
        )
        for method, url, kwargs in missing_requests:
            response = self.client.request(
                method,
                url,
                headers=self.admin_headers,
                **kwargs,
            )
            self.assertEqual(response.status_code, 404, f"{url}: {response.text}")

        missing_import = self.client.post(
            "/api/input-drafts/999/import-preview",
            headers=self.admin_headers,
            data={"revision": "1"},
            files={"file": ("position.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(missing_import.status_code, 404, missing_import.text)

    def test_all_inspection_and_draft_routes_require_admin(self):
        draft = self.create_draft()
        row_id = self.list_rows(draft["id"])["rows"][0]["id"]
        forbidden_requests = (
            ("GET", f"/api/input-versions/{self.version['id']}/summary", {}),
            ("GET", f"/api/input-versions/{self.version['id']}/preview", {}),
            ("GET", f"/api/input-versions/{self.version['id']}/download", {}),
            ("POST", "/api/input-drafts/position", {}),
            ("GET", "/api/input-drafts/position", {}),
            ("GET", f"/api/input-drafts/{draft['id']}/rows", {}),
            ("POST", f"/api/input-drafts/{draft['id']}/rows", {"json": {"revision": draft["revision"], **self.valid_row}}),
            ("PUT", f"/api/input-drafts/{draft['id']}/rows/{row_id}", {"json": {"revision": draft["revision"], **self.valid_row}}),
            ("DELETE", f"/api/input-drafts/{draft['id']}/rows/{row_id}", {"json": {"revision": draft["revision"]}}),
            ("POST", f"/api/input-drafts/{draft['id']}/rows/bulk-delete", {"json": {"revision": draft["revision"], "row_ids": [row_id]}}),
            ("POST", f"/api/input-drafts/{draft['id']}/import-apply", {"json": {"revision": draft["revision"], "token": "missing"}}),
            ("GET", f"/api/input-drafts/{draft['id']}/download", {}),
            ("POST", f"/api/input-drafts/{draft['id']}/validate", {}),
            ("POST", f"/api/input-drafts/{draft['id']}/publish", {"json": {"revision": draft["revision"], "name": "forbidden", "confirm_warnings": True}}),
            ("POST", f"/api/input-drafts/{draft['id']}/discard", {"json": {"revision": draft["revision"]}}),
        )
        for method, url, kwargs in forbidden_requests:
            response = self.client.request(
                method,
                url,
                headers=self.operator_headers,
                **kwargs,
            )
            self.assertEqual(response.status_code, 403, f"{url}: {response.text}")

        forbidden_import = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.operator_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("position.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(forbidden_import.status_code, 403, forbidden_import.text)

    def test_draft_persists_across_requests_logout_and_relogin(self):
        created = self.create_draft()
        resumed = self.create_draft()
        self.assertEqual(resumed["id"], created["id"])
        self.assertEqual(resumed["revision"], created["revision"])

        logout = self.client.post(
            "/api/auth/logout",
            headers=self.admin_headers,
        )
        self.assertEqual(logout.status_code, 204, logout.text)
        self.admin_headers = self.login("admin", "admin-pass")
        persisted = self.client.get(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        )
        self.assertEqual(persisted.status_code, 200, persisted.text)
        self.assertEqual(persisted.json()["id"], created["id"])
        self.assertEqual(persisted.json()["row_count"], 1)
        self.assertEqual(
            persisted.json()["diff"],
            {"added": 0, "modified": 0, "deleted": 0, "unchanged": 1},
        )

    def test_draft_and_validate_diff_tracks_edit_restore_add_and_soft_delete(self):
        draft = self.create_draft()
        original = self.list_rows(draft["id"])["rows"][0]
        modified_values = {
            "store_site": original["store_site"],
            "jiaji_sku": original["jiaji_sku"],
            "msku": original["msku"],
            "scale_position": original["scale_position"],
            "stocking_position": "不备货",
            "ordered_days": original["ordered_days"],
        }
        modified = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/{original['id']}",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **modified_values},
        ).json()
        current = self.client.get(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        ).json()
        self.assertEqual(
            current["diff"],
            {"added": 0, "modified": 1, "deleted": 0, "unchanged": 0},
        )
        validation = self.client.post(
            f"/api/input-drafts/{draft['id']}/validate",
            headers=self.admin_headers,
        ).json()
        self.assertEqual(validation["diff"], current["diff"])

        restored = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/{original['id']}",
            headers=self.admin_headers,
            json={
                "revision": modified["revision"],
                **dict(modified_values, stocking_position="备货"),
            },
        ).json()
        self.assertEqual(
            self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            ).json()["diff"],
            {"added": 0, "modified": 0, "deleted": 0, "unchanged": 1},
        )

        added = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": restored["revision"], **self.valid_row},
        ).json()
        self.assertEqual(
            self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            ).json()["diff"],
            {"added": 1, "modified": 0, "deleted": 0, "unchanged": 1},
        )
        removed_added = self.client.delete(
            f"/api/input-drafts/{draft['id']}/rows/{added['row']['id']}",
            headers=self.admin_headers,
            json={"revision": added["revision"]},
        ).json()
        self.assertEqual(
            self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            ).json()["diff"],
            {"added": 0, "modified": 0, "deleted": 0, "unchanged": 1},
        )
        self.client.delete(
            f"/api/input-drafts/{draft['id']}/rows/{original['id']}",
            headers=self.admin_headers,
            json={"revision": removed_added["revision"]},
        )
        self.assertEqual(
            self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            ).json()["diff"],
            {"added": 0, "modified": 0, "deleted": 1, "unchanged": 0},
        )

    def test_row_crud_pagination_search_and_filters(self):
        draft = self.create_draft()
        listed = self.list_rows(draft["id"], offset=0, limit=1)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["rows"][0]["change_type"], "unchanged")

        added = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **self.valid_row},
        )
        self.assertEqual(added.status_code, 201, added.text)
        self.assertGreater(added.json()["revision"], draft["revision"])
        row_id = added.json()["row"]["id"]
        revision = added.json()["revision"]

        for params in (
            {"search": "sku-b"},
            {"site": "SEEKWAY:CA"},
            {"scale_position": "中尾"},
            {"only_modified": "true"},
        ):
            filtered = self.list_rows(draft["id"], **params)
            self.assertEqual(filtered["total"], 1, params)
            self.assertEqual(filtered["rows"][0]["id"], row_id)

        updated = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/{row_id}",
            headers=self.admin_headers,
            json={"revision": revision, **dict(self.valid_row, ordered_days="61")},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["row"]["ordered_days"], "61")
        revision = updated.json()["revision"]

        deleted = self.client.delete(
            f"/api/input-drafts/{draft['id']}/rows/{row_id}",
            headers=self.admin_headers,
            json={"revision": revision},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["row_id"], row_id)
        self.assertEqual(self.list_rows(draft["id"])["total"], 1)

        missing_update = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/999",
            headers=self.admin_headers,
            json={"revision": deleted.json()["revision"], **self.valid_row},
        )
        self.assertEqual(missing_update.status_code, 404, missing_update.text)

    def test_only_errors_filter_and_bulk_delete_are_atomic(self):
        draft = self.create_draft()
        invalid = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **dict(self.valid_row, store_site=" ")},
        )
        self.assertEqual(invalid.status_code, 201, invalid.text)
        invalid_id = invalid.json()["row"]["id"]
        errors = self.list_rows(draft["id"], only_errors="true")
        self.assertEqual(errors["total"], 1)
        self.assertEqual(errors["rows"][0]["id"], invalid_id)
        self.assertEqual(errors["rows"][0]["issues"][0]["code"], "empty_site")

        failed = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows/bulk-delete",
            headers=self.admin_headers,
            json={
                "revision": invalid.json()["revision"],
                "row_ids": [invalid_id, 999],
            },
        )
        self.assertEqual(failed.status_code, 404, failed.text)
        self.assertEqual(self.list_rows(draft["id"], only_errors="true")["total"], 1)

        deleted = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows/bulk-delete",
            headers=self.admin_headers,
            json={
                "revision": invalid.json()["revision"],
                "row_ids": [invalid_id],
            },
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["deleted_ids"], [invalid_id])
        self.assertEqual(self.list_rows(draft["id"], only_errors="true")["total"], 0)

    def test_stale_revision_returns_409_without_partial_changes(self):
        draft = self.create_draft()
        first = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **self.valid_row},
        )
        self.assertEqual(first.status_code, 201, first.text)
        stale = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **dict(self.valid_row, jiaji_sku="SKU-C")},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("刷新", stale.json()["detail"])
        self.assertEqual(self.list_rows(draft["id"])["total"], 2)

    def test_import_preview_apply_uses_single_use_server_token(self):
        draft = self.create_draft()
        candidate = self.position_bytes(
            [["SEEKWAY:CA", "SKU-B", "MSKU-B", "中尾", "备货", 60]]
        )
        preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("replacement.xlsx", BytesIO(candidate))},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(
            preview.json()["diff"],
            {"added": 1, "modified": 0, "deleted": 1, "unchanged": 0},
        )
        token = preview.json()["token"]
        temporary_files = list(
            (self.storage / "temporary" / "position-imports").glob("*.xlsx")
        )
        self.assertEqual(len(temporary_files), 1)

        applied = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={"revision": draft["revision"], "token": token},
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["diff"], preview.json()["diff"])
        self.assertGreater(applied.json()["revision"], draft["revision"])
        rows = self.list_rows(draft["id"])
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["rows"][0]["jiaji_sku"], "SKU-B")
        summary = self.client.get(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        ).json()
        self.assertEqual(
            summary["diff"],
            {"added": 1, "modified": 0, "deleted": 1, "unchanged": 0},
        )
        continued = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/{rows['rows'][0]['id']}",
            headers=self.admin_headers,
            json={
                "revision": applied.json()["revision"],
                **dict(self.valid_row, stocking_position="不备货"),
            },
        )
        self.assertEqual(continued.status_code, 200, continued.text)
        continued_validation = self.client.post(
            f"/api/input-drafts/{draft['id']}/validate",
            headers=self.admin_headers,
        ).json()
        self.assertEqual(continued_validation["diff"], summary["diff"])
        self.assertEqual(
            list((self.storage / "temporary" / "position-imports").glob("*.xlsx")),
            [],
        )

        reused = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={"revision": continued.json()["revision"], "token": token},
        )
        self.assertEqual(reused.status_code, 409, reused.text)

    def test_empty_import_warns_and_publish_requires_fresh_confirmation(self):
        draft = self.create_draft()
        preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("empty.xlsx", BytesIO(self.position_bytes([])))},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(
            {issue["code"] for issue in preview.json()["issues"]},
            {"row_count_cleared", "sites_cleared", "skus_cleared"},
        )
        self.assertEqual(preview.json()["warning_count"], 3)
        applied = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={
                "revision": draft["revision"],
                "token": preview.json()["token"],
            },
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        validation = self.client.post(
            f"/api/input-drafts/{draft['id']}/validate",
            headers=self.admin_headers,
        )
        self.assertEqual(validation.status_code, 200, validation.text)
        self.assertEqual(validation.json()["warning_count"], 3)
        self.assertEqual(
            validation.json()["diff"],
            {"added": 0, "modified": 0, "deleted": 1, "unchanged": 0},
        )

        rejected = self.client.post(
            f"/api/input-drafts/{draft['id']}/publish",
            headers=self.admin_headers,
            json={
                "revision": applied.json()["revision"],
                "name": "empty-position",
                "confirm_warnings": False,
            },
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        confirmed = self.client.post(
            f"/api/input-drafts/{draft['id']}/publish",
            headers=self.admin_headers,
            json={
                "revision": applied.json()["revision"],
                "name": "empty-position",
                "confirm_warnings": True,
            },
        )
        self.assertEqual(confirmed.status_code, 201, confirmed.text)

    def test_import_token_is_bound_to_revision_and_stale_file_is_removed(self):
        draft = self.create_draft()
        preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("replacement.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        token = preview.json()["token"]

        changed = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **self.valid_row},
        )
        self.assertEqual(changed.status_code, 201, changed.text)
        self.assertEqual(
            list((self.storage / "temporary" / "position-imports").glob("*.xlsx")),
            [],
        )
        stale = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={"revision": changed.json()["revision"], "token": token},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.list_rows(draft["id"])["total"], 2)

    def test_import_token_is_bound_to_admin_and_wrong_admin_cannot_consume_it(self):
        draft = self.create_draft()
        created = self.client.post(
            "/api/users",
            headers=self.admin_headers,
            json={
                "username": "second-admin",
                "password": "second-admin-pass",
                "role": "admin",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        second_admin_headers = self.login("second-admin", "second-admin-pass")
        preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("replacement.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        token = preview.json()["token"]

        forbidden = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=second_admin_headers,
            json={"revision": draft["revision"], "token": token},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        self.assertIn(token, self.app.state.position_import_candidates)

        applied = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={"revision": draft["revision"], "token": token},
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertNotIn(token, self.app.state.position_import_candidates)

    def test_import_token_ttl_cleanup_replay_and_concurrent_apply(self):
        draft = self.create_draft()
        self.app.state.import_candidate_ttl_seconds = 60
        expired_preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("expired.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(expired_preview.status_code, 200, expired_preview.text)
        expired_token = expired_preview.json()["token"]
        expired_path = Path(
            self.app.state.position_import_candidates[expired_token]["path"]
        )
        self.app.state.position_import_candidates[expired_token]["expires_at"] = (
            datetime.utcnow() - timedelta(seconds=1)
        )

        current_preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("current.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(current_preview.status_code, 200, current_preview.text)
        self.assertFalse(expired_path.exists())
        expired = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={"revision": draft["revision"], "token": expired_token},
        )
        self.assertEqual(expired.status_code, 409, expired.text)

        token = current_preview.json()["token"]

        def apply_once():
            return self.client.post(
                f"/api/input-drafts/{draft['id']}/import-apply",
                headers=self.admin_headers,
                json={"revision": draft["revision"], "token": token},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _index: apply_once(), range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        replay = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={"revision": max(response.json().get("revision", 1) for response in responses), "token": token},
        )
        self.assertEqual(replay.status_code, 409, replay.text)

    def test_import_candidate_startup_cleanup_only_removes_expired_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_root = root / "storage" / "temporary" / "position-imports"
            candidate_root.mkdir(parents=True)
            expired = candidate_root / "expired.xlsx"
            fresh = candidate_root / "fresh.xlsx"
            expired.write_bytes(b"expired")
            fresh.write_bytes(b"fresh")
            old_timestamp = (datetime.now() - timedelta(seconds=120)).timestamp()
            os.utime(expired, (old_timestamp, old_timestamp))

            app = create_app(
                database_url=sqlite_url(root / "startup.db"),
                storage_root=root / "storage",
                bootstrap_admin=("admin", "admin-pass"),
                import_candidate_ttl_seconds=60,
            )
            try:
                self.assertFalse(expired.exists())
                self.assertTrue(fresh.exists())
            finally:
                app.state.database.dispose()

    def test_invalid_import_returns_400_without_changing_draft_or_leaking_file(self):
        draft = self.create_draft()
        invalid = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("broken.xlsx", BytesIO(b"not-an-excel-file"))},
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertIn("导入文件校验失败", invalid.json()["detail"])
        current = self.client.get(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        ).json()
        self.assertEqual(current["revision"], draft["revision"])
        self.assertEqual(self.list_rows(draft["id"])["total"], 1)
        self.assertEqual(
            list((self.storage / "temporary").rglob("*.xlsx")),
            [],
        )

    def test_download_validate_publish_and_duplicate_name_conflict(self):
        with self.app.state.database.session() as session:
            base_path = Path(
                session.get(InputVersion, self.version["id"]).storage_path
            )
        base_bytes = base_path.read_bytes()
        draft = self.create_draft()

        download = self.client.get(
            f"/api/input-drafts/{draft['id']}/download",
            headers=self.admin_headers,
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertGreater(len(download.content), 0)
        self.assertEqual(
            list((self.storage / "temporary" / "draft-downloads").glob("*.xlsx")),
            [],
        )
        validation = self.client.post(
            f"/api/input-drafts/{draft['id']}/validate",
            headers=self.admin_headers,
        )
        self.assertEqual(validation.status_code, 200, validation.text)
        self.assertTrue(validation.json()["valid"])
        self.assertEqual(validation.json()["error_count"], 0)

        published = self.client.post(
            f"/api/input-drafts/{draft['id']}/publish",
            headers=self.admin_headers,
            json={
                "revision": draft["revision"],
                "name": "position-v2",
                "confirm_warnings": True,
            },
        )
        self.assertEqual(published.status_code, 201, published.text)
        self.assertNotEqual(published.json()["id"], draft["base_version_id"])
        self.assertTrue(published.json()["active"])
        self.assertEqual(published.json()["draft_revision"], draft["revision"] + 1)
        self.assertEqual(published.json()["draft_status"], "published")
        self.assertEqual(base_path.read_bytes(), base_bytes)

        next_draft = self.create_draft()
        duplicate = self.client.post(
            f"/api/input-drafts/{next_draft['id']}/publish",
            headers=self.admin_headers,
            json={
                "revision": next_draft["revision"],
                "name": "position-v2",
                "confirm_warnings": True,
            },
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_publish_validation_and_generation_errors_return_400(self):
        draft = self.create_draft()
        row = self.list_rows(draft["id"])["rows"][0]
        invalid = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/{row['id']}",
            headers=self.admin_headers,
            json={
                "revision": draft["revision"],
                "store_site": " ",
                "jiaji_sku": row["jiaji_sku"],
                "msku": row["msku"],
                "scale_position": row["scale_position"],
                "stocking_position": row["stocking_position"],
                "ordered_days": row["ordered_days"],
            },
        )
        self.assertEqual(invalid.status_code, 200, invalid.text)
        rejected = self.client.post(
            f"/api/input-drafts/{draft['id']}/publish",
            headers=self.admin_headers,
            json={
                "revision": invalid.json()["revision"],
                "name": "invalid-position",
                "confirm_warnings": True,
            },
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertIn("不能发布", rejected.json()["detail"])

        with patch(
            "delivery_note.web.api.publish_draft",
            side_effect=OSError("writer failed"),
            create=True,
        ):
            generation = self.client.post(
                f"/api/input-drafts/{draft['id']}/publish",
                headers=self.admin_headers,
                json={
                    "revision": invalid.json()["revision"],
                    "name": "writer-failure",
                    "confirm_warnings": True,
                },
            )
        self.assertEqual(generation.status_code, 400, generation.text)
        self.assertIn("发布失败", generation.json()["detail"])

    def test_discard_cleans_import_candidate_and_blocks_further_changes(self):
        draft = self.create_draft()
        preview = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-preview",
            headers=self.admin_headers,
            data={"revision": str(draft["revision"])},
            files={"file": ("replacement.xlsx", BytesIO(self.position_bytes()))},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        discarded = self.client.post(
            f"/api/input-drafts/{draft['id']}/discard",
            headers=self.admin_headers,
            json={"revision": draft["revision"]},
        )
        self.assertEqual(discarded.status_code, 200, discarded.text)
        self.assertEqual(discarded.json()["status"], "discarded")
        self.assertEqual(
            list((self.storage / "temporary" / "position-imports").glob("*.xlsx")),
            [],
        )
        blocked = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={"revision": discarded.json()["revision"], **self.valid_row},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

    def test_successful_row_write_commits_once(self):
        draft = self.create_draft()
        commits = []

        def record_commit(session):
            if session.bind is self.app.state.database.engine:
                commits.append(session)

        event.listen(Session, "after_commit", record_commit)
        try:
            response = self.client.post(
                f"/api/input-drafts/{draft['id']}/rows",
                headers=self.admin_headers,
                json={"revision": draft["revision"], **self.valid_row},
            )
        finally:
            event.remove(Session, "after_commit", record_commit)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(commits), 1)

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
            versions = session.query(InputVersion).order_by(InputVersion.id).all()
            persisted_draft = session.get(InputDraft, draft["id"])
            self.assertEqual([(item.id, item.active) for item in versions], [(self.version["id"], True)])
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
                "delivery_note.web.api.mutate_draft_row",
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
        self.assertEqual(len(rollbacks), 1)


if __name__ == "__main__":
    unittest.main()
