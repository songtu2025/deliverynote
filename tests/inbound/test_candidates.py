from delivery_note.self_operated_inbound import (
    process_self_operated_inbound,
)


from tests.support.inbound import InboundAllocationCase


class InboundCandidatesTests(InboundAllocationCase):
    def test_product_mapping_uses_locked_product_site_not_brand(self) -> None:
        inbound = self.inbound([{}])

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            self.products(),
            inbound,
            "Yu feng",
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.pending_total, 0)
        self.assertEqual(
            result.allocation_rows.iloc[0]["平台站点"],
            "AMAZON:RIVMOUNT:US",
        )

    def test_inbound_candidate_resolves_multiple_locked_product_sites(self) -> None:
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SIMARI:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            products,
            self.inbound([{}]),
            "Yu feng",
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.pending_total, 0)
        self.assertEqual(
            result.allocation_rows.iloc[0]["平台站点"],
            "AMAZON:RIVMOUNT:US",
        )

    def test_missing_delivery_number_rejects_partial_matching(self) -> None:
        inbound = self.inbound([{}])

        with self.assertRaisesRegex(ValueError, "缺少交货单号.*9012"):
            process_self_operated_inbound(
                self.delivery(20),
                ("LN2608179011", "LN2608179012"),
                self.products(),
                inbound,
                "Yu feng",
            )

    def test_multiple_inbound_candidates_stay_pending_for_manual_selection(
        self,
    ) -> None:
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            products,
            self.inbound(
                [
                    {},
                    {
                        "入库单号": "WV-2",
                        "平台站点": "AMAZON:SEEKWAY:US",
                    },
                ]
            ),
            "Yu feng",
        )

        self.assertEqual(result.import_total, 0)
        self.assertEqual(result.pending_total, 20)
        self.assertEqual(
            result.pending_rows.iloc[0]["待处理原因"],
            "产品信息站点不唯一",
        )
        self.assertEqual(
            set(result.pending_rows.iloc[0]["完整站点"].split("、")),
            {"AMAZON:RIVMOUNT:US", "AMAZON:SEEKWAY:US"},
        )

    def test_manual_site_selection_recomputes_allocation(self) -> None:
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )
        inbound = self.inbound(
            [
                {},
                {
                    "入库单号": "WV-2",
                    "平台站点": "AMAZON:SEEKWAY:US",
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            products,
            inbound,
            "Yu feng",
            site_overrides={
                ("SKU-A", "US"): "AMAZON:SEEKWAY:US",
            },
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.pending_total, 0)
        self.assertEqual(
            result.allocation_rows.iloc[0]["平台站点"],
            "AMAZON:SEEKWAY:US",
        )

    def test_manual_site_selection_must_use_filtered_candidate(self) -> None:
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )
        inbound = self.inbound(
            [
                {},
                {
                    "入库单号": "WV-2",
                    "平台站点": "AMAZON:SEEKWAY:US",
                },
            ]
        )

        with self.assertRaisesRegex(ValueError, "人工选择站点不在候选范围"):
            process_self_operated_inbound(
                self.delivery(20),
                ("LN2608179011",),
                products,
                inbound,
                "Yu feng",
                site_overrides={("SKU-A", "US"): "AMAZON:SIMARI:US"},
            )
