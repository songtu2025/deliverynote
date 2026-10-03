from tests.support.position_api import PositionApiCase
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


from delivery_note.web.models import (
    InputVersion,
)


class PositionDraftApiTests(PositionApiCase):
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
