from tests.support.position_api import PositionApiCase
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


import delivery_note.web.position_draft_read as draft_read_module
import delivery_note.web.position_draft_state as position_drafts_module
from delivery_note.web.api import create_app
from delivery_note.web.database import sqlite_url
from tests.asgi_client import SyncASGIClient


class PositionDraftApiTests(PositionApiCase):
    def test_draft_summary_reads_the_base_workbook_once(self):
        with (
            patch.object(
                position_drafts_module,
                "read_position_workbook",
                wraps=position_drafts_module.read_position_workbook,
            ) as read_workbook,
            patch.object(
                draft_read_module,
                "validate_position_frame",
                wraps=draft_read_module.validate_position_frame,
            ) as validate_frame,
        ):
            draft = self.create_draft()
            first = self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            )
            second = self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            )

            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(read_workbook.call_count, 1)
            self.assertEqual(validate_frame.call_count, 1)

            mutation = self.client.post(
                f"/api/input-drafts/{draft['id']}/rows",
                headers=self.admin_headers,
                json={"revision": draft["revision"], **self.valid_row},
            )
            self.assertEqual(mutation.status_code, 201, mutation.text)
            changed = self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            )
            repeated = self.client.get(
                "/api/input-drafts/position",
                headers=self.admin_headers,
            )

        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(changed.json()["revision"], mutation.json()["revision"])
        self.assertEqual(repeated.json()["revision"], mutation.json()["revision"])
        self.assertEqual(read_workbook.call_count, 1)
        self.assertEqual(validate_frame.call_count, 2)

    def test_draft_caches_do_not_cross_application_databases(self):
        first = self.create_draft()
        self.assertEqual(first["row_count"], 1)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                database_url=sqlite_url(root / "isolated.db"),
                storage_root=root / "storage",
                bootstrap_admin=("admin", "admin-pass"),
            )
            client = SyncASGIClient(app)
            try:
                login = client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "admin-pass"},
                )
                headers = {"Authorization": f"Bearer {login.json()['token']}"}
                upload = client.post(
                    "/api/input-versions/position",
                    headers=headers,
                    data={"name": "isolated-position", "activate": "true"},
                    files={
                        "file": (
                            "isolated-position.xlsx",
                            BytesIO(
                                self.position_bytes(
                                    [
                                        [
                                            "OTHER:US",
                                            "OTHER-A",
                                            "OTHER-MSKU-A",
                                            "短尾",
                                            "备货",
                                            30,
                                        ],
                                        [
                                            "OTHER:CA",
                                            "OTHER-B",
                                            "OTHER-MSKU-B",
                                            "中尾",
                                            "备货",
                                            60,
                                        ],
                                    ]
                                )
                            ),
                        )
                    },
                )
                self.assertEqual(upload.status_code, 201, upload.text)
                isolated = client.post(
                    "/api/input-drafts/position",
                    headers=headers,
                )
                self.assertEqual(isolated.status_code, 201, isolated.text)
                self.assertEqual(isolated.json()["row_count"], 2)
                rows = client.get(
                    f"/api/input-drafts/{isolated.json()['id']}/rows",
                    headers=headers,
                )
                self.assertEqual(rows.status_code, 200, rows.text)
                self.assertEqual(
                    [row["jiaji_sku"] for row in rows.json()["rows"]],
                    ["OTHER-A", "OTHER-B"],
                )
            finally:
                client.close()
                app.state.database.dispose()
