from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from delivery_note.application import DeliveryRequest, process_delivery_batch
from delivery_note.config import resolve_supplier
from delivery_note.excel_io import (
    read_delivery_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_position_workbook,
    read_supplier_workbook,
    validate_template_workbook,
)

try:
    from scripts.generate_acceptance_data import generate_acceptance_data
except ImportError:
    generate_acceptance_data = None


class AcceptanceDataTests(unittest.TestCase):
    def test_script_runs_directly_from_repository_root(self):
        repository_root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/generate_acceptance_data.py",
                    "--output-dir",
                    directory,
                ],
                cwd=repository_root,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("delivery_first:", result.stdout)

    def test_generated_files_cover_shared_balance_scenario(self):
        self.assertIsNotNone(generate_acceptance_data, "验收数据生成器尚未实现")
        if generate_acceptance_data is None:
            return

        with TemporaryDirectory() as directory:
            paths = generate_acceptance_data(Path(directory))

            self.assertEqual(
                set(paths),
                {
                    "purchase",
                    "product",
                    "supplier",
                    "position",
                    "template",
                    "delivery_first",
                    "delivery_second",
                },
            )
            self.assertTrue(all(path.is_file() for path in paths.values()))
            validate_template_workbook(paths["template"])

            supplier_rows = read_supplier_workbook(paths["supplier"])
            product_rows = read_product_workbook(paths["product"])
            purchase_rows = read_purchase_workbook(paths["purchase"])
            position_rows = read_position_workbook(paths["position"])
            self.assertEqual(position_rows.iloc[0]["MSKU"], "MSKU-A")

            requests = []
            for key in ("delivery_first", "delivery_second"):
                supplier = resolve_supplier(paths[key], supplier_rows)
                requests.append(
                    DeliveryRequest(
                        source_id=key,
                        delivery_rows=read_delivery_workbook(paths[key]),
                        supplier_name=supplier.name,
                        supplier_code=supplier.code,
                        source_name=paths[key].name,
                    )
                )

            result = process_delivery_batch(requests, product_rows, purchase_rows)
            self.assertEqual(result.delivery_total, 160)
            self.assertEqual(result.import_total, 100)
            self.assertEqual(result.manual_total, 60)
            self.assertEqual(result.items[0].result.import_total, 80)
            self.assertEqual(result.items[1].result.import_total, 20)


if __name__ == "__main__":
    unittest.main()
