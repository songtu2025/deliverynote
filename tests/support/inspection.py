"""资料分析测试的临时工作簿和默认库位夹具。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from delivery_note.processing.models import POSITION_SOURCE_COLUMNS


class InputInspectionCase(unittest.TestCase):
    """共用资料分析测试所需的文件目录。"""

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.path = self.root / "position.xlsx"
        self.frame = pd.DataFrame(
            [["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货"]],
            columns=POSITION_SOURCE_COLUMNS,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()
