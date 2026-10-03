from tests.support.position_api import PositionApiCase
from io import BytesIO


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
