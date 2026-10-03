from tests.support.position_api import PositionApiCase

from sqlalchemy import event
from sqlalchemy.orm import Session


class PositionDraftApiTests(PositionApiCase):
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
