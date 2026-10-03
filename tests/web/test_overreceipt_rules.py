from tests.support.web_api import WebApiCase
from io import BytesIO
from unittest.mock import patch


import delivery_note.web.rule_versions as rule_versions_module


class WebApiTests(WebApiCase):
    def test_initial_state_creates_batches_without_overreceipt_rule(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)

        rules = self.client.get(
            "/api/overreceipt-rule-versions",
            headers=admin_headers,
        )
        self.assertEqual(rules.status_code, 200, rules.text)
        self.assertEqual(rules.json(), [])

        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "默认关闭超收"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertIsNone(created.json()["overreceipt_rule"])

        logs = self.client.get("/api/audit-logs", headers=admin_headers).json()
        create_log = next(
            log
            for log in logs
            if log["action"] == "create_batch"
            and log["entity_id"] == str(created.json()["id"])
        )
        self.assertIsNone(create_log["details"]["overreceipt_rule_version_id"])

    def test_overreceipt_warehouses_cache_the_active_purchase_version(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        original_reader = rule_versions_module.read_purchase_workbook

        with patch.object(
            rule_versions_module,
            "read_purchase_workbook",
            wraps=original_reader,
        ) as reader:
            first = self.client.get(
                "/api/overreceipt-rule-versions/warehouses",
                headers=admin_headers,
            )
            second = self.client.get(
                "/api/overreceipt-rule-versions/warehouses",
                headers=admin_headers,
            )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), ["水鞋-广州仓"])
        self.assertEqual(second.json(), first.json())
        self.assertEqual(reader.call_count, 1)

        uploaded = self.client.post(
            "/api/input-versions/purchase",
            headers=admin_headers,
            data={"name": "purchase-v2", "activate": "true"},
            files={
                "file": (
                    "purchase-v2.xlsx",
                    BytesIO(self.workbook_bytes("purchase")),
                )
            },
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

        with patch.object(
            rule_versions_module,
            "read_purchase_workbook",
            wraps=original_reader,
        ) as reader:
            third = self.client.get(
                "/api/overreceipt-rule-versions/warehouses",
                headers=admin_headers,
            )

        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(third.json(), first.json())
        self.assertEqual(reader.call_count, 1)

    def test_operator_can_publish_activate_and_lock_immutable_overreceipt_rules(self):
        admin_headers = self.login("admin", "admin-pass")
        operator = self.create_operator(admin_headers)
        self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")

        warehouses = self.client.get(
            "/api/overreceipt-rule-versions/warehouses",
            headers=operator_headers,
        )
        self.assertEqual(warehouses.status_code, 200, warehouses.text)
        self.assertEqual(warehouses.json(), ["水鞋-广州仓"])

        first = self.client.post(
            "/api/overreceipt-rule-versions",
            headers=operator_headers,
            json={
                "name": "2026-07 短尾放宽",
                "short_tail_limit": 50,
                "medium_tail_limit": 20,
                "long_tail_limit": 10,
                "allowed_warehouses": ["水鞋-广州仓"],
            },
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertTrue(first.json()["active"])
        self.assertEqual(first.json()["created_by"], operator["id"])

        locked_batch = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "锁定超收规则 V1"},
        )
        self.assertEqual(locked_batch.status_code, 201, locked_batch.text)
        self.assertEqual(
            locked_batch.json()["overreceipt_rule"]["id"],
            first.json()["id"],
        )

        second = self.client.post(
            "/api/overreceipt-rule-versions",
            headers=admin_headers,
            json={
                "name": "2026-08 收紧",
                "short_tail_limit": 30,
                "medium_tail_limit": 10,
                "long_tail_limit": 0,
                "allowed_warehouses": [],
            },
        )
        self.assertEqual(second.status_code, 201, second.text)
        self.assertTrue(second.json()["active"])

        versions = self.client.get(
            "/api/overreceipt-rule-versions",
            headers=operator_headers,
        )
        self.assertEqual(versions.status_code, 200, versions.text)
        by_id = {item["id"]: item for item in versions.json()}
        self.assertFalse(by_id[first.json()["id"]]["active"])
        self.assertTrue(by_id[second.json()["id"]]["active"])

        reactivated = self.client.post(
            f"/api/overreceipt-rule-versions/{first.json()['id']}/activate",
            headers=operator_headers,
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.text)
        self.assertTrue(reactivated.json()["active"])

        unchanged_batch = self.client.get(
            f"/api/batches/{locked_batch.json()['id']}",
            headers=operator_headers,
        )
        self.assertEqual(
            unchanged_batch.json()["overreceipt_rule"]["id"],
            first.json()["id"],
        )

        logs = self.client.get("/api/audit-logs", headers=admin_headers).json()
        actions = [log for log in logs if log["entity_type"] == "overreceipt_rule"]
        self.assertEqual(
            [log["action"] for log in actions],
            [
                "activate_overreceipt_rule",
                "publish_overreceipt_rule",
                "publish_overreceipt_rule",
            ],
        )
        self.assertEqual(actions[0]["user_id"], operator["id"])
