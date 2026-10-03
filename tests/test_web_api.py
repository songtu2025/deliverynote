from tests.support.web_api import INPUT_KINDS, WebApiCase
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Lock
import unittest
from unittest.mock import patch

from httpx2 import ASGITransport, AsyncClient
import pandas as pd
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

import delivery_note.web.batch_file_uploads as batch_file_uploads_module
import delivery_note.web.batch_preflight as batch_preflight_module
import delivery_note.web.input_version_routes as input_version_routes_module
import delivery_note.web.rule_versions as rule_versions_module
from tests.asgi_client import SyncASGIClient

import delivery_note.web.api as web_api_module
import delivery_note.web.caches as cache_module
from delivery_note.web.api import create_app
from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    InputVersion,
    Job,
    SelfOperatedBatch,
    SplitRecord,
)



class WebApiTests(WebApiCase):



    def test_exception_contract_uses_stable_codes_and_workflow_actions(self):
        exception = ExceptionRecord(
            batch_file_id=1,
            sku="SKU-A",
            original_site="US",
            full_site="AMAZON:SEEKWAY:US",
            destination="",
            delivery_quantity=10,
            allocated_quantity=0,
            manual_quantity=10,
            reason="产品信息站点不唯一",
            status="pending",
        )
        ambiguous = web_api_module._exception_json(
            exception,
            [],
            self_operated=True,
        )
        self.assertEqual(ambiguous["reason_code"], "ambiguous_product_site")
        self.assertEqual(ambiguous["allowed_actions"], ["resolve_site"])

        exception.reason_code = "ambiguous_product_site"
        exception.reason = "更新后的展示文案"
        renamed = web_api_module._exception_json(
            exception,
            [],
            self_operated=True,
        )
        self.assertEqual(renamed["reason_code"], "ambiguous_product_site")
        self.assertEqual(renamed["allowed_actions"], ["resolve_site"])

        exception.reason_code = None
        exception.reason = "历史批次的未知原因"
        unknown = web_api_module._exception_json(
            exception,
            [],
            self_operated=True,
        )
        self.assertEqual(unknown["reason_code"], "unknown")
        self.assertEqual(unknown["allowed_actions"], [])


















    def test_upload_parsing_runs_off_loop_and_obeys_concurrency_limit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                database_url=f"sqlite+pysqlite:///{root / 'parse-limit.db'}",
                storage_root=root / "storage",
                bootstrap_admin=("admin", "admin-pass"),
                max_concurrent_upload_parses=1,
            )
            client = SyncASGIClient(app)
            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin-pass"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            counter_lock = Lock()
            concurrent_parses = Barrier(2)
            active = 0
            maximum_active = 0
            observed_running_loops = []

            def slow_validation(_kind, _path):
                nonlocal active, maximum_active
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    observed_running_loops.append(False)
                else:
                    observed_running_loops.append(True)
                with counter_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    concurrent_parses.wait(timeout=0.3)
                except BrokenBarrierError:
                    pass
                with counter_lock:
                    active -= 1

            async def upload_versions():
                async def keep_event_loop_awake():
                    while True:
                        await asyncio.sleep(0.01)

                heartbeat = asyncio.create_task(keep_event_loop_awake())
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://testserver",
                ) as async_client:
                    try:
                        return await asyncio.gather(
                            *(
                                async_client.post(
                                    f"/api/input-versions/{kind}",
                                    headers=headers,
                                    data={
                                        "name": f"{kind}-threaded",
                                        "activate": "false",
                                    },
                                    files={
                                        "file": (
                                            f"{kind}.xlsx",
                                            BytesIO(b"content"),
                                        )
                                    },
                                )
                                for kind in ("purchase", "product")
                            )
                        )
                    finally:
                        heartbeat.cancel()
                        with suppress(asyncio.CancelledError):
                            await heartbeat

            try:
                with patch.object(
                    input_version_routes_module,
                    "_validate_input_version",
                    side_effect=slow_validation,
                ):
                    responses = asyncio.run(upload_versions())
            finally:
                client.close()
                app.state.database.dispose()

        self.assertTrue(
            all(response.status_code == 201 for response in responses),
            [response.text for response in responses],
        )
        self.assertEqual(observed_running_loops, [False, False])
        self.assertEqual(maximum_active, 1)






















    def test_self_operated_batch_only_requires_its_own_input_versions(self):
        headers = self.login("admin", "admin-pass")
        version_ids = {}
        for kind in ("product", "supplier"):
            response = self.client.post(
                f"/api/input-versions/{kind}",
                headers=headers,
                data={"name": f"{kind}-self-operated", "activate": "true"},
                files={
                    "file": (
                        f"{kind}.xlsx",
                        BytesIO(self.workbook_bytes(kind)),
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            version_ids[kind] = response.json()["id"]

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "不依赖原流程资料的自营仓批次"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )

        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(batch["version_ids"]["product"], version_ids["product"])
        self.assertEqual(batch["version_ids"]["supplier"], version_ids["supplier"])
        self.assertIsNone(batch["version_ids"]["purchase"])
        self.assertIsNone(batch["version_ids"]["position"])
        self.assertIsNone(batch["version_ids"]["template"])
        self.assertIn("inbound_template", batch["versions"])
        self.assertEqual(batch["file_count"], 1)
        self.assertTrue(batch["inbound_file"]["uploaded"])

        delivery_batch = self.client.post(
            "/api/batches",
            headers=headers,
            json={"name": "原流程仍要求完整资料"},
        )
        self.assertEqual(delivery_batch.status_code, 409, delivery_batch.text)
        self.assertIn("purchase", delivery_batch.json()["detail"])
        self.assertIn("position", delivery_batch.json()["detail"])
        self.assertNotIn("template", delivery_batch.json()["detail"])




    def test_admin_refreshes_draft_supplier_version_and_alias_preflight_passes(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        operator_headers = self.login("operator", "operator-pass")
        original_ids = self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "供应商别名批次"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]

        replacement = self.client.post(
            "/api/input-versions/supplier",
            headers=admin_headers,
            data={"name": "supplier-alias-v2", "activate": "true"},
            files={
                "file": (
                    "supplier-alias.xlsx",
                    BytesIO(
                        self.supplier_workbook_bytes(
                            [["STGYS001", "RUIZY", "启用", "瑞智雅|RIVBOS"]]
                        )
                    ),
                )
            },
        )
        self.assertEqual(replacement.status_code, 201, replacement.text)
        replacement_id = replacement.json()["id"]
        self.assertNotEqual(original_ids["supplier"], replacement_id)

        forbidden = self.client.post(
            f"/api/batches/{batch_id}/refresh-supplier-version",
            headers=operator_headers,
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        refreshed = self.client.post(
            f"/api/batches/{batch_id}/refresh-supplier-version",
            headers=admin_headers,
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["version_ids"]["supplier"], replacement_id)
        self.assertEqual(refreshed.json()["versions"]["supplier"]["id"], replacement_id)

        upload = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={
                "file": (
                    "260903-瑞智雅RIVBOS眼镜交货单-发货53箱 (1).xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=admin_headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")

        logs = self.client.get("/api/audit-logs", headers=admin_headers).json()
        refresh_log = next(
            log
            for log in logs
            if log["action"] == "refresh_batch_supplier_version"
            and log["entity_id"] == str(batch_id)
        )
        self.assertEqual(
            refresh_log["details"],
            {
                "previous_supplier_version_id": original_ids["supplier"],
                "supplier_version_id": replacement_id,
            },
        )

    def test_supplier_refresh_rejects_non_draft_and_missing_active_version(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "刷新状态限制"},
        )
        batch_id = created.json()["id"]

        for batch_status in ("running", "failed", "succeeded"):
            with self.subTest(status=batch_status):
                with self.app.state.database.session() as session:
                    batch = session.get(Batch, batch_id)
                    batch.status = batch_status
                    session.commit()
                response = self.client.post(
                    f"/api/batches/{batch_id}/refresh-supplier-version",
                    headers=admin_headers,
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("仅草稿状态", response.json()["detail"])

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "draft"
            for version in session.scalars(
                select(InputVersion).where(InputVersion.kind == "supplier")
            ):
                version.active = False
            session.commit()
        missing = self.client.post(
            f"/api/batches/{batch_id}/refresh-supplier-version",
            headers=admin_headers,
        )
        self.assertEqual(missing.status_code, 409, missing.text)
        self.assertIn("没有启用的供应商资料", missing.json()["detail"])

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

    def test_self_operated_batch_locks_rule_and_accepts_an_appended_delivery(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        template = self.client.post(
            "/api/input-versions/inbound_template",
            headers=headers,
            data={"name": "inbound-template-v1", "activate": "true"},
            files={
                "file": (
                    "inbound-template.xlsx",
                    BytesIO(self.workbook_bytes("inbound_template")),
                )
            },
        )
        self.assertEqual(template.status_code, 201, template.text)
        rule = self.client.post(
            "/api/self-operated-overreceipt-rule-versions",
            headers=headers,
            json={"name": "自营仓超收 5 件", "allowance": 5},
        )
        self.assertEqual(rule.status_code, 201, rule.text)

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "自营仓入库接口测试"},
            files={
                "delivery_file": (
                    "260817-狂飙-质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        batch_id = batch["id"]
        self.assertEqual(batch["workflow"], "self_operated_inbound")
        self.assertEqual(batch["self_operated_overreceipt_rule"]["allowance"], 5)
        self.assertEqual(
            batch["versions"]["inbound_template"]["id"],
            template.json()["id"],
        )
        self.assertEqual(batch["file_count"], 1)
        self.assertTrue(batch["inbound_file"]["uploaded"])
        listed_batch = next(
            item
            for item in self.client.get("/api/batches", headers=headers).json()
            if item["id"] == batch_id
        )
        self.assertEqual(
            listed_batch,
            {key: batch[key] for key in listed_batch},
        )
        self.app.state.max_batch_upload_files = 2
        extra_file = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={
                "file": (
                    "260817-狂飙-额外质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                )
            },
        )
        self.assertEqual(extra_file.status_code, 201, extra_file.text)
        self.assertEqual(extra_file.json()["file_order"], 2)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")
        self.assertEqual(preflight.json()["file_count"], 2)

    def test_self_operated_creation_accepts_repeated_delivery_file_fields(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "多质检单批次"},
            files=[
                (
                    "delivery_file",
                    (
                        "260817-狂飙-A质检交货单.xlsx",
                        BytesIO(self.self_operated_delivery_bytes(8)),
                    ),
                ),
                (
                    "delivery_file",
                    (
                        "260817-狂飙-B质检交货单.xlsx",
                        BytesIO(self.self_operated_delivery_bytes(7)),
                    ),
                ),
                (
                    "inbound_file",
                    (
                        "自营仓收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    ),
                ),
            ],
        )

        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(batch["file_count"], 2)
        self.assertEqual(
            [
                (source["original_name"], source["file_order"])
                for source in batch["files"]
            ],
            [
                ("260817-狂飙-A质检交货单.xlsx", 1),
                ("260817-狂飙-B质检交货单.xlsx", 2),
            ],
        )

    def test_self_operated_multi_file_creation_is_atomic_on_validation_failure(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        invalid = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "多质检单原子失败"},
            files=[
                (
                    "delivery_file",
                    (
                        "260817-狂飙-A质检交货单.xlsx",
                        BytesIO(self.self_operated_delivery_bytes()),
                    ),
                ),
                (
                    "delivery_file",
                    ("260817-狂飙-B质检交货单.xlsx", BytesIO(b"invalid")),
                ),
                (
                    "inbound_file",
                    (
                        "自营仓收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    ),
                ),
            ],
        )

        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(self.client.get("/api/batches", headers=headers).json(), [])
        temporary_root = (
            self.app.state.storage_root / "temporary" / "self-operated-batches"
        )
        self.assertEqual(list(temporary_root.glob("*")), [])

    def test_self_operated_creation_rejects_duplicate_names_and_file_limit(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        duplicate_files = [
            (
                "delivery_file",
                ("同名质检单.xlsx", BytesIO(self.self_operated_delivery_bytes())),
            ),
            (
                "delivery_file",
                ("同名质检单.xlsx", BytesIO(self.self_operated_delivery_bytes())),
            ),
            (
                "inbound_file",
                (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            ),
        ]

        duplicate = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "同名失败"},
            files=duplicate_files,
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertIn("同名", duplicate.json()["detail"])

        self.app.state.max_batch_upload_files = 1
        limited = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "数量超限"},
            files=[
                (
                    "delivery_file",
                    ("A.xlsx", BytesIO(self.self_operated_delivery_bytes())),
                ),
                (
                    "delivery_file",
                    ("B.xlsx", BytesIO(self.self_operated_delivery_bytes())),
                ),
                (
                    "inbound_file",
                    (
                        "自营仓收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    ),
                ),
            ],
        )
        self.assertEqual(limited.status_code, 413, limited.text)
        self.assertEqual(self.client.get("/api/batches", headers=headers).json(), [])

    def test_self_operated_preflight_validates_every_delivery_file(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "逐份预检"},
            files={
                "delivery_file": (
                    "260817-狂飙-A质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        batch_id = created.json()["id"]
        appended = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={"file": ("第二份损坏.xlsx", BytesIO(b"invalid"))},
        )
        self.assertEqual(appended.status_code, 201, appended.text)

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=headers,
        )

        self.assertEqual(preflight.status_code, 400, preflight.text)
        self.assertIn("第二份", preflight.json()["detail"])

    def test_inbound_replacement_succeeds_when_old_file_cleanup_fails(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "入库单清理失败"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "旧入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        with self.app.state.database.session() as session:
            old_path = Path(
                session.get(SelfOperatedBatch, batch_id).inbound_storage_path
            )

        original_unlink = Path.unlink

        def fail_old_file_cleanup(path, *args, **kwargs):
            if path == old_path:
                raise PermissionError("denied")
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=fail_old_file_cleanup,
            ),
            self.assertLogs("delivery_note.web.api", level="WARNING"),
        ):
            replaced = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=headers,
                files={
                    "file": (
                        "新入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    )
                },
            )

        self.assertEqual(replaced.status_code, 200, replaced.text)
        with self.app.state.database.session() as session:
            profile = session.get(SelfOperatedBatch, batch_id)
            self.assertEqual(profile.inbound_original_name, "新入库单.xlsx")
            self.assertNotEqual(Path(profile.inbound_storage_path), old_path)
            self.assertTrue(Path(profile.inbound_storage_path).is_file())
        self.assertTrue(old_path.is_file())

    def test_self_operated_creation_is_atomic_when_file_validation_fails(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        invalid = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "校验失败的自营仓批次"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": ("异常入库单.xlsx", BytesIO(b"not-an-excel-file")),
            },
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)

        batches = self.client.get("/api/batches", headers=headers)
        self.assertEqual(batches.status_code, 200, batches.text)
        self.assertEqual(batches.json(), [])
        temporary_root = (
            self.app.state.storage_root / "temporary" / "self-operated-batches"
        )
        self.assertEqual(list(temporary_root.glob("*")), [])

    def test_delivery_creation_with_files_is_atomic(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        invalid = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "校验失败的交货批次"},
            files={"files": ("异常交货单.xlsx", BytesIO(b"not-an-excel-file"))},
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(
            self.client.get("/api/batches", headers=headers).json(),
            [],
        )
        temporary_root = (
            self.app.state.storage_root / "temporary" / "delivery-batches"
        )
        self.assertEqual(list(temporary_root.glob("*")), [])

        created = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "带文件创建的交货批次"},
            files={"files": ("交货单.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["file_count"], 1)

    def test_single_file_delete_succeeds_when_file_cleanup_fails(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "单文件清理失败"},
            files={"files": ("交货单.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        source_id = created.json()["files"][0]["id"]
        with self.app.state.database.session() as session:
            storage_path = Path(session.get(BatchFile, source_id).storage_path)

        with (
            patch.object(Path, "unlink", side_effect=PermissionError("denied")),
            self.assertLogs("delivery_note.web.api", level="WARNING"),
        ):
            deleted = self.client.delete(
                f"/api/batches/{batch_id}/files/{source_id}",
                headers=headers,
            )

        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["file_count"], 0)
        with self.app.state.database.session() as session:
            self.assertIsNone(session.get(BatchFile, source_id))
            self.assertEqual(session.get(Batch, batch_id).status, "draft")
        self.assertTrue(storage_path.is_file())

    def test_delivery_creation_rejects_too_many_files_before_writing(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        self.app.state.max_batch_upload_files = 1

        response = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "文件过多"},
            files=[
                ("files", ("one.xlsx", BytesIO(self.delivery_bytes()))),
                ("files", ("two.xlsx", BytesIO(self.delivery_bytes()))),
            ],
        )

        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn("最多上传 1 份", response.json()["detail"])
        self.assertEqual(
            self.client.get("/api/batches", headers=headers).json(),
            [],
        )
        temporary_root = (
            self.app.state.storage_root / "temporary" / "delivery-batches"
        )
        self.assertFalse(temporary_root.exists())

    def test_empty_delivery_drafts_are_removed_without_touching_uploaded_batches(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        empty = self.client.post(
            "/api/batches",
            headers=headers,
            json={"name": "应被清理的空交货批次"},
        )
        self.assertEqual(empty.status_code, 201, empty.text)
        created = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "保留的交货批次"},
            files={"files": ("交货单.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(created.status_code, 201, created.text)

        cleaned = self.client.delete("/api/batches/empty", headers=headers)
        self.assertEqual(cleaned.status_code, 200, cleaned.text)
        self.assertEqual(cleaned.json()["deleted_ids"], [empty.json()["id"]])
        batches = self.client.get("/api/batches", headers=headers)
        self.assertEqual(
            [batch["name"] for batch in batches.json()],
            ["保留的交货批次"],
        )

    def test_empty_self_operated_drafts_are_removed_without_touching_ready_batches(
        self,
    ):
        headers = self.login("admin", "admin-pass")
        version_ids = self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "保留的自营仓批次"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)

        with self.app.state.database.session() as session:
            empty = Batch(
                name="应被清理的空批次",
                created_by=1,
                purchase_version_id=None,
                product_version_id=version_ids["product"],
                supplier_version_id=version_ids["supplier"],
                position_version_id=None,
                template_version_id=None,
            )
            session.add(empty)
            session.flush()
            session.add(
                SelfOperatedBatch(
                    batch_id=empty.id,
                    template_version_id=created.json()["versions"]["inbound_template"][
                        "id"
                    ],
                )
            )
            session.commit()
            empty_id = empty.id

        cleaned = self.client.delete(
            "/api/self-operated-batches/empty",
            headers=headers,
        )
        self.assertEqual(cleaned.status_code, 200, cleaned.text)
        self.assertEqual(cleaned.json()["deleted_ids"], [empty_id])

        batches = self.client.get("/api/batches", headers=headers)
        self.assertEqual(batches.status_code, 200, batches.text)
        self.assertEqual(
            [batch["name"] for batch in batches.json()], ["保留的自营仓批次"]
        )

    def test_admin_can_delete_multiple_batches_and_owned_files(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        delivery = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "delete-delivery-batch"},
            files={"files": ("delivery.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(delivery.status_code, 201, delivery.text)
        self_operated = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "delete-self-operated-batch"},
            files={
                "delivery_file": (
                    "quality-delivery.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "self-operated-inbound.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(self_operated.status_code, 201, self_operated.text)
        batch_ids = [delivery.json()["id"], self_operated.json()["id"]]
        batch_directories = [
            self.root / "storage" / "batches" / str(batch_id) for batch_id in batch_ids
        ]
        self.assertTrue(all(path.is_dir() for path in batch_directories))

        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == batch_ids[0])
            )
            exception = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-A",
                delivery_quantity=1,
                allocated_quantity=0,
                manual_quantity=1,
                reason="delete-test",
            )
            session.add(exception)
            session.flush()
            session.add(SplitRecord(exception_id=exception.id, quantity=1))
            session.add(
                Job(
                    batch_id=batch_ids[0],
                    kind="compute",
                    status="succeeded",
                )
            )
            session.commit()

        deleted = self.client.request(
            "DELETE",
            "/api/batches",
            headers=headers,
            json={"batch_ids": batch_ids},
        )

        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["deleted_ids"], batch_ids)
        self.assertEqual(deleted.json()["file_cleanup_failed_ids"], [])
        self.assertTrue(all(not path.exists() for path in batch_directories))
        self.assertEqual(
            self.client.get("/api/batches", headers=headers).json(),
            [],
        )

    def test_batch_delete_is_admin_only_and_rejects_active_batch_atomically(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        first = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "keep-batch"},
        ).json()
        active = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "running-batch"},
        ).json()
        with self.app.state.database.session() as session:
            session.get(Batch, active["id"]).status = "running"
            session.commit()

        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")
        forbidden = self.client.request(
            "DELETE",
            "/api/batches",
            headers=operator_headers,
            json={"batch_ids": [first["id"]]},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        blocked = self.client.request(
            "DELETE",
            "/api/batches",
            headers=admin_headers,
            json={"batch_ids": [first["id"], active["id"]]},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("running-batch", blocked.json()["detail"])
        remaining_ids = [
            batch["id"]
            for batch in self.client.get(
                "/api/batches",
                headers=admin_headers,
            ).json()
        ]
        self.assertEqual(set(remaining_ids), {first["id"], active["id"]})

    def test_batch_delete_rejects_active_export_job_atomically(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        first = self.client.post(
            "/api/batches", headers=headers, json={"name": "keep-batch"}
        ).json()
        exporting = self.client.post(
            "/api/batches", headers=headers, json={"name": "exporting-batch"}
        ).json()
        with self.app.state.database.session() as session:
            session.get(Batch, exporting["id"]).status = "succeeded"
            session.add(Job(batch_id=exporting["id"], kind="export", status="queued"))
            session.commit()

        for job_status in ("queued", "running"):
            with self.app.state.database.session() as session:
                job = session.scalar(
                    select(Job).where(Job.batch_id == exporting["id"])
                )
                job.status = job_status
                session.commit()
            blocked = self.client.request(
                "DELETE",
                "/api/batches",
                headers=headers,
                json={"batch_ids": [first["id"], exporting["id"]]},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(
                {batch["id"] for batch in self.client.get(
                    "/api/batches", headers=headers
                ).json()},
                {first["id"], exporting["id"]},
            )

        with self.app.state.database.session() as session:
            job = session.scalar(select(Job).where(Job.batch_id == exporting["id"]))
            job.status = "succeeded"
            session.commit()
        deleted = self.client.request(
            "DELETE",
            "/api/batches",
            headers=headers,
            json={"batch_ids": [first["id"], exporting["id"]]},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_preflight_rejects_file_order_changed_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        batch_id = self.client.post(
            "/api/batches", headers=headers, json={"name": "预检并发测试"}
        ).json()["id"]
        file_ids = []
        for name in (
            "260717-狂飙-A交货单.xlsx",
            "260717-狂飙-B交货单.xlsx",
        ):
            response = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=headers,
                files={"file": (name, BytesIO(self.delivery_bytes()))},
            )
            self.assertEqual(response.status_code, 201, response.text)
            file_ids.append(response.json()["id"])

        original_reader = batch_preflight_module.read_delivery_workbook
        reordered = False

        def read_and_reorder(path):
            nonlocal reordered
            if not reordered:
                reordered = True
                response = self.client.put(
                    f"/api/batches/{batch_id}/files/order",
                    headers=headers,
                    json={"file_ids": list(reversed(file_ids))},
                )
                self.assertEqual(response.status_code, 200, response.text)
            return original_reader(path)

        with patch.object(
            batch_preflight_module, "read_delivery_workbook",
            side_effect=read_and_reorder,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=headers)
            .json()["status"],
            "draft",
        )
        compute = self.client.post(
            f"/api/batches/{batch_id}/compute", headers=headers
        )
        self.assertEqual(compute.status_code, 409, compute.text)

    def test_preflight_rejects_file_removed_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        batch_id = self.client.post(
            "/api/batches", headers=headers, json={"name": "预检删除测试"}
        ).json()["id"]
        uploaded = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={
                "file": (
                    "260717-狂飙-A交货单.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        ).json()
        original_reader = batch_preflight_module.read_delivery_workbook

        def read_and_remove(path):
            removed = self.client.delete(
                f"/api/batches/{batch_id}/files/{uploaded['id']}",
                headers=headers,
            )
            self.assertEqual(removed.status_code, 200, removed.text)
            return original_reader(path)

        with patch.object(
            batch_preflight_module, "read_delivery_workbook",
            side_effect=read_and_remove,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=headers)
            .json()["status"],
            "draft",
        )

    def test_preflight_rejects_inbound_replacement_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "自营仓预检并发测试"},
            files={
                "delivery_file": (
                    "260817-狂飙-质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        original_reader = batch_preflight_module.read_self_operated_delivery_workbook

        def read_and_replace(path):
            result = original_reader(path)
            replaced = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=headers,
                files={
                    "file": (
                        "更新后的收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    )
                },
            )
            self.assertEqual(replaced.status_code, 200, replaced.text)
            return result

        with patch.object(
            batch_preflight_module,
            "read_self_operated_delivery_workbook",
            side_effect=read_and_replace,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        batch = self.client.get(f"/api/batches/{batch_id}", headers=headers).json()
        self.assertEqual(batch["status"], "draft")
        self.assertEqual(
            batch["inbound_file"]["original_name"], "更新后的收货入库单.xlsx"
        )



    def test_versions_batch_order_preflight_and_compute_job(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        version_ids = self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")

        created = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "7 月交货批次"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(batch["version_ids"], version_ids)
        self.assertEqual(
            {kind: item["name"] for kind, item in batch["versions"].items()},
            {kind: f"{kind}-v1" for kind in INPUT_KINDS},
        )
        self.assertEqual(batch["jobs"], {})
        batch_id = batch["id"]

        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={
                "file": (
                    "260717-狂飙-A交货单-发货10箱.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        duplicate = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={
                "file": (
                    "260717-狂飙-A交货单-发货10箱.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        second = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={
                "file": (
                    "260717-狂飙-B交货单-发货20箱.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(second.status_code, 201, second.text)

        reordered = self.client.put(
            f"/api/batches/{batch_id}/files/order",
            headers=operator_headers,
            json={"file_ids": [second.json()["id"], first.json()["id"]]},
        )
        self.assertEqual(reordered.status_code, 200, reordered.text)
        self.assertEqual(
            [item["id"] for item in reordered.json()["files"]],
            [second.json()["id"], first.json()["id"]],
        )

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=operator_headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")

        first_start = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=operator_headers,
        )
        second_start = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=operator_headers,
        )
        self.assertEqual(first_start.status_code, 202, first_start.text)
        self.assertEqual(second_start.status_code, 202, second_start.text)
        self.assertEqual(first_start.json()["id"], second_start.json()["id"])
        self.assertEqual(first_start.json()["status"], "queued")
        job = self.client.get(
            f"/api/jobs/{first_start.json()['id']}",
            headers=operator_headers,
        )
        self.assertEqual(job.status_code, 200, job.text)
        self.assertEqual(job.json()["kind"], "compute")
        refreshed = self.client.get(
            f"/api/batches/{batch_id}", headers=operator_headers
        ).json()
        self.assertEqual(refreshed["jobs"]["compute"]["id"], job.json()["id"])
        self.assertEqual(refreshed["jobs"]["compute"]["status"], "queued")

    def test_batch_reads_bulk_load_exception_splits(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "批量读取测试"},
        ).json()["id"]

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "succeeded"
            source = BatchFile(
                batch_id=batch_id,
                original_name="批量读取测试.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
                supplier_name="KuangBiao",
                supplier_code="GYS-023",
                delivery_total=10,
                import_total=0,
                manual_total=10,
                import_rows=[],
            )
            session.add(source)
            session.flush()
            for index in range(10):
                exception = ExceptionRecord(
                    batch_file_id=source.id,
                    sku="SKU-A",
                    original_site="US",
                    full_site="AMAZON:SEEKWAY:US",
                    destination="水鞋-广州仓",
                    delivery_quantity=1,
                    allocated_quantity=0,
                    manual_quantity=1,
                    reason=f"批量读取测试 {index}",
                    status="resolved",
                )
                session.add(exception)
                session.flush()
                session.add(
                    SplitRecord(
                        exception_id=exception.id,
                        quantity=1,
                        destination="水鞋-广州仓",
                        site="AMAZON:SEEKWAY:US",
                        supplier_code="GYS-023",
                        sku="SKU-A",
                        resolved=True,
                    )
                )
            session.commit()

        loaded_exceptions = []

        def record_loaded(_session, instance):
            if isinstance(instance, (ExceptionRecord, SplitRecord)):
                loaded_exceptions.append(instance)

        event.listen(Session, "loaded_as_persistent", record_loaded)
        try:
            detail, detail_queries = self.get_with_query_count(
                f"/api/batches/{batch_id}",
                admin_headers,
            )
            listed, list_queries = self.get_with_query_count(
                "/api/batches",
                admin_headers,
            )
        finally:
            event.remove(Session, "loaded_as_persistent", record_loaded)
        self.assertEqual(loaded_exceptions, [])
        original_reader = cache_module.read_position_workbook
        with patch.object(
            cache_module,
            "read_position_workbook",
            wraps=original_reader,
        ) as reader:
            exceptions, exception_queries = self.get_with_query_count(
                f"/api/batches/{batch_id}/exceptions",
                admin_headers,
            )
            repeated_exceptions = self.client.get(
                f"/api/batches/{batch_id}/exceptions",
                headers=admin_headers,
            )

        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(exceptions.status_code, 200, exceptions.text)
        self.assertEqual(
            repeated_exceptions.status_code,
            200,
            repeated_exceptions.text,
        )
        self.assertEqual(detail.json()["summary"]["import_total"], 10)
        listed_batch = next(
            batch for batch in listed.json() if batch["id"] == batch_id
        )
        self.assertEqual(
            listed_batch,
            {key: detail.json()[key] for key in listed_batch},
        )
        self.assertEqual(len(exceptions.json()), 10)
        self.assertEqual(repeated_exceptions.json(), exceptions.json())
        self.assertEqual(reader.call_count, 1)
        self.assertLessEqual(detail_queries, 15)
        self.assertLessEqual(list_queries, 8)
        self.assertLessEqual(exception_queries, 8)

        loaded_page_records = []

        def record_page(_session, instance):
            if isinstance(instance, (ExceptionRecord, SplitRecord)):
                loaded_page_records.append(instance)

        event.listen(Session, "loaded_as_persistent", record_page)
        try:
            page, page_queries = self.get_with_query_count(
                f"/api/batches/{batch_id}/exceptions?offset=2&limit=3",
                admin_headers,
            )
        finally:
            event.remove(Session, "loaded_as_persistent", record_page)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 10)
        self.assertEqual(len(page.json()["items"]), 3)
        self.assertEqual(
            sum(isinstance(record, ExceptionRecord) for record in loaded_page_records),
            3,
        )
        self.assertEqual(
            sum(isinstance(record, SplitRecord) for record in loaded_page_records),
            3,
        )
        self.assertEqual(page.json()["stats"]["resolved_count"], 10)
        self.assertLessEqual(page_queries, 10)

        filtered = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&review_scope=unfinished",
            headers=admin_headers,
        )
        self.assertEqual(filtered.json()["total"], 0)
        self.assertEqual(filtered.json()["stats"]["total_count"], 10)

        reason = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&reason=批量读取测试 4",
            headers=admin_headers,
        )
        self.assertEqual(reason.json()["total"], 1)
        self.assertEqual(reason.json()["items"][0]["reason"], "批量读取测试 4")

        filters = self.client.get(
            f"/api/batches/{batch_id}/exceptions/filters",
            headers=admin_headers,
        )
        self.assertEqual(filters.status_code, 200, filters.text)
        self.assertEqual(len(filters.json()["reasons"]), 10)
        self.assertEqual(filters.json()["sites"], ["AMAZON:SEEKWAY:US"])
        self.assertEqual(filters.json()["scales"], ["短尾"])
        self.assertEqual(filters.json()["stocking"], ["备货"])

        by_position = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&scale_position=短尾",
            headers=admin_headers,
        )
        self.assertEqual(by_position.json()["total"], 10)
        self.assertEqual(len(by_position.json()["items"]), 3)

        by_position_search = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3&search=短尾",
            headers=admin_headers,
        )
        self.assertEqual(by_position_search.json()["total"], 10)
        position_page = self.client.get(
            f"/api/batches/{batch_id}/exceptions"
            "?offset=3&limit=3&search=短尾&scale_position=短尾",
            headers=admin_headers,
        )
        self.assertEqual(position_page.json()["total"], 10)
        self.assertEqual(
            [item["reason"] for item in position_page.json()["items"]],
            [f"批量读取测试 {index}" for index in range(3, 6)],
        )

        invalid = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=201",
            headers=admin_headers,
        )
        self.assertEqual(invalid.status_code, 422)

        first_exception_id = exceptions.json()[0]["id"]
        with self.app.state.database.session() as session:
            first_exception = session.get(ExceptionRecord, first_exception_id)
            first_exception.status = "pending"
            session.execute(
                delete(SplitRecord).where(
                    SplitRecord.exception_id == first_exception_id
                )
            )
            session.commit()
        updated = self.client.get(
            f"/api/batches/{batch_id}/exceptions?limit=3",
            headers=admin_headers,
        )
        self.assertEqual(updated.json()["stats"]["unfinished_count"], 1)
        self.assertEqual(updated.json()["stats"]["unfinished_quantity"], 1)
        self.assertEqual(updated.json()["stats"]["resolved_count"], 9)

    def test_unpaged_lists_reject_more_than_200_items_without_truncation(self):
        headers = self.login("admin", "admin-pass")
        version_ids = self.upload_active_versions(headers)
        with self.app.state.database.session() as session:
            session.add_all(
                Batch(
                    name=f"批次 {index}",
                    created_by=1,
                    **{
                        f"{kind}_version_id": version_id
                        for kind, version_id in version_ids.items()
                    },
                )
                for index in range(201)
            )
            session.commit()

        unpaged = self.client.get("/api/batches", headers=headers)
        self.assertEqual(unpaged.status_code, 422)
        self.assertIn("分页", unpaged.json()["detail"])
        paged = self.client.get("/api/batches?limit=200", headers=headers)
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(paged.json()["total"], 201)
        self.assertEqual(len(paged.json()["items"]), 200)

        with self.app.state.database.session() as session:
            batch = session.query(Batch).first()
            source = BatchFile(
                batch_id=batch.id,
                original_name="测试.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
            )
            session.add(source)
            session.flush()
            session.add_all(
                ExceptionRecord(
                    batch_file_id=source.id,
                    sku=f"SKU-{index}",
                    delivery_quantity=1,
                    allocated_quantity=0,
                    manual_quantity=1,
                    reason="未找到可交货采购需求",
                )
                for index in range(601)
            )
            session.commit()

        unpaged = self.client.get(
            f"/api/batches/{batch.id}/exceptions", headers=headers
        )
        self.assertEqual(unpaged.status_code, 422)
        self.assertIn("分页", unpaged.json()["detail"])
        paged = self.client.get(
            f"/api/batches/{batch.id}/exceptions?limit=200", headers=headers
        )
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(paged.json()["total"], 601)
        self.assertEqual(len(paged.json()["items"]), 200)

        searched = self.client.get(
            f"/api/batches/{batch.id}/exceptions?search=SKU", headers=headers
        )
        self.assertEqual(searched.status_code, 422)
        stream_sizes = []

        def record_stream(execute_state):
            if size := execute_state.execution_options.get("yield_per"):
                stream_sizes.append(size)

        event.listen(Session, "do_orm_execute", record_stream)
        try:
            searched_page = self.client.get(
                f"/api/batches/{batch.id}/exceptions?search=SKU&limit=200",
                headers=headers,
            )
        finally:
            event.remove(Session, "do_orm_execute", record_stream)
        self.assertEqual(searched_page.status_code, 200)
        self.assertEqual(searched_page.json()["total"], 601)
        self.assertEqual(stream_sizes, [200])
        last_page = self.client.get(
            f"/api/batches/{batch.id}/exceptions"
            "?search=SKU&offset=600&limit=10",
            headers=headers,
        )
        self.assertEqual(last_page.json()["total"], 601)
        self.assertEqual(
            [item["sku"] for item in last_page.json()["items"]],
            ["SKU-600"],
        )

    def test_batch_list_query_count_is_constant_as_batches_grow(self):
        admin_headers = self.login("admin", "admin-pass")
        version_ids = self.upload_active_versions(admin_headers)

        def add_batch(index: int) -> None:
            with self.app.state.database.session() as session:
                batch = Batch(
                    name=f"批次 {index}",
                    status="succeeded",
                    created_by=1,
                    purchase_version_id=version_ids["purchase"],
                    product_version_id=version_ids["product"],
                    supplier_version_id=version_ids["supplier"],
                    position_version_id=version_ids["position"],
                    template_version_id=version_ids["template"],
                )
                session.add(batch)
                session.flush()
                source = BatchFile(
                    batch_id=batch.id,
                    original_name=f"批次 {index}.xlsx",
                    storage_path=f"unused-{index}.xlsx",
                    file_order=1,
                    delivery_total=5,
                    import_total=2,
                    manual_total=3,
                    import_rows=[],
                )
                session.add(source)
                session.flush()
                exception = ExceptionRecord(
                    batch_file_id=source.id,
                    sku="SKU-A",
                    delivery_quantity=3,
                    allocated_quantity=0,
                    manual_quantity=3,
                    reason="数量超出采购余额",
                    status="resolved",
                )
                session.add(exception)
                session.flush()
                session.add_all(
                    [
                        SplitRecord(
                            exception_id=exception.id,
                            quantity=2,
                            destination="水鞋-广州仓",
                            site="AMAZON:SEEKWAY:US",
                            supplier_code="GYS-023",
                            sku="SKU-A",
                            resolved=True,
                        ),
                        SplitRecord(
                            exception_id=exception.id,
                            quantity=1,
                            sku="SKU-A",
                            resolved=False,
                        ),
                    ]
                )
                session.commit()

        add_batch(1)
        single, single_queries = self.get_with_query_count(
            "/api/batches",
            admin_headers,
        )
        for index in range(2, 11):
            add_batch(index)
        multiple, multiple_queries = self.get_with_query_count(
            "/api/batches",
            admin_headers,
        )

        self.assertEqual(single.status_code, 200, single.text)
        self.assertEqual(multiple.status_code, 200, multiple.text)
        self.assertEqual(single_queries, multiple_queries)
        self.assertLessEqual(multiple_queries, 8)
        self.assertEqual(
            [batch["name"] for batch in multiple.json()],
            [f"批次 {index}" for index in range(10, 0, -1)],
        )
        for batch in multiple.json():
            self.assertEqual(
                batch["summary"],
                {
                    "delivery_total": 5,
                    "import_total": 4,
                    "manual_total": 1,
                    "conserved": True,
                },
            )

        page, page_queries = self.get_with_query_count(
            "/api/batches?workflow=delivery&offset=2&limit=3",
            admin_headers,
        )
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 10)
        self.assertEqual(page.json()["empty_draft_count"], 0)
        self.assertEqual(
            [batch["name"] for batch in page.json()["items"]],
            ["批次 8", "批次 7", "批次 6"],
        )
        self.assertTrue(all(
            batch["summary"]["conserved"] for batch in page.json()["items"]
        ))
        self.assertLessEqual(page_queries, 9)

        searched = self.client.get(
            "/api/batches?workflow=delivery&search=批次 1&limit=3",
            headers=admin_headers,
        )
        self.assertEqual(searched.json()["total"], 2)
        self.assertEqual(
            [batch["name"] for batch in searched.json()["items"]],
            ["批次 10", "批次 1"],
        )
        invalid = self.client.get(
            "/api/batches?limit=201", headers=admin_headers
        )
        self.assertEqual(invalid.status_code, 422)

    def test_position_frame_cache_evicts_least_recent_version(self):
        cache = cache_module.PositionFrameCache(max_entries=2)
        loaded_versions = []

        def read_frame(path):
            version_id = int(path.stem)
            loaded_versions.append(version_id)
            return pd.DataFrame({"version_id": [version_id]})

        with patch.object(
            cache_module,
            "read_position_workbook",
            side_effect=read_frame,
        ):
            first_frame = cache.get(1, Path("1.xlsx"))
            cache.get(2, Path("2.xlsx"))
            self.assertIs(cache.get(1, Path("1.xlsx")), first_frame)
            cache.get(3, Path("3.xlsx"))
            cache.get(2, Path("2.xlsx"))

        self.assertEqual(loaded_versions, [1, 2, 3, 2])

    def test_position_frame_cache_serializes_concurrent_misses(self):
        cache = cache_module.PositionFrameCache(max_entries=2)
        concurrent_reads = Barrier(2)

        def read_frame(_path):
            try:
                concurrent_reads.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
            return pd.DataFrame({"version_id": [1]})

        with patch.object(
            cache_module,
            "read_position_workbook",
            side_effect=read_frame,
        ) as reader:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(cache.get, 1, Path("1.xlsx")) for _ in range(2)
                ]
                frames = [future.result(timeout=5) for future in futures]

        self.assertEqual(reader.call_count, 1)
        self.assertIs(frames[0], frames[1])

    def test_concurrent_batch_uploads_get_distinct_contiguous_orders(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "并发上传排序测试"},
        ).json()["id"]
        saved_uploads = Barrier(2)
        original_save_upload = batch_file_uploads_module._save_upload

        async def synchronized_save_upload(*args, **kwargs):
            await original_save_upload(*args, **kwargs)
            saved_uploads.wait(timeout=5)

        def upload(filename: str):
            return self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=admin_headers,
                files={"file": (filename, BytesIO(self.delivery_bytes()))},
            )

        filenames = ("KuangBiao-A.xlsx", "KuangBiao-B.xlsx")
        with (
            patch.object(
                batch_file_uploads_module,
                "_save_upload",
                new=synchronized_save_upload,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            responses = list(executor.map(upload, filenames))

        self.assertEqual(
            [response.status_code for response in responses],
            [201, 201],
            [response.text for response in responses],
        )
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=admin_headers
        ).json()
        self.assertEqual(
            [item["file_order"] for item in batch["files"]],
            [1, 2],
        )
        self.assertEqual(
            {item["original_name"] for item in batch["files"]},
            set(filenames),
        )

    def test_batch_file_limit_rejects_append_before_writing(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "普通追加数量上限"},
        ).json()["id"]
        self.app.state.max_batch_upload_files = 1
        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={"file": ("first.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(first.status_code, 201, first.text)
        input_root = self.app.state.storage_root / "batches" / str(batch_id) / "inputs"
        files_before = set(input_root.iterdir())

        with patch.object(
            batch_file_uploads_module,
            "_save_upload",
            wraps=batch_file_uploads_module._save_upload,
        ) as save_upload:
            rejected = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=admin_headers,
                files={"file": ("second.xlsx", BytesIO(self.delivery_bytes()))},
            )

        self.assertEqual(rejected.status_code, 413, rejected.text)
        self.assertIn("最多上传 1 份", rejected.json()["detail"])
        save_upload.assert_not_awaited()
        self.assertEqual(set(input_root.iterdir()), files_before)
        with self.app.state.database.session() as session:
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            ).all()
        self.assertEqual([source.original_name for source in sources], ["first.xlsx"])

    def test_concurrent_batch_appends_enforce_file_limit_after_writing(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "并发追加数量上限"},
        ).json()["id"]
        self.app.state.max_batch_upload_files = 1
        saved_uploads = Barrier(2)
        original_save_upload = batch_file_uploads_module._save_upload

        async def synchronized_save_upload(*args, **kwargs):
            await original_save_upload(*args, **kwargs)
            saved_uploads.wait(timeout=5)

        def upload(filename: str):
            return self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=admin_headers,
                files={"file": (filename, BytesIO(self.delivery_bytes()))},
            )

        with (
            patch.object(
                batch_file_uploads_module,
                "_save_upload",
                new=synchronized_save_upload,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            responses = list(executor.map(upload, ("first.xlsx", "second.xlsx")))

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [201, 413],
            [response.text for response in responses],
        )
        rejected = next(
            response for response in responses if response.status_code == 413
        )
        self.assertIn("最多上传 1 份", rejected.json()["detail"])
        input_root = self.app.state.storage_root / "batches" / str(batch_id) / "inputs"
        self.assertEqual(len(list(input_root.iterdir())), 1)
        with self.app.state.database.session() as session:
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            ).all()
        self.assertEqual(len(sources), 1)

    def test_delivery_file_can_be_deleted_before_compute(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        batch_id = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "文件纠错测试"},
        ).json()["id"]
        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={
                "file": ("260717-狂飙-A交货单.xlsx", BytesIO(self.delivery_bytes()))
            },
        ).json()
        second = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={
                "file": ("260717-狂飙-B交货单.xlsx", BytesIO(self.delivery_bytes()))
            },
        ).json()
        with self.app.state.database.session() as session:
            removed_path = Path(session.get(BatchFile, second["id"]).storage_path)
        self.assertTrue(removed_path.is_file())

        deleted = self.client.request(
            "DELETE",
            f"/api/batches/{batch_id}/files/{second['id']}",
            headers=admin_headers,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["status"], "draft")
        self.assertEqual(
            [(item["id"], item["file_order"]) for item in deleted.json()["files"]],
            [(first["id"], 1)],
        )
        self.assertFalse(removed_path.exists())

        self.client.post(f"/api/batches/{batch_id}/preflight", headers=admin_headers)
        self.client.post(f"/api/batches/{batch_id}/compute", headers=admin_headers)
        blocked = self.client.request(
            "DELETE",
            f"/api/batches/{batch_id}/files/{first['id']}",
            headers=admin_headers,
        )
        self.assertEqual(blocked.status_code, 409)

    def test_preflight_rejects_invalid_excel_content(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "无效预检"},
        )
        batch_id = created.json()["id"]
        uploaded = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={"file": ("260717-狂飙-A交货单-发货10箱.xlsx", BytesIO(b"invalid"))},
        )
        self.assertEqual(uploaded.status_code, 201)

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=admin_headers,
        )
        self.assertEqual(preflight.status_code, 400)
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=admin_headers
        ).json()
        self.assertEqual(batch["status"], "draft")

    def test_split_review_is_quantity_safe_and_invalidates_export(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")
        batch_id = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "拆分测试"},
        ).json()["id"]

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "succeeded"
            source = BatchFile(
                batch_id=batch_id,
                original_name="260717-狂飙-A交货单-发货10箱.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
                supplier_name="KuangBiao",
                supplier_code="GYS-023",
                delivery_total=40,
                import_total=0,
                manual_total=40,
                document_note="260717-狂飙-01-10箱",
                import_rows=[],
            )
            session.add(source)
            session.flush()
            exception = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-A",
                original_site="US",
                full_site="AMAZON:SEEKWAY:US",
                destination="水鞋-广州仓",
                delivery_quantity=40,
                allocated_quantity=0,
                manual_quantity=40,
                reason="超出采购未交量",
                status="pending",
            )
            session.add(exception)
            session.commit()
            exception_id = exception.id

        invalid = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={"parts": [{"quantity": 39, "resolved": False}]},
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={
                "parts": [
                    {"quantity": 25, "destination": "仓A", "resolved": True},
                    {"quantity": 15, "destination": "仓B", "resolved": False},
                ]
            },
        )
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["status"], "partial")
        self.assertEqual(valid.json()["reason_code"], "purchase_balance_exceeded")
        self.assertEqual(valid.json()["allowed_actions"], ["split"])
        self.assertEqual(
            [part["quantity"] for part in valid.json()["parts"]],
            [25, 15],
        )
        batch_after_split = self.client.get(
            f"/api/batches/{batch_id}", headers=operator_headers
        ).json()
        summary = batch_after_split["summary"]
        self.assertEqual(
            (
                summary["delivery_total"],
                summary["import_total"],
                summary["manual_total"],
            ),
            (40, 25, 15),
        )
        self.assertEqual(
            (
                batch_after_split["files"][0]["import_total"],
                batch_after_split["files"][0]["manual_total"],
            ),
            (25, 15),
        )

        export = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=operator_headers,
        )
        repeated = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=operator_headers,
        )
        self.assertEqual(export.status_code, 202, export.text)
        self.assertEqual(export.json()["id"], repeated.json()["id"])
        blocked_split = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={"parts": [{"quantity": 40, "resolved": False}]},
        )
        self.assertEqual(blocked_split.status_code, 409)


if __name__ == "__main__":
    unittest.main()
