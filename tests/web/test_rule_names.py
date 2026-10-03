from tests.support.web_api import WebApiCase


class WebApiTests(WebApiCase):
    def test_rule_version_names_can_change_without_changing_locked_rules(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        first = self.client.post(
            "/api/overreceipt-rule-versions",
            headers=headers,
            json={
                "name": "交货超收旧名称",
                "short_tail_limit": 50,
                "medium_tail_limit": 20,
                "long_tail_limit": 10,
                "allowed_warehouses": ["水鞋-广州仓"],
            },
        )
        self.assertEqual(first.status_code, 201, first.text)
        locked_batch = self.client.post(
            "/api/batches",
            headers=headers,
            json={"name": "规则名称修改验收"},
        )
        self.assertEqual(locked_batch.status_code, 201, locked_batch.text)
        second = self.client.post(
            "/api/overreceipt-rule-versions",
            headers=headers,
            json={
                "name": "交货超收当前名称",
                "short_tail_limit": 30,
                "medium_tail_limit": 10,
                "long_tail_limit": 0,
                "allowed_warehouses": [],
            },
        )
        self.assertEqual(second.status_code, 201, second.text)

        renamed = self.client.put(
            f"/api/overreceipt-rule-versions/{first.json()['id']}/name",
            headers=headers,
            json={"name": " 交货超收新名称 "},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["id"], first.json()["id"])
        self.assertEqual(renamed.json()["name"], "交货超收新名称")
        self.assertEqual(renamed.json()["short_tail_limit"], 50)
        self.assertEqual(renamed.json()["medium_tail_limit"], 20)
        self.assertEqual(renamed.json()["long_tail_limit"], 10)
        self.assertEqual(
            renamed.json()["allowed_warehouses"],
            ["水鞋-广州仓"],
        )
        self.assertFalse(renamed.json()["active"])

        locked = self.client.get(
            f"/api/batches/{locked_batch.json()['id']}",
            headers=headers,
        )
        self.assertEqual(locked.status_code, 200, locked.text)
        self.assertEqual(
            locked.json()["overreceipt_rule"]["id"],
            first.json()["id"],
        )
        self.assertEqual(
            locked.json()["overreceipt_rule"]["name"],
            "交货超收新名称",
        )
        self.assertEqual(
            locked.json()["overreceipt_rule"]["short_tail_limit"],
            50,
        )

        duplicate = self.client.put(
            f"/api/overreceipt-rule-versions/{first.json()['id']}/name",
            headers=headers,
            json={"name": second.json()["name"]},
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        blank = self.client.put(
            f"/api/overreceipt-rule-versions/{first.json()['id']}/name",
            headers=headers,
            json={"name": "   "},
        )
        self.assertEqual(blank.status_code, 400, blank.text)

        self_operated = self.client.post(
            "/api/self-operated-overreceipt-rule-versions",
            headers=headers,
            json={"name": "自营仓旧名称", "allowance": 5},
        )
        self.assertEqual(self_operated.status_code, 201, self_operated.text)
        renamed_self_operated = self.client.put(
            "/api/self-operated-overreceipt-rule-versions/"
            f"{self_operated.json()['id']}/name",
            headers=headers,
            json={"name": "自营仓新名称"},
        )
        self.assertEqual(
            renamed_self_operated.status_code,
            200,
            renamed_self_operated.text,
        )
        self.assertEqual(
            renamed_self_operated.json()["id"],
            self_operated.json()["id"],
        )
        self.assertEqual(
            renamed_self_operated.json()["name"],
            "自营仓新名称",
        )
        self.assertEqual(renamed_self_operated.json()["allowance"], 5)

        logs = self.client.get("/api/audit-logs", headers=headers).json()
        rename_actions = {
            log["action"]: log for log in logs if log["action"].startswith("rename_")
        }
        self.assertEqual(
            set(rename_actions),
            {
                "rename_overreceipt_rule",
                "rename_self_operated_overreceipt_rule",
            },
        )
        self.assertEqual(
            rename_actions["rename_overreceipt_rule"]["details"],
            {"before": "交货超收旧名称", "after": "交货超收新名称"},
        )
