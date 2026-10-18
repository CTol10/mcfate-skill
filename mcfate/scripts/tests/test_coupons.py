"""场景：优惠券调度 —— 门槛、加购成本、节省归属，全部只认官方数据。"""

from __future__ import annotations

import unittest

from mcfate_core import config, coupons as coupon_lib, normalize
from tests import fixtures


class CouponCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        rows, _status, _note = normalize.normalize_coupons(fixtures.COUPONS_RAW)
        self.by_id = {coupon.coupon_id: coupon for coupon in rows}

    def test_not_applicable_when_product_mismatch(self) -> None:
        check = coupon_lib.check(self.by_id["C3"], ["1100"], 26.5)
        self.assertEqual(check.status, config.COUPON_NOT_APPLICABLE)
        self.assertFalse(check.applicable)

    def test_needs_extra_when_threshold_not_reached(self) -> None:
        check = coupon_lib.check(self.by_id["C1"], ["1100"], 26.5)
        self.assertEqual(check.status, config.COUPON_NEEDS_EXTRA)
        self.assertAlmostEqual(check.extra_needed or 0, 3.5)
        self.assertIn("还差", check.note)

    def test_usable_when_threshold_reached(self) -> None:
        check = coupon_lib.check(self.by_id["C1"], ["1100"], 30.0)
        self.assertEqual(check.status, config.COUPON_USABLE)

    def test_coupon_without_metadata_is_unverified(self) -> None:
        raw = {"data": [{"title": "神秘券", "couponId": "X"}]}
        rows, status, _note = normalize.normalize_coupons(raw)
        self.assertEqual(status, "ok")
        check = coupon_lib.check(rows[0], ["1100"], 26.5)
        self.assertEqual(check.status, config.COUPON_UNVERIFIED)
        self.assertIsNone(check.applicable)

    def test_threshold_is_reported_as_assumed_unit(self) -> None:
        self.assertTrue(self.by_id["C1"].unit_assumed)


class SavingsAttributionTest(unittest.TestCase):
    def test_requires_two_successful_quotes(self) -> None:
        with_quote = normalize.normalize_quote(fixtures.QUOTE_WITH_COUPON)
        without_quote = normalize.normalize_quote(fixtures.QUOTE_OK)
        saving, verified = coupon_lib.attribute_savings(with_quote, without_quote)
        self.assertTrue(verified)
        self.assertAlmostEqual(saving or 0, 3.0)

    def test_failed_quote_blocks_savings_claim(self) -> None:
        with_quote = normalize.normalize_quote(fixtures.QUOTE_FAIL)
        without_quote = normalize.normalize_quote(fixtures.QUOTE_OK)
        saving, verified = coupon_lib.attribute_savings(with_quote, without_quote)
        self.assertFalse(verified)
        self.assertIsNone(saving)

    def test_different_baskets_cannot_be_compared(self) -> None:
        with_quote = normalize.normalize_quote(fixtures.QUOTE_WITH_COUPON)
        other = {
            "success": True,
            "code": 200,
            "data": {
                "price": 1450,
                "discount": 0,
                "productList": [{"productCode": "1700", "quantity": 1, "subtotal": 1450}],
            },
        }
        saving, verified = coupon_lib.attribute_savings(with_quote, normalize.normalize_quote(other))
        self.assertFalse(verified)
        self.assertIsNone(saving)


class ComboSuggestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = normalize.normalize_menu(fixtures.MENU_RAW)
        self.coupons, _status, _note = normalize.normalize_coupons(fixtures.COUPONS_RAW)

    def test_filler_added_to_reach_threshold(self) -> None:
        combos, _notes = coupon_lib.suggest_combos(self.coupons, self.items, budget=50)
        target = next(combo for combo in combos if combo.coupon and combo.coupon.coupon_id == "C1")
        self.assertGreaterEqual((target.estimated_subtotal or 0), 30)
        self.assertTrue(any("加购" in note for note in target.notes))

    def test_budget_blocks_unaffordable_top_up(self) -> None:
        combos, _notes = coupon_lib.suggest_combos(self.coupons, self.items, budget=30)
        target = next(combo for combo in combos if combo.coupon and combo.coupon.coupon_id == "C1")
        self.assertLess((target.estimated_subtotal or 0), 30)
        self.assertTrue(any("无法凑到门槛" in note for note in target.notes))

    def test_no_coupons_still_returns_clear_note(self) -> None:
        combos, notes = coupon_lib.suggest_combos([], self.items, budget=35)
        self.assertEqual(combos, [])
        self.assertTrue(any("没有可用的结构化券" in note for note in notes))

    def test_coupon_not_in_menu_is_skipped(self) -> None:
        raw = {"data": [{"title": "店外券", "couponId": "Z", "products": [{"productCode": "999999"}]}]}
        rows, _status, _note = normalize.normalize_coupons(raw)
        combos, notes = coupon_lib.suggest_combos(rows, self.items, budget=35)
        self.assertEqual(combos, [])
        self.assertTrue(any("不在当前菜单" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
