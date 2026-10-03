from tests.support.position_api import PositionApiCase
from io import BytesIO
from unittest.mock import patch

from openpyxl import Workbook
from sqlalchemy.orm import Session


class PositionDraftApiTests(PositionApiCase):
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
