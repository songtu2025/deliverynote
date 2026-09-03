from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from delivery_note.gerpgo import (
    GerpgoClient,
    GerpgoError,
    GerpgoSettings,
    _post_json,
    load_gerpgo_settings,
    save_gerpgo_settings,
)


class GerpgoSettingsTests(unittest.TestCase):
    def test_managed_settings_override_environment(self):
        with TemporaryDirectory() as directory:
            storage_root = Path(directory)
            managed = GerpgoSettings(
                base_url="https://managed.example.test",
                app_id="managed-app",
                app_key="managed-key",
                source="managed",
            )
            save_gerpgo_settings(storage_root, managed)

            with patch.dict(
                "os.environ",
                {
                    "GERPGO_API_BASE_URL": "https://env.example.test",
                    "GERPGO_APP_ID": "env-app",
                    "GERPGO_APP_KEY": "env-key",
                },
            ):
                loaded = load_gerpgo_settings(storage_root)
                client = GerpgoClient.from_config(storage_root)

            self.assertEqual(loaded, managed)
            self.assertEqual(client.base_url, managed.base_url)
            self.assertEqual(client.app_id, managed.app_id)
            self.assertEqual(client.app_key, managed.app_key)

    def test_environment_is_used_when_no_managed_file_exists(self):
        with TemporaryDirectory() as directory:
            with patch.dict(
                "os.environ",
                {
                    "GERPGO_API_BASE_URL": "https://env.example.test",
                    "GERPGO_APP_ID": "env-app",
                    "GERPGO_APP_KEY": "env-key",
                },
            ):
                settings = load_gerpgo_settings(Path(directory))

            self.assertEqual(settings.source, "environment")
            self.assertEqual(settings.base_url, "https://env.example.test")


class GerpgoRequestTests(unittest.TestCase):
    def test_http_error_keeps_rate_limit_detail(self):
        body = BytesIO(
            b'{"code":90008,"messages":["rate limited"],"data":null}'
        )
        error = HTTPError(
            "https://example.test/detail",
            509,
            "rate limited",
            {},
            body,
        )

        with patch("delivery_note.gerpgo.urlopen", side_effect=error):
            with self.assertRaisesRegex(GerpgoError, "90008.*rate limited") as caught:
                _post_json("https://example.test/detail", {}, {"poCode": "PO-1"})

        self.assertEqual(caught.exception.http_status, 509)
        self.assertEqual(caught.exception.api_code, 90008)


if __name__ == "__main__":
    unittest.main()
