import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from delivery_note.purchase_detail_cache import (
    build_purchase_detail_cache,
    evaluate_shadow_cache,
    full_verification_due,
    load_purchase_detail_cache,
    load_purchase_detail_cache_state,
    payload_hash,
    plan_incremental_detail_fetch,
    purchase_cache_source_identity,
    write_purchase_detail_cache,
)


class PurchaseDetailCacheTests(unittest.TestCase):
    def setUp(self):
        self.order = {
            "code": "PO-1",
            "updateTime": "2026-08-26 12:00:00",
            "status": {"id": 3, "name": "待交货"},
        }
        self.detail = {
            "poCode": "PO-1",
            "warehouseProcureItemVos": [{"balanceQuantity": 12}],
        }
        self.identity = purchase_cache_source_identity(
            "https://example.test/",
            "app-id",
        )

    def test_hash_is_independent_of_dictionary_key_order(self):
        reordered = {
            "status": {"name": "待交货", "id": 3},
            "updateTime": "2026-08-26 12:00:00",
            "code": "PO-1",
        }

        self.assertEqual(payload_hash(self.order), payload_hash(reordered))

    def test_shadow_comparison_detects_matching_and_changed_details(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "purchase-details-v1.json"
            payload = build_purchase_detail_cache(
                self.identity,
                [(self.order, self.detail)],
            )
            write_purchase_detail_cache(path, payload)
            cached = load_purchase_detail_cache(path, self.identity)

            matching = evaluate_shadow_cache(
                cached,
                [(dict(self.order), dict(self.detail))],
            )
            changed_detail = {
                **self.detail,
                "warehouseProcureItemVos": [{"balanceQuantity": 11}],
            }
            mismatching = evaluate_shadow_cache(
                cached,
                [(dict(self.order), changed_detail)],
            )
            changed_list = evaluate_shadow_cache(
                cached,
                [
                    (
                        {**self.order, "updateTime": "2026-08-26 12:01:00"},
                        dict(self.detail),
                    )
                ],
            )

        self.assertEqual(matching.comparable_orders, 1)
        self.assertEqual(matching.matching_orders, 1)
        self.assertEqual(matching.mismatched_orders, 0)
        self.assertEqual(mismatching.comparable_orders, 1)
        self.assertEqual(mismatching.mismatched_orders, 1)
        self.assertEqual(changed_list.comparable_orders, 0)

    def test_invalid_cache_and_source_change_are_ignored(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "purchase-details-v1.json"
            payload = build_purchase_detail_cache(
                self.identity,
                [(self.order, self.detail)],
            )
            write_purchase_detail_cache(path, payload)

            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["orders"]["PO-1"]["detail"]["poCode"] = "tampered"
            path.write_text(
                json.dumps(stored, ensure_ascii=False),
                encoding="utf-8",
            )

            self.assertEqual(
                load_purchase_detail_cache(path, self.identity),
                {},
            )

            write_purchase_detail_cache(path, payload)
            self.assertEqual(
                load_purchase_detail_cache(path, "different-source"),
                {},
            )

    def test_duplicate_order_codes_are_not_cached(self):
        payload = build_purchase_detail_cache(
            self.identity,
            [
                (self.order, self.detail),
                (dict(self.order), dict(self.detail)),
            ],
        )
        stats = evaluate_shadow_cache(
            {},
            [
                (self.order, self.detail),
                (dict(self.order), dict(self.detail)),
            ],
        )

        self.assertEqual(payload["orders"], {})
        self.assertEqual(stats.duplicate_orders, 2)

    def test_incremental_plan_samples_ten_percent_and_fetches_changes(self):
        orders = [
            {"code": f"PO-{index}", "updateTime": "2026-08-27 08:00:00"}
            for index in range(127)
        ]
        details = [
            (order, {"poCode": order["code"], "balance": index})
            for index, order in enumerate(orders)
        ]
        cached = build_purchase_detail_cache(self.identity, details)["orders"]

        first = plan_incremental_detail_fetch(orders, cached, "2026-08-27")
        second = plan_incremental_detail_fetch(orders, cached, "2026-08-27")
        changed_orders = [dict(order) for order in orders]
        changed_orders[0]["updateTime"] = "2026-08-27 08:01:00"
        changed = plan_incremental_detail_fetch(
            changed_orders,
            cached,
            "2026-08-27",
        )

        self.assertEqual(len(first.sampled_codes), 13)
        self.assertEqual(len(first.fetch_orders), 13)
        self.assertEqual(len(first.cached_details), 114)
        self.assertEqual(first.sampled_codes, second.sampled_codes)
        self.assertEqual(changed.changed_codes, frozenset({"PO-0"}))
        self.assertEqual(len(changed.fetch_orders), 14)

    def test_daily_full_verification_uses_business_date(self):
        current = datetime(2026, 8, 27, 2, tzinfo=timezone.utc)

        self.assertFalse(
            full_verification_due(
                current - timedelta(hours=3),
                current,
            )
        )
        self.assertTrue(
            full_verification_due(
                current - timedelta(days=1),
                current,
            )
        )

    def test_legacy_cache_creation_time_counts_as_full_verification(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "purchase-details-v1.json"
            payload = build_purchase_detail_cache(
                self.identity,
                [(self.order, self.detail)],
            )
            payload.pop("last_full_verified_at")
            write_purchase_detail_cache(path, payload)

            state = load_purchase_detail_cache_state(path, self.identity)

        self.assertEqual(len(state.orders), 1)
        self.assertIsNotNone(state.last_full_verified_at)


if __name__ == "__main__":
    unittest.main()
