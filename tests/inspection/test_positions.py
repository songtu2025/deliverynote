from unittest.mock import patch

import pandas as pd

from delivery_note.excel_io import (
    read_position_workbook,
)
from delivery_note.input_inspection import (
    inspect_input_version,
    inspect_input_version_with_preview,
    preview_input_version,
)
from delivery_note.inspection.positions import (
    position_change_warnings,
    position_diff,
    validate_position_frame,
)
from delivery_note.inspection.workbooks import write_position_workbook
from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from tests.support.inspection import InputInspectionCase


class InputInspectionTests(InputInspectionCase):
    def test_position_summary_preview_and_quality_issues(self) -> None:
        frame = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "未知", ""],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )
        issues = validate_position_frame(frame)
        self.assertIn("duplicate_msku", {item["code"] for item in issues})
        self.assertIn("unknown_scale", {item["code"] for item in issues})
        duplicate_issue = next(
            item for item in issues if item["code"] == "duplicate_msku"
        )
        self.assertEqual(duplicate_issue["row_numbers"], [2, 3])

        write_position_workbook(self.path, frame)
        inspection = inspect_input_version("position", self.path)
        self.assertEqual(inspection["row_count"], 2)
        self.assertEqual(inspection["metrics"], {"sites": 1, "skus": 1, "mskus": 1})
        self.assertEqual(
            {item["code"] for item in inspection["issues"]},
            {item["code"] for item in issues},
        )

        preview = preview_input_version("position", self.path, offset=1, limit=1)
        self.assertEqual(preview["total"], 2)
        self.assertEqual(preview["offset"], 1)
        self.assertEqual(preview["limit"], 1)
        self.assertEqual(preview["columns"], POSITION_SOURCE_COLUMNS)
        self.assertNotIn("已下单可售天数", preview["rows"][0])

    def test_combined_position_inspection_reads_the_workbook_once(self) -> None:
        write_position_workbook(self.path, self.frame)

        with patch(
            "delivery_note.inspection.workbooks.read_position_workbook",
            wraps=read_position_workbook,
        ) as read_workbook:
            result = inspect_input_version_with_preview(
                "position",
                self.path,
                offset=0,
                limit=50,
            )

        self.assertEqual(read_workbook.call_count, 1)
        self.assertEqual(result["summary"]["row_count"], 1)
        self.assertEqual(result["preview"]["total"], 1)
        self.assertEqual(result["preview"]["rows"][0]["积加SKU"], "SKU-A")

    def test_written_position_workbook_round_trips(self) -> None:
        write_position_workbook(self.path, self.frame)
        self.assertEqual(
            read_position_workbook(self.path).to_dict("records"),
            self.frame.to_dict("records"),
        )

    def test_position_validation_reports_errors_and_warnings(self) -> None:
        frame = pd.DataFrame(
            [
                [None, "SKU-A", "MSKU-A", "短尾", "备货"],
                ["SEEKWAY:US", "", "MSKU-B", "中尾", None],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )

        issues = {item["code"]: item for item in validate_position_frame(frame)}

        self.assertEqual(issues["empty_site"]["severity"], "error")
        self.assertEqual(issues["empty_sku"]["severity"], "error")
        self.assertEqual(issues["empty_stocking"]["severity"], "warning")
        self.assertEqual(issues["empty_site"]["row_numbers"], [2])
        self.assertEqual(issues["empty_sku"]["row_numbers"], [3])

    def test_position_diff_counts_composite_key_changes(self) -> None:
        base = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                ["SEEKWAY:CA", "SKU-B", "MSKU-B", "中尾", "备货"],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )
        candidate = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "不备货"],
                ["SEEKWAY:UK", "SKU-C", "MSKU-C", "长尾", "备货"],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )

        self.assertEqual(
            position_diff(base, candidate),
            {"added": 1, "modified": 1, "deleted": 1, "unchanged": 0},
        )

    def test_position_diff_normalizes_identity_keys(self) -> None:
        candidate = self.frame.copy()
        candidate.loc[0, "店铺-站点"] = " seekway:us "
        candidate.loc[0, "积加SKU"] = "sku-a"
        candidate.loc[0, "MSKU"] = "msku-a"

        self.assertEqual(
            position_diff(self.frame, candidate),
            {"added": 0, "modified": 0, "deleted": 0, "unchanged": 1},
        )

    def test_position_diff_stably_pairs_duplicate_identity_rows(self) -> None:
        base = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "中尾", "备货"],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )
        candidate = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "长尾", "备货"],
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "长尾", "备货"],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )

        self.assertEqual(
            position_diff(base, candidate),
            {"added": 1, "modified": 1, "deleted": 0, "unchanged": 1},
        )

    def test_position_change_warnings_cover_empty_and_fifty_percent_changes(
        self,
    ) -> None:
        base = pd.DataFrame(
            [
                [f"STORE:{index}", f"SKU-{index}", f"MSKU-{index}", "短尾", "备货"]
                for index in range(4)
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )
        empty = pd.DataFrame(columns=POSITION_SOURCE_COLUMNS)
        half = base.iloc[:2].copy()
        increased = pd.concat(
            [
                base,
                pd.DataFrame(
                    [
                        ["STORE:4", "SKU-4", "MSKU-4", "短尾", "备货"],
                        ["STORE:5", "SKU-5", "MSKU-5", "短尾", "备货"],
                    ],
                    columns=POSITION_SOURCE_COLUMNS,
                ),
            ],
            ignore_index=True,
        )

        self.assertEqual(
            {issue["code"] for issue in position_change_warnings(base, empty)},
            {"row_count_cleared", "sites_cleared", "skus_cleared"},
        )
        self.assertEqual(
            {issue["code"] for issue in position_change_warnings(base, half)},
            {"row_count_changed", "sites_changed", "skus_changed"},
        )
        self.assertEqual(
            {issue["code"] for issue in position_change_warnings(base, increased)},
            {"row_count_changed", "sites_changed", "skus_changed"},
        )

    def test_empty_msku_is_an_error_when_site_and_sku_have_multiple_rows(self) -> None:
        frame = pd.DataFrame(
            [
                ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                [" seekway:us ", "sku-a", "", "中尾", "备货"],
            ],
            columns=POSITION_SOURCE_COLUMNS,
        )

        duplicate_issue = next(
            item
            for item in validate_position_frame(frame)
            if item["code"] == "duplicate_msku"
        )
        self.assertEqual(duplicate_issue["severity"], "error")
        self.assertEqual(duplicate_issue["row_numbers"], [3])
