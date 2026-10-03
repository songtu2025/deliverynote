from tests.support.position_api import PositionApiCase
from io import BytesIO


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
