from tests.support.position_api import PositionApiCase
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from delivery_note.web.api import create_app
from delivery_note.web.database import sqlite_url
from delivery_note.web.models import (
    InputDraft,
    InputVersion,
)


































class PositionDraftApiTests(PositionApiCase):
























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
        self.assertEqual(stale.json()["code"], "draft_import_preview_expired")
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
        self.assertEqual(
            sorted(response.status_code for response in responses), [200, 409]
        )
        replay = self.client.post(
            f"/api/input-drafts/{draft['id']}/import-apply",
            headers=self.admin_headers,
            json={
                "revision": max(
                    response.json().get("revision", 1) for response in responses
                ),
                "token": token,
            },
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
            base_path = Path(session.get(InputVersion, self.version["id"]).storage_path)
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
        self.assertEqual(duplicate.json()["code"], "input_version_name_exists")

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
            "delivery_note.web.position_draft_lifecycle.publish_draft",
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
