from tests.support.worker import WorkerCase
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

import pandas as pd

from delivery_note.web.database import Database
from delivery_note.web.models import (
    InputVersion,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)

from delivery_note.worker import (
    build_parser,
    run_once,
)


class WorkerIntegrationTests(WorkerCase):
    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    @patch("delivery_note.workers.purchase_collection.GerpgoClient.from_config")
    def test_purchase_sync_creates_inactive_candidate(self, client_factory):
        api_client = client_factory.return_value
        api_client.list_purchase_orders.return_value = [
            {"code": "PO-1", "invoicesStatusName": "待交货"}
        ]
        api_client.purchase_order_detail.return_value = {
            "warehouseProcureItemVos": [
                {
                    "procureItemVos": [
                        {
                            "product": "SKU-A",
                            "supplierCode": "GYS-023",
                            "supplierName": "接口供应商",
                            "arrivalMarketName": "共享",
                            "deliveryWarehouseName": "水鞋-广州仓",
                            "balanceQuantity": 12,
                        }
                    ]
                }
            ]
        }

        started = self.client.post(
            "/api/purchase-sync",
            headers=self.headers,
        )
        self.assertEqual(started.status_code, 201, started.text)
        job_id = started.json()["id"]

        completed_id = run_once(self.database_url, self.storage_root)

        self.assertEqual(completed_id, job_id)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                job = session.get(PurchaseSyncJob, job_id)
                self.assertEqual(job.status, "succeeded", job.error_message)
                self.assertIsNotNone(job.candidate_version_id)
                candidate = session.get(
                    InputVersion,
                    job.candidate_version_id,
                )
                self.assertFalse(candidate.active)
                rows = pd.read_excel(candidate.storage_path)
                self.assertEqual(rows.iloc[0]["未交量"], 12)
                self.assertEqual(rows.iloc[0]["供应商"], "接口供应商")
                self.assertEqual(rows.iloc[0]["平台站点"], "共享")
                self.assertEqual(job.issues[0]["code"], "shared_site")
        finally:
            database.dispose()

    @patch.dict(
        "os.environ",
        {
            "GERPGO_API_BASE_URL": "https://example.test",
            "GERPGO_APP_ID": "app",
            "GERPGO_APP_KEY": "key",
        },
    )
    @patch("delivery_note.workers.sync_inbound.GerpgoClient.from_config")
    def test_self_operated_inbound_sync_creates_candidate(self, client_factory):
        client_factory.return_value.list_self_operated_inbound_orders.return_value = [
            {
                "orderNo": "IN-1",
                "orderType": "purchase",
                "orderStatus": "WAIT_INBOUND",
                "warehouseName": "自营仓",
                "purchaseCode": "PO-1",
                "releatedCode": "LN2608179025",
                "supplierName": "KuangBiao",
                "orderItemResultList": [
                    {
                        "sku": "SKU-A",
                        "marketName": "共享",
                        "id": 1001,
                        "sourceItemId": 2001,
                        "releatedItemId": 3001,
                        "arriveNum": 10,
                    }
                ],
            }
        ]
        started = self.client.post(
            "/api/self-operated-inbound-sync",
            headers=self.headers,
        )
        self.assertEqual(started.status_code, 201, started.text)
        job_id = started.json()["id"]

        completed_id = run_once(self.database_url, self.storage_root)

        self.assertEqual(completed_id, job_id)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                job = session.get(SelfOperatedInboundSyncJob, job_id)
                self.assertEqual(job.status, "succeeded", job.error_message)
                candidate = session.get(InputVersion, job.candidate_version_id)
                self.assertFalse(candidate.active)
                rows = pd.read_excel(candidate.storage_path)
                self.assertEqual(rows.iloc[0]["入库单号"], "IN-1")
                self.assertEqual(rows.iloc[0]["平台站点"], "共享")
                self.assertEqual(rows.iloc[0]["积加明细ID"], 1001)
                self.assertEqual(rows.iloc[0]["来源明细ID"], 2001)
                self.assertEqual(rows.iloc[0]["关联明细ID"], 3001)
                self.assertEqual(job.issues[0]["code"], "shared_site")
        finally:
            database.dispose()

    @patch("delivery_note.workers.scheduler._claim_sync_job", return_value=None)
    @patch("delivery_note.workers.scheduler._claim_job")
    def test_inbound_worker_only_claims_inbound_queue(self, claim_batch, claim_sync):
        completed_id = run_once(self.database_url, self.storage_root, "inbound-sync")
        self.assertIsNone(completed_id)
        claim_batch.assert_not_called()
        claim_sync.assert_called_once()
        self.assertIs(claim_sync.call_args.args[1], SelfOperatedInboundSyncJob)

    def test_worker_queue_argument_defaults_to_all(self):
        parser = build_parser()

        self.assertEqual(parser.parse_args([]).queue, "all")
        self.assertEqual(parser.parse_args([]).max_attempts, 3)
        self.assertEqual(
            parser.parse_args(["--queue", "purchase-sync"]).queue,
            "purchase-sync",
        )
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--max-attempts", "0"])
