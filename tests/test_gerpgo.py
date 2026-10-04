from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time
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
        body = BytesIO(b'{"code":90008,"messages":["rate limited"],"data":null}')
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


class GerpgoClientTests(unittest.TestCase):
    def test_concurrent_detail_requests_keep_global_start_interval(self):
        started_at = []
        started_at_lock = Lock()

        def post_json(_url, _headers, payload):
            with started_at_lock:
                started_at.append(time.monotonic())
            return {"code": 200, "data": {"poCode": payload["poCode"]}}

        client = GerpgoClient(
            "https://example.test",
            "app",
            "key",
            post_json=post_json,
        )
        client.access_token = "token"

        with ThreadPoolExecutor(max_workers=3) as executor:
            details = list(
                executor.map(
                    client.purchase_order_detail,
                    ["PO-1", "PO-2", "PO-3"],
                )
            )

        self.assertEqual(len(details), 3)
        intervals = [
            current - previous for previous, current in zip(started_at, started_at[1:])
        ]
        self.assertTrue(all(interval >= 0.3 for interval in intervals))

    def test_reads_all_purchase_order_pages_and_detail(self):
        calls = []

        def post_json(url, headers, payload):
            calls.append((url, headers, payload))
            if url.endswith("/api_token"):
                return {"code": 200, "data": {"accessToken": "token"}}
            if url.endswith("/purchase/srm/procure/page"):
                page = payload["pageInfo"]["page"]
                return {
                    "code": 200,
                    "data": {
                        "total": 2,
                        "rows": [{"poCode": f"PO-{page}"}],
                    },
                }
            return {"code": 200, "data": {"poCode": payload["poCode"]}}

        client = GerpgoClient(
            "https://example.test",
            "app",
            "key",
            post_json=post_json,
            sleep=lambda _seconds: None,
            monotonic=lambda: 0,
        )

        orders = client.list_purchase_orders()
        detail = client.purchase_order_detail("PO-1")

        self.assertEqual([order["poCode"] for order in orders], ["PO-1", "PO-2"])
        self.assertEqual(detail["poCode"], "PO-1")
        self.assertEqual(calls[1][2]["invoicesStatusList"], [3, 6])

    def test_rejects_unsuccessful_response(self):
        calls = []
        client = GerpgoClient(
            "https://example.test",
            "app",
            "key",
            post_json=lambda *_args: (
                calls.append(True) or {"code": 500, "messages": ["失败"]}
            ),
        )
        with self.assertRaisesRegex(GerpgoError, "失败"):
            client.authenticate()
        self.assertEqual(len(calls), 1)

    def test_rate_limit_uses_exponential_backoff(self):
        calls = []
        sleeps = []
        current_time = [0.0]

        def sleep(seconds):
            sleeps.append(seconds)
            current_time[0] += seconds

        def post_json(_url, _headers, payload):
            calls.append(payload)
            if len(calls) <= 5:
                return {
                    "code": 90008,
                    "messages": ["接口调用次数已超过限制次数"],
                }
            return {"code": 200, "data": {"poCode": payload["poCode"]}}

        client = GerpgoClient(
            "https://example.test",
            "app",
            "key",
            post_json=post_json,
            sleep=sleep,
            monotonic=lambda: current_time[0],
        )
        client.access_token = "token"

        detail = client.purchase_order_detail("PO-1")

        self.assertEqual(detail["poCode"], "PO-1")
        self.assertEqual(len(calls), 6)
        self.assertEqual(sleeps, [2, 4, 8, 16, 32])

    def test_reads_all_waiting_self_operated_inbound_pages(self):
        calls = []

        def post_json(url, headers, payload):
            calls.append((url, headers, payload))
            if url.endswith("/api_token"):
                return {"code": 200, "data": {"accessToken": "token"}}
            page = payload["page"]
            order_type = payload["orderType"]
            total = 2 if order_type == "purchase" else 1
            return {
                "code": 200,
                "data": {
                    "total": total,
                    "rows": [{"orderNo": f"{order_type}-{page}"}],
                },
            }

        client = GerpgoClient(
            "https://example.test",
            "app",
            "key",
            post_json=post_json,
            sleep=lambda _seconds: None,
            monotonic=lambda: 0,
        )

        rows = client.list_self_operated_inbound_orders()

        self.assertEqual(
            [row["orderNo"] for row in rows],
            ["purchase-1", "purchase-2", "transfer-1"],
        )
        first_payload = calls[1][2]
        self.assertEqual(first_payload["rnType"], "0")
        self.assertEqual(first_payload["orderType"], "purchase")
        self.assertEqual(
            first_payload["orderStatusList"],
            ["WAIT_INBOUND", "PART_INBOUND"],
        )
        self.assertEqual(first_payload["pagesize"], 500)
        transfer_payload = calls[3][2]
        self.assertEqual(transfer_payload["rnType"], "1")
        self.assertEqual(transfer_payload["orderType"], "transfer")


if __name__ == "__main__":
    unittest.main()
