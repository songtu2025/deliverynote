from tests.support.position_api import PositionApiCase
from io import BytesIO


from delivery_note.web.models import (
    InputVersion,
)


class PositionDraftApiTests(PositionApiCase):
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
