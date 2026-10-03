from tests.support.web_api import WebApiCase
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


from tests.asgi_client import SyncASGIClient

from delivery_note.web.api import create_app


class WebApiTests(WebApiCase):
    def test_session_cookie_secure_environment_is_parsed_strictly(self):
        for configured, expected_secure in (("false", False), ("true", True)):
            with self.subTest(configured=configured), TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.dict(
                    os.environ,
                    {"SESSION_COOKIE_SECURE": configured},
                ):
                    app = create_app(
                        database_url=f"sqlite+pysqlite:///{root / 'cookie.db'}",
                        storage_root=root / "storage",
                        bootstrap_admin=("admin", "admin-pass"),
                    )
                client = SyncASGIClient(app)
                try:
                    response = client.post(
                        "/api/auth/login",
                        json={"username": "admin", "password": "admin-pass"},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(
                        "; Secure" in response.headers["set-cookie"],
                        expected_secure,
                    )
                finally:
                    client.close()
                    app.state.database.dispose()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.dict(
                    os.environ,
                    {"SESSION_COOKIE_SECURE": "sometimes"},
                ),
                self.assertRaisesRegex(ValueError, "SESSION_COOKIE_SECURE"),
            ):
                create_app(
                    database_url=f"sqlite+pysqlite:///{root / 'invalid-cookie.db'}",
                    storage_root=root / "storage",
                    auto_migrate_schema=False,
                )

    def test_health_endpoints_distinguish_liveness_and_readiness(self):
        for path in ("/health/live", "/health/ready", "/health"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"status": "ok"})

        with patch.object(
            self.app.state.database,
            "session",
            side_effect=RuntimeError("database-secret"),
        ):
            live = self.client.get("/health/live")
            ready = self.client.get("/health/ready")
            legacy = self.client.get("/health")

        self.assertEqual(live.status_code, 200, live.text)
        self.assertEqual(live.json(), {"status": "ok"})
        for response in (ready, legacy):
            self.assertEqual(response.status_code, 503, response.text)
            self.assertNotIn("database-secret", response.text)

    def test_upload_concurrency_and_file_count_limits_must_be_positive(self):
        settings = (
            ("max_concurrent_upload_parses", "MAX_CONCURRENT_UPLOAD_PARSES"),
            ("max_batch_upload_files", "MAX_BATCH_UPLOAD_FILES"),
        )
        for option, message in settings:
            with self.subTest(option=option), TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaisesRegex(ValueError, message):
                    create_app(
                        database_url=f"sqlite+pysqlite:///{root / 'invalid.db'}",
                        storage_root=root / "storage",
                        auto_migrate_schema=False,
                        **{option: 0},
                    )

    def test_api_timestamps_include_an_explicit_utc_offset(self):
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json()["expires_at"].endswith("Z"))
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        self.upload_active_versions(headers)
        versions = self.client.get(
            "/api/input-versions",
            headers=headers,
        ).json()
        self.assertTrue(
            all(version["created_at"].endswith("Z") for version in versions)
        )

        created = self.client.post(
            "/api/batches",
            headers=headers,
            json={"name": "北京时间边界测试"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertTrue(created.json()["created_at"].endswith("Z"))
        self.assertTrue(created.json()["updated_at"].endswith("Z"))

        logs = self.client.get("/api/audit-logs", headers=headers).json()
        self.assertTrue(all(log["created_at"].endswith("Z") for log in logs))
