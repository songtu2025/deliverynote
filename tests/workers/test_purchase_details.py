from datetime import datetime
from threading import Lock
import time
import unittest


from delivery_note.workers.purchase_details import (
    _fetch_purchase_order_details,
    _fetch_incremental_purchase_order_details,
)
from delivery_note.purchase_detail_cache import PurchaseDetailCacheState


class WorkerExportConsolidationTests(unittest.TestCase):
    def test_purchase_details_use_eight_workers_and_keep_order(self):
        class DetailClient:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = Lock()

            def purchase_order_detail(self, po_code):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.03)
                with self.lock:
                    self.active -= 1
                return {"poCode": po_code}

        client = DetailClient()
        orders = [{"code": f"PO-{index}"} for index in range(8)]
        progress = []

        details = _fetch_purchase_order_details(
            client,
            orders,
            lambda count, po_code: progress.append((count, po_code)),
        )

        self.assertEqual(client.max_active, 8)
        self.assertEqual(
            [detail[1]["poCode"] for detail in details],
            [order["code"] for order in orders],
        )
        self.assertEqual(
            [count for count, _po_code in progress],
            list(range(1, 9)),
        )

    def test_incremental_details_reuse_cache_and_fallback_on_mismatch(self):
        from datetime import timezone

        from delivery_note.purchase_detail_cache import (
            build_purchase_detail_cache,
        )

        orders = [
            {"code": f"PO-{index}", "updateTime": "2026-08-27 08:00:00"}
            for index in range(20)
        ]
        details = [(order, {"poCode": order["code"], "balance": 1}) for order in orders]
        cached = build_purchase_detail_cache("source", details)["orders"]
        last_full = datetime.now(timezone.utc)

        class StableClient:
            def __init__(self):
                self.calls = []

            def purchase_order_detail(self, po_code):
                self.calls.append(po_code)
                return {"poCode": po_code, "balance": 1}

        stable = StableClient()
        fetched, stats, _ = _fetch_incremental_purchase_order_details(
            stable,
            orders,
            PurchaseDetailCacheState(cached, last_full),
            lambda _count, _code: None,
            last_full,
        )

        self.assertEqual(len(stable.calls), 5)
        self.assertEqual(stats["cache_hit_count"], 15)
        self.assertEqual(stats["sampled_order_count"], 5)
        self.assertFalse(stats["incremental_fallback"])
        self.assertEqual([detail[1]["balance"] for detail in fetched], [1] * 20)

        class MismatchClient:
            def __init__(self):
                self.calls = []
                self.changed = False
                self.lock = Lock()

            def purchase_order_detail(self, po_code):
                with self.lock:
                    self.calls.append(po_code)
                    if not self.changed:
                        self.changed = True
                        return {"poCode": po_code, "balance": 2}
                return {"poCode": po_code, "balance": 1}

        mismatch = MismatchClient()
        fetched, stats, _ = _fetch_incremental_purchase_order_details(
            mismatch,
            orders,
            PurchaseDetailCacheState(cached, last_full),
            lambda _count, _code: None,
            last_full,
        )

        self.assertEqual(len(mismatch.calls), 25)
        self.assertTrue(stats["incremental_fallback"])
        self.assertEqual(stats["sample_mismatch_count"], 1)
        self.assertEqual([detail[1]["balance"] for detail in fetched], [1] * 20)
