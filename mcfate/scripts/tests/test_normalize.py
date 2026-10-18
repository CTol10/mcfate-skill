"""场景：接口返回归一化 —— 缺字段不猜、失败不崩。"""

from __future__ import annotations

import unittest

from mcfate_core import normalize
from tests import fixtures


class MenuNormalizeTest(unittest.TestCase):
    def test_parses_raw_query_meals(self) -> None:
        items = normalize.normalize_menu(fixtures.MENU_RAW)
        self.assertEqual(len(items), 8)
        big_mac = next(item for item in items if item.code == "1100")
        self.assertEqual(big_mac.name, "巨无霸")
        self.assertAlmostEqual(big_mac.price, 26.5)
        self.assertEqual(big_mac.category, "巨无霸牛鱼肉堡")  # 跳过营销位，取真实分类
        self.assertIn("100%纯牛肉", big_mac.tags)

    def test_item_without_category_falls_back(self) -> None:
        items = normalize.normalize_menu(fixtures.MENU_RAW)
        moon_burger = next(item for item in items if item.code == "521900")
        self.assertEqual(moon_burger.category, "未分类")

    def test_compact_menu_supported(self) -> None:
        raw = {"items": [{"code": "1", "name": "测试堡", "price": 12.5, "category": "汉堡"}]}
        items = normalize.normalize_menu(raw)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0].price, 12.5)

    def test_failed_envelope_returns_empty(self) -> None:
        self.assertEqual(normalize.normalize_menu({"success": False, "message": "门店已打烊"}), [])
        self.assertEqual(normalize.normalize_menu(None), [])

    def test_price_string_cleaning(self) -> None:
        self.assertAlmostEqual(normalize.to_float("¥33.5"), 33.5)
        self.assertIsNone(normalize.to_float("价格待定"))
        self.assertIsNone(normalize.to_float(True))


class QuoteNormalizeTest(unittest.TestCase):
    def test_ok_quote_converts_cents_to_yuan(self) -> None:
        quote = normalize.normalize_quote(fixtures.QUOTE_OK)
        self.assertTrue(quote.ok)
        self.assertAlmostEqual(quote.payable, 26.5)
        self.assertEqual(quote.take_way[0]["code"], "eat-in")

    def test_failed_quote_never_produces_price(self) -> None:
        quote = normalize.normalize_quote(fixtures.QUOTE_FAIL)
        self.assertFalse(quote.ok)
        self.assertIsNone(quote.payable)
        self.assertIn("门店繁忙", quote.error or "")

    def test_garbage_quote_is_unverified(self) -> None:
        quote = normalize.normalize_quote({"success": True, "code": 200, "data": {}})
        self.assertFalse(quote.ok)
        self.assertIsNone(quote.payable)

    def test_text_response_is_unverified(self) -> None:
        self.assertFalse(normalize.normalize_quote("算好了，一共 26.5 元").ok)


class CouponNormalizeTest(unittest.TestCase):
    def test_parses_coupons_and_optional_threshold(self) -> None:
        coupons, status, _note = normalize.normalize_coupons(fixtures.COUPONS_RAW)
        self.assertEqual(status, "ok")
        self.assertEqual(len(coupons), 3)
        by_id = {coupon.coupon_id: coupon for coupon in coupons}
        self.assertAlmostEqual(by_id["C1"].threshold, 30.0)
        self.assertTrue(by_id["C1"].unit_assumed)
        self.assertIsNone(by_id["C2"].threshold)  # 接口没给就是未知，不许补默认值
        self.assertEqual(by_id["C2"].product_codes, ("1100",))

    def test_empty_coupon_list(self) -> None:
        coupons, status, note = normalize.normalize_coupons({"success": True, "data": []})
        self.assertEqual(coupons, [])
        self.assertEqual(status, "empty")
        self.assertIn("没有", note)

    def test_natural_language_response_is_unparsed(self) -> None:
        coupons, status, _note = normalize.normalize_coupons("暂无可用优惠券")
        self.assertEqual(coupons, [])
        self.assertEqual(status, "unparsed")

    def test_tool_error_is_reported(self) -> None:
        _coupons, status, note = normalize.normalize_coupons({"success": False, "message": "服务不可用"})
        self.assertEqual(status, "error")
        self.assertIn("服务不可用", note)


if __name__ == "__main__":
    unittest.main()
