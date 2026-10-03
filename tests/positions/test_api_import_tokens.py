from tests.support.position_api import PositionApiCase
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory


from delivery_note.web.api import create_app
from delivery_note.web.database import sqlite_url


class PositionDraftApiTests(PositionApiCase):
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
