from tests.support.position_api import PositionApiCase
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

import delivery_note.web.position_draft_read as draft_read_module
import delivery_note.web.position_draft_state as position_drafts_module
from delivery_note.input_inspection import write_position_workbook
from delivery_note.processing.models import (POSITION_SOURCE_COLUMNS)
from delivery_note.web.api import create_app
from delivery_note.web.database import sqlite_url
from delivery_note.web.models import (
    InputDraft,
    InputVersion,
    PositionDraftRow,
)
from tests.asgi_client import SyncASGIClient


































class PositionDraftApiTests(PositionApiCase):









    def test_missing_inspection_and_draft_resources_return_404(self):
        for suffix in ("summary", "inspection", "preview", "download"):
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
            (
                "POST",
                "/api/input-drafts/999/rows",
                {"json": {"revision": 1, **self.valid_row}},
            ),
            (
                "PUT",
                "/api/input-drafts/999/rows/999",
                {"json": {"revision": 1, **self.valid_row}},
            ),
            ("DELETE", "/api/input-drafts/999/rows/999", {"json": {"revision": 1}}),
            (
                "POST",
                "/api/input-drafts/999/rows/bulk-delete",
                {"json": {"revision": 1, "row_ids": [999]}},
            ),
            (
                "POST",
                "/api/input-drafts/999/import-apply",
                {"json": {"revision": 1, "token": "missing"}},
            ),
            ("GET", "/api/input-drafts/999/download", {}),
            ("POST", "/api/input-drafts/999/validate", {}),
            (
                "POST",
                "/api/input-drafts/999/publish",
                {"json": {"revision": 1, "name": "missing", "confirm_warnings": True}},
            ),
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
            (
                "GET",
                f"/api/input-versions/{self.version['id']}/inspection",
                {},
            ),
            ("GET", f"/api/input-versions/{self.version['id']}/preview", {}),
            ("GET", f"/api/input-versions/{self.version['id']}/download", {}),
            ("POST", "/api/input-drafts/position", {}),
            ("GET", "/api/input-drafts/position", {}),
            ("GET", f"/api/input-drafts/{draft['id']}/rows", {}),
            (
                "POST",
                f"/api/input-drafts/{draft['id']}/rows",
                {"json": {"revision": draft["revision"], **self.valid_row}},
            ),
            (
                "PUT",
                f"/api/input-drafts/{draft['id']}/rows/{row_id}",
                {"json": {"revision": draft["revision"], **self.valid_row}},
            ),
            (
                "DELETE",
                f"/api/input-drafts/{draft['id']}/rows/{row_id}",
                {"json": {"revision": draft["revision"]}},
            ),
            (
                "POST",
                f"/api/input-drafts/{draft['id']}/rows/bulk-delete",
                {"json": {"revision": draft["revision"], "row_ids": [row_id]}},
            ),
            (
                "POST",
                f"/api/input-drafts/{draft['id']}/import-apply",
                {"json": {"revision": draft["revision"], "token": "missing"}},
            ),
            ("GET", f"/api/input-drafts/{draft['id']}/download", {}),
            ("POST", f"/api/input-drafts/{draft['id']}/validate", {}),
            (
                "POST",
                f"/api/input-drafts/{draft['id']}/publish",
                {
                    "json": {
                        "revision": draft["revision"],
                        "name": "forbidden",
                        "confirm_warnings": True,
                    }
                },
            ),
            (
                "POST",
                f"/api/input-drafts/{draft['id']}/discard",
                {"json": {"revision": draft["revision"]}},
            ),
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
                headers = {
                    "Authorization": f"Bearer {login.json()['token']}"
                }
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

    def test_resuming_existing_draft_records_the_admin_action(self):
        created = self.create_draft()

        resumed = self.client.post(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        )

        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["id"], created["id"])
        audit_logs = self.client.get(
            "/api/audit-logs",
            headers=self.admin_headers,
        ).json()
        resume_logs = [
            log for log in audit_logs if log["action"] == "resume_input_draft"
        ]
        self.assertEqual(len(resume_logs), 1)
        self.assertEqual(resume_logs[0]["user_id"], created["created_by"])
        self.assertEqual(resume_logs[0]["entity_type"], "input_draft")
        self.assertEqual(resume_logs[0]["entity_id"], str(created["id"]))
        self.assertEqual(
            resume_logs[0]["details"],
            {"base_version_id": created["base_version_id"]},
        )

    def test_draft_endpoint_locks_versions_before_its_first_draft_lookup(self):
        calls: list[str] = []
        original_scalar = Session.scalar
        original_scalars = Session.scalars

        def record_scalar(session, statement, *args, **kwargs):
            text = str(statement)
            if "input_versions" in text or "input_drafts" in text:
                calls.append(text)
            return original_scalar(session, statement, *args, **kwargs)

        def record_scalars(session, statement, *args, **kwargs):
            text = str(statement)
            if "input_versions" in text or "input_drafts" in text:
                calls.append(text)
            return original_scalars(session, statement, *args, **kwargs)

        with (
            patch.object(Session, "scalar", new=record_scalar),
            patch.object(Session, "scalars", new=record_scalars),
        ):
            response = self.client.post(
                "/api/input-drafts/position", headers=self.admin_headers
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertIn("input_versions", calls[0])
        self.assertIn("ORDER BY input_versions.id", calls[0])
        self.assertIn("input_drafts", calls[1])

    def test_upload_and_activation_lock_input_versions_in_id_order(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"])
        sheet.append(
            ["待交货", "KuangBiao", "SKU-A", "AMAZON:SEEKWAY:US", "水鞋-广州仓", 100]
        )
        output = BytesIO()
        workbook.save(output)
        payload = output.getvalue()
        calls: list[str] = []
        original_scalars = Session.scalars

        def record_scalars(session, statement, *args, **kwargs):
            text = str(statement)
            if "FROM input_versions" in text and "FOR UPDATE" in text:
                calls.append(text)
            return original_scalars(session, statement, *args, **kwargs)

        with patch.object(Session, "scalars", new=record_scalars):
            active = self.client.post(
                "/api/input-versions/purchase",
                headers=self.admin_headers,
                data={"name": "purchase-v1", "activate": "true"},
                files={"file": ("purchase-v1.xlsx", BytesIO(payload))},
            )
            inactive = self.client.post(
                "/api/input-versions/purchase",
                headers=self.admin_headers,
                data={"name": "purchase-v2", "activate": "false"},
                files={"file": ("purchase-v2.xlsx", BytesIO(payload))},
            )
            activated = self.client.post(
                f"/api/input-versions/{inactive.json()['id']}/activate",
                headers=self.admin_headers,
            )

        self.assertEqual(active.status_code, 201, active.text)
        self.assertEqual(inactive.status_code, 201, inactive.text)
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(len(calls), 2)
        for statement in calls:
            self.assertIn("ORDER BY input_versions.id", statement)

    def test_position_replacement_requires_draft_workflow_even_without_open_draft(self):
        detail = "库位资料已有正式版本，请使用“开始网页维护”通过草稿流程发布新版本"
        position_directory = self.storage / "master" / "position"
        files_before = set(position_directory.iterdir())

        active_upload = self.client.post(
            "/api/input-versions/position",
            headers=self.admin_headers,
            data={"name": "position-v2-active", "activate": "true"},
            files={
                "file": (
                    "position-v2-active.xlsx",
                    BytesIO(self.position_bytes()),
                )
            },
        )
        self.assertEqual(active_upload.status_code, 409, active_upload.text)
        self.assertEqual(active_upload.json()["detail"], detail)

        inactive_upload = self.client.post(
            "/api/input-versions/position",
            headers=self.admin_headers,
            data={"name": "position-v2-inactive", "activate": "false"},
            files={
                "file": (
                    "position-v2-inactive.xlsx",
                    BytesIO(self.position_bytes()),
                )
            },
        )
        self.assertEqual(inactive_upload.status_code, 409, inactive_upload.text)
        self.assertEqual(inactive_upload.json()["detail"], detail)

        historical_path = position_directory / "position-old.xlsx"
        historical_path.write_bytes(self.position_bytes())
        with self.app.state.database.session() as session:
            historical = InputVersion(
                kind="position",
                name="position-old",
                original_name="position-old.xlsx",
                storage_path=str(historical_path),
                active=False,
                created_by=self.version["created_by"],
            )
            session.add(historical)
            session.commit()
            historical_id = historical.id
        activation = self.client.post(
            f"/api/input-versions/{historical_id}/activate",
            headers=self.admin_headers,
        )
        self.assertEqual(activation.status_code, 409, activation.text)
        self.assertEqual(activation.json()["detail"], detail)

        versions = self.client.get(
            "/api/input-versions", headers=self.admin_headers
        ).json()
        self.assertTrue(
            next(item for item in versions if item["id"] == self.version["id"])[
                "active"
            ]
        )
        self.assertFalse(
            next(item for item in versions if item["id"] == historical_id)["active"]
        )
        self.assertFalse(any(item["name"] == "position-v2-active" for item in versions))
        self.assertFalse(
            any(item["name"] == "position-v2-inactive" for item in versions)
        )
        self.assertEqual(
            set(position_directory.iterdir()), files_before | {historical_path}
        )

    def test_resumed_legacy_draft_reports_its_base_and_cannot_overwrite_new_active(
        self,
    ):
        draft = self.create_draft()
        replacement_path = self.storage / "master" / "position" / "legacy-v2.xlsx"
        replacement_path.write_bytes(self.position_bytes())
        with self.app.state.database.session() as session:
            session.get(InputVersion, self.version["id"]).active = False
            replacement = InputVersion(
                kind="position",
                name="position-v2",
                original_name="position-v2.xlsx",
                storage_path=str(replacement_path),
                active=True,
                created_by=draft["created_by"],
            )
            session.add(replacement)
            session.commit()
            replacement_id = replacement.id

        resumed = self.client.post(
            "/api/input-drafts/position", headers=self.admin_headers
        )
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["base_version_id"], self.version["id"])
        self.assertEqual(resumed.json()["base_version_name"], "position-v1")
        self.assertEqual(resumed.json()["active_version_id"], replacement_id)
        self.assertEqual(resumed.json()["active_version_name"], "position-v2")

        rejected = self.client.post(
            f"/api/input-drafts/{draft['id']}/publish",
            headers=self.admin_headers,
            json={
                "revision": draft["revision"],
                "name": "position-v3",
                "confirm_warnings": True,
            },
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()["code"], "draft_base_version_changed")
        self.assertEqual(
            rejected.json()["detail"],
            "当前启用的库位版本已变化，请放弃当前草稿后重新开始",
        )
        current = self.client.get(
            "/api/input-drafts/position", headers=self.admin_headers
        ).json()
        self.assertEqual(current["status"], "editing")
        with self.app.state.database.session() as session:
            self.assertTrue(session.get(InputVersion, replacement_id).active)
            self.assertEqual(
                session.query(InputVersion).filter_by(name="position-v3").count(),
                0,
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
            json={
                "revision": revision,
                **dict(self.valid_row, stocking_position="不备货"),
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["row"]["stocking_position"], "不备货")
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

    def test_row_page_loads_only_requested_orm_rows(self):
        source_rows = [
            [
                "SEEKWAY:US" if index % 2 else "SEEKWAY:CA",
                f"SKU-{index:03d}",
                f"MSKU-{index:03d}",
                "短尾" if index % 3 else "中尾",
                "备货",
            ]
            for index in range(1, 121)
        ]
        with self.app.state.database.session() as session:
            source_path = Path(
                session.get(InputVersion, self.version["id"]).storage_path
            )
        write_position_workbook(
            source_path,
            pd.DataFrame(source_rows, columns=POSITION_SOURCE_COLUMNS),
        )
        draft = self.create_draft()
        loaded_row_ids: list[int] = []

        def record_loaded(_session, instance):
            if isinstance(instance, PositionDraftRow):
                loaded_row_ids.append(instance.id)

        event.listen(Session, "loaded_as_persistent", record_loaded)
        try:
            page = self.list_rows(draft["id"], offset=10, limit=50)
            self.assertEqual(len(loaded_row_ids), 50)
            filtered = self.list_rows(
                draft["id"],
                search="sku-01",
                site="seekway:ca",
            )
        finally:
            event.remove(Session, "loaded_as_persistent", record_loaded)

        self.assertEqual(page["total"], 120)
        self.assertEqual(len(page["rows"]), 50)
        self.assertEqual(
            [row["row_order"] for row in page["rows"]],
            list(range(11, 61)),
        )
        self.assertEqual(len(loaded_row_ids), 55)
        self.assertEqual(filtered["total"], 5)
        self.assertEqual(
            [row["jiaji_sku"] for row in filtered["rows"]],
            ["SKU-010", "SKU-012", "SKU-014", "SKU-016", "SKU-018"],
        )

        first_row = page["rows"][0]
        values = {
            field: first_row[field]
            for field in (
                "store_site",
                "jiaji_sku",
                "msku",
                "scale_position",
                "stocking_position",
            )
        }
        values["scale_position"] = "长尾"
        updated = self.client.put(
            f"/api/input-drafts/{draft['id']}/rows/{first_row['id']}",
            headers=self.admin_headers,
            json={"revision": draft["revision"], **values},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        original_snapshots = draft_read_module._draft_row_snapshots
        with patch.object(
            draft_read_module,
            "_draft_row_snapshots",
            wraps=original_snapshots,
        ) as snapshots:
            self.list_rows(draft["id"], offset=0, limit=50)
            self.list_rows(draft["id"], offset=50, limit=50)
        self.assertEqual(snapshots.call_count, 1)

    def test_only_errors_filter_and_bulk_delete_are_atomic(self):
        draft = self.create_draft()
        invalid = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={
                "revision": draft["revision"],
                **dict(self.valid_row, store_site=" "),
            },
        )
        self.assertEqual(invalid.status_code, 201, invalid.text)
        invalid_id = invalid.json()["row"]["id"]
        valid = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows",
            headers=self.admin_headers,
            json={
                "revision": invalid.json()["revision"],
                **self.valid_row,
            },
        )
        self.assertEqual(valid.status_code, 201, valid.text)
        valid_id = valid.json()["row"]["id"]
        errors = self.list_rows(draft["id"], only_errors="true")
        self.assertEqual(errors["total"], 1)
        self.assertEqual(errors["rows"][0]["id"], invalid_id)
        self.assertEqual(errors["rows"][0]["issues"][0]["code"], "empty_site")

        failed = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows/bulk-delete",
            headers=self.admin_headers,
            json={
                "revision": valid.json()["revision"],
                "row_ids": [invalid_id, valid_id, 999],
            },
        )
        self.assertEqual(failed.status_code, 404, failed.text)
        self.assertEqual(self.list_rows(draft["id"], only_errors="true")["total"], 1)
        self.assertEqual(self.list_rows(draft["id"])["total"], 3)

        deleted = self.client.post(
            f"/api/input-drafts/{draft['id']}/rows/bulk-delete",
            headers=self.admin_headers,
            json={
                "revision": valid.json()["revision"],
                "row_ids": [invalid_id, valid_id],
            },
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(
            deleted.json()["deleted_ids"],
            [invalid_id, valid_id],
        )
        self.assertEqual(
            deleted.json()["revision"],
            valid.json()["revision"] + 1,
        )
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
            json={
                "revision": draft["revision"],
                **dict(self.valid_row, jiaji_sku="SKU-C"),
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["code"], "draft_revision_conflict")
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
