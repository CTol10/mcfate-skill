"""场景：硬约束优先级 —— 预算与排除项永远压过游戏得分。"""

from __future__ import annotations

import unittest

from mcfate_core import normalize
from mcfate_core.constraints import Constraints, apply, prioritize_main
from mcfate_core.models import ROLE_DRINK, ROLE_MAIN, ROLE_SIDE
from tests import fixtures


class ConstraintTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = normalize.normalize_menu(fixtures.MENU_RAW)

    def test_budget_filters_out_expensive_items(self) -> None:
        outcome = apply(self.items, Constraints.build(20, []))
        self.assertTrue(all(item.price <= 20 for item in outcome.kept))
        dropped_names = {row["name"] for row in outcome.dropped}
        self.assertIn("巨无霸", dropped_names)
        self.assertIn("超出预算", " ".join(row["reason"] for row in outcome.dropped))

    def test_exclude_terms_match_name_category_and_tags(self) -> None:
        outcome = apply(self.items, Constraints.build(None, ["牛肉", "咖啡"]))
        kept_codes = {item.code for item in outcome.kept}
        self.assertNotIn("4648", kept_codes)  # 名称含牛肉
        self.assertNotIn("1100", kept_codes)  # 标签含 100%纯牛肉
        self.assertNotIn("507411", kept_codes)  # 名称含咖啡

    def test_missing_price_is_kept_but_flagged(self) -> None:
        items = self.items + [normalize.normalize_menu({"items": [{"code": "x", "name": "无价餐品"}]})[0]]
        outcome = apply(items, Constraints.build(20, []))
        self.assertIn("x", outcome.flags)
        self.assertIn("budget_unverified", outcome.flags["x"])

    def test_no_constraints_keeps_everything(self) -> None:
        outcome = apply(self.items, Constraints.build(None, []))
        self.assertEqual(len(outcome.kept), len(self.items))
        self.assertEqual(outcome.dropped, [])

    def test_roles_are_classified(self) -> None:
        by_code = {item.code: item for item in self.items}
        self.assertEqual(by_code["1100"].role, ROLE_MAIN)
        self.assertEqual(by_code["9900008751"].role, ROLE_DRINK)
        self.assertEqual(by_code["4810"].role, ROLE_SIDE)

    def test_sides_are_dropped_when_mains_are_enough(self) -> None:
        outcome = apply(self.items, Constraints.build(None, []))
        kept, notes = prioritize_main(outcome.kept, 3)
        self.assertTrue(all(item.role == ROLE_MAIN for item in kept))
        self.assertTrue(notes)

    def test_sides_kept_when_not_enough_mains(self) -> None:
        outcome = apply(self.items, Constraints.build(None, []))
        kept, notes = prioritize_main(outcome.kept, 50)
        self.assertEqual(len(kept), len(outcome.kept))
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
