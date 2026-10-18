"""场景：官方算价与预算判定 —— 算价失败绝不伪造成交价。"""

from __future__ import annotations

import unittest

from mcfate_core import config, normalize, pricing
from mcfate_core.models import Combo
from tests import fixtures


class JudgeTest(unittest.TestCase):
    def test_failed_quote_stays_unverified(self) -> None:
        verdict = pricing.judge(normalize.normalize_quote(fixtures.QUOTE_FAIL), 35)
        self.assertEqual(verdict["state"], config.PRICE_UNVERIFIED)
        self.assertIsNone(verdict["payable"])
        self.assertIn("门店繁忙", verdict["note"])

    def test_priced_within_budget(self) -> None:
        verdict = pricing.judge(normalize.normalize_quote(fixtures.QUOTE_OK), 35)
        self.assertEqual(verdict["state"], config.PRICE_PRICED)
        self.assertAlmostEqual(verdict["payable"], 26.5)
        self.assertFalse(verdict["over_budget"])

    def test_over_budget_detected(self) -> None:
        verdict = pricing.judge(normalize.normalize_quote(fixtures.QUOTE_OK), 20)
        self.assertEqual(verdict["state"], config.PRICE_OVER_BUDGET)
        self.assertTrue(verdict["over_budget"])
        self.assertIn("超出预算", verdict["note"])

    def test_official_discount_is_surfaced(self) -> None:
        verdict = pricing.judge(normalize.normalize_quote(fixtures.QUOTE_WITH_COUPON), 35)
        self.assertAlmostEqual(verdict["official_discount"], 3.0)
        self.assertAlmostEqual(verdict["payable"], 23.5)


class RerankTest(unittest.TestCase):
    def test_cheapest_priced_wins_and_unverified_goes_last(self) -> None:
        ranked = pricing.rerank(
            [
                {"label": "未核价方案", "quote": normalize.normalize_quote(fixtures.QUOTE_FAIL)},
                {"label": "原价方案", "quote": normalize.normalize_quote(fixtures.QUOTE_OK)},
                {"label": "用券方案", "quote": normalize.normalize_quote(fixtures.QUOTE_WITH_COUPON)},
            ],
            budget=30,
        )
        self.assertEqual([row["label"] for row in ranked], ["用券方案", "原价方案", "未核价方案"])
        self.assertAlmostEqual(ranked[0]["payable"], 23.5)
        self.assertIsNone(ranked[-1]["payable"])

    def test_over_budget_rows_rank_after_affordable_ones(self) -> None:
        ranked = pricing.rerank(
            [
                {"label": "超预算方案", "quote": normalize.normalize_quote(fixtures.QUOTE_OK)},
                {"label": "可成交方案", "quote": normalize.normalize_quote(fixtures.QUOTE_WITH_COUPON)},
            ],
            budget=20,
        )
        self.assertEqual([row["state"] for row in ranked], [config.PRICE_OVER_BUDGET, config.PRICE_OVER_BUDGET])
        # 同样超预算时，金额更低者优先
        self.assertEqual(ranked[0]["label"], "可成交方案")

    def test_priced_beats_unverified_when_both_fit(self) -> None:
        ranked = pricing.rerank(
            [
                {"label": "未核价方案", "quote": normalize.normalize_quote(fixtures.QUOTE_FAIL)},
                {"label": "可成交方案", "quote": normalize.normalize_quote(fixtures.QUOTE_WITH_COUPON)},
            ],
            budget=35,
        )
        self.assertEqual(ranked[0]["label"], "可成交方案")
        self.assertIsNone(ranked[-1]["payable"])


class RequestTest(unittest.TestCase):
    def test_request_matches_calculate_price_schema(self) -> None:
        request = pricing.build_request("1234567", 1, 1, [{"code": "1100", "quantity": 2}], coupon_id="C1")
        self.assertEqual(request["storeCode"], "1234567")
        self.assertEqual(request["items"][0]["productCode"], "1100")
        self.assertEqual(request["items"][0]["quantity"], 2)
        self.assertEqual(request["items"][0]["couponId"], "C1")
        self.assertNotIn("beCode", request)  # 到店自取不传 beCode
        self.assertNotIn("takeWayCode", request)  # calculate-price 无此参数

    def test_price_requests_capped(self) -> None:
        combos = [
            Combo(label=f"组合{i}", items=[{"code": "1100", "name": "巨无霸", "quantity": 1}]) for i in range(20)
        ]
        requests = pricing.price_requests(combos, "1234567", 1, 1, max_calls=6)
        self.assertEqual(len(requests), 6)
        self.assertEqual(requests[0]["with_coupon"]["items"][0]["productCode"], "1100")


if __name__ == "__main__":
    unittest.main()
