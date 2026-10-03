from tests.support.position_api import PositionApiCase
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import event
from sqlalchemy.orm import Session

import delivery_note.web.position_draft_read as draft_read_module
from delivery_note.inspection.workbooks import write_position_workbook
from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from delivery_note.web.models import (
    InputVersion,
    PositionDraftRow,
)


class PositionDraftApiTests(PositionApiCase):
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
