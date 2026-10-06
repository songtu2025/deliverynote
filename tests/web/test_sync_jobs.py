from tests.support.web_api import WebApiCase
from unittest.mock import patch


from delivery_note.web.models import (
    InputVersion,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)


class WebApiTests(WebApiCase):
    def test_sync_issue_download_error_contracts(self) -> None:
        headers = self.login("admin", "admin-pass")
        empty_issues: tuple[list[dict[str, object]] | None, ...] = (None, [])
        for prefix, model, missing, empty in (
            (
                "purchase-sync",
                PurchaseSyncJob,
                "采购同步任务不存在",
                "当前任务没有待处理问题",
            ),
            (
                "self-operated-inbound-sync",
                SelfOperatedInboundSyncJob,
                "待入库同步任务不存在",
                "当前任务没有异常数据",
            ),
        ):
            with self.subTest(prefix=prefix):
                response = self.client.get(
                    f"/api/{prefix}/999/issues/download", headers=headers
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": missing})
            for issues in empty_issues:
                with self.subTest(prefix=prefix, issues=issues):
                    with self.app.state.database.session() as session:
                        job = model(status="succeeded", created_by=1, issues=issues)
                        session.add(job)
                        session.commit()
                        job_id = job.id
                    response = self.client.get(
                        f"/api/{prefix}/{job_id}/issues/download", headers=headers
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), {"detail": empty})

    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    def test_purchase_sync_does_not_require_product_or_supplier_information(self):
        admin_headers = self.login("admin", "admin-pass")
        started = self.client.post(
            "/api/purchase-sync",
            headers=admin_headers,
        )

        self.assertEqual(started.status_code, 201, started.text)
        self.assertIsNone(started.json()["product_version_id"])
        self.assertIsNone(started.json()["supplier_version_id"])

    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    def test_operator_can_start_purchase_sync(self):
        admin_headers = self.login("admin", "admin-pass")
        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")

        started = self.client.post(
            "/api/purchase-sync",
            headers=operator_headers,
        )

        self.assertEqual(started.status_code, 201, started.text)
        self.assertEqual(started.json()["status"], "queued")
        status_response = self.client.get(
            "/api/purchase-sync",
            headers=operator_headers,
        )
        self.assertEqual(status_response.status_code, 200, status_response.text)
        self.assertEqual(status_response.json()["job"]["id"], started.json()["id"])

    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    def test_operator_can_start_self_operated_inbound_sync(self):
        admin_headers = self.login("admin", "admin-pass")
        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")

        started = self.client.post(
            "/api/self-operated-inbound-sync",
            headers=operator_headers,
        )

        self.assertEqual(started.status_code, 201, started.text)
        self.assertEqual(started.json()["status"], "queued")
        self.assertIsNone(started.json()["base_version_id"])
        current = self.client.get(
            "/api/self-operated-inbound-sync",
            headers=operator_headers,
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["job"]["id"], started.json()["id"])
        self.assertIsNone(current.json()["active_version"])

    def test_sync_routes_require_authentication(self):
        routes = (
            ("get", "/api/purchase-sync"),
            ("post", "/api/purchase-sync"),
            ("get", "/api/purchase-sync/1/issues"),
            ("get", "/api/purchase-sync/1/issues/download"),
            ("get", "/api/purchase-sync/1/preview"),
            ("get", "/api/self-operated-inbound-sync"),
            ("post", "/api/self-operated-inbound-sync"),
            ("get", "/api/self-operated-inbound-sync/1/issues"),
            ("get", "/api/self-operated-inbound-sync/1/issues/download"),
            ("get", "/api/self-operated-inbound-sync/1/preview"),
            ("post", "/api/self-operated-inbound-sync/1/activate"),
        )
        for method, path in routes:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 401, response.text)

    def test_operator_can_activate_self_operated_sync_candidate(self):
        admin_headers = self.login("admin", "admin-pass")
        candidate_path = self.root / "self-operated-activation.xlsx"
        candidate_path.write_bytes(self.self_operated_inbound_bytes())
        with self.app.state.database.session() as session:
            version = InputVersion(
                kind="self_operated_inbound",
                name="待入库候选版本",
                original_name=candidate_path.name,
                storage_path=str(candidate_path),
                active=False,
                created_by=1,
            )
            session.add(version)
            session.flush()
            job = SelfOperatedInboundSyncJob(
                status="succeeded",
                created_by=1,
                candidate_version_id=version.id,
            )
            session.add(job)
            session.commit()
            job_id = job.id
            version_id = version.id

        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")
        candidate_path.unlink()
        missing = self.client.post(
            f"/api/self-operated-inbound-sync/{job_id}/activate",
            headers=operator_headers,
        )
        self.assertEqual(missing.status_code, 409, missing.text)
        current = self.client.get(
            "/api/self-operated-inbound-sync", headers=operator_headers
        )
        self.assertIsNone(current.json()["active_version"])
        candidate_path.write_bytes(self.self_operated_inbound_bytes())
        activated = self.client.post(
            f"/api/self-operated-inbound-sync/{job_id}/activate",
            headers=operator_headers,
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json()["id"], version_id)
        self.assertTrue(activated.json()["active"])
        current = self.client.get(
            "/api/self-operated-inbound-sync",
            headers=operator_headers,
        )
        self.assertEqual(current.json()["active_version"]["id"], version_id)
