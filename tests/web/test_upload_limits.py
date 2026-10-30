"""验证真实上传容量边界、提示及失败清理。"""

from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
import os

from fastapi import HTTPException, UploadFile

from delivery_note.web.api import create_app
from delivery_note.web.uploads import _save_upload


class UploadLimitTests(IsolatedAsyncioTestCase):
    async def test_exact_limit_is_saved_and_one_extra_byte_is_rejected(self) -> None:
        limit = 100 * 1024 * 1024
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "upload.xlsx"
            for extra in (0, 1):
                with self.subTest(extra=extra), TemporaryFile() as stream:
                    stream.truncate(limit + extra)
                    stream.seek(0)
                    upload = UploadFile(file=stream, filename="upload.xlsx")
                    if extra:
                        with self.assertRaises(HTTPException) as caught:
                            await _save_upload(upload, destination, limit)
                        self.assertEqual(caught.exception.status_code, 413)
                        self.assertEqual(
                            caught.exception.detail,
                            "单个文件不能超过 100 MiB，请缩小文件后重试。",
                        )
                    else:
                        await _save_upload(upload, destination, limit)
                    self.assertTrue(stream.closed)
                    self.assertEqual(destination.stat().st_size, limit)
                    self.assertEqual(list(Path(directory).iterdir()), [destination])

    async def test_default_and_environment_override(self) -> None:
        for configured, expected in ((None, 100 * 1024 * 1024), ("10485760", 10485760)):
            with self.subTest(configured=configured), TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.dict(os.environ):
                    os.environ.pop("MAX_UPLOAD_BYTES", None)
                    if configured is not None:
                        os.environ["MAX_UPLOAD_BYTES"] = configured
                    app = create_app(
                        database_url=f"sqlite+pysqlite:///{root / 'test.db'}",
                        storage_root=root / "storage",
                        auto_migrate_schema=True,
                    )
                try:
                    self.assertEqual(app.state.max_upload_bytes, expected)
                finally:
                    app.state.database.dispose()
