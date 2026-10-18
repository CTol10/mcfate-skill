"""渲染层测试：重点是回合结构，不是文案。

游戏感的核心约束有两条，必须被锁住：
1. 动作（就它了 / 再来一个 / 换个口味）在每个回合里只出现一次；
2. 揭晓与摆盘是两种不同结构，不能混用。
"""

from __future__ import annotations

import unittest

from mcfate_core import render
from mcfate_core.models import Candidate, MenuItem, Score


def make_candidate(code: str = "1100", name: str = "巨无霸", price=26.0, reasons=None, gaps=None) -> Candidate:
    item = MenuItem(code=code, name=name, price=price, original_price=None, category="巨无霸牛鱼肉堡")
    score = Score(components={"novelty": 0.5}, total=0.5, reasons=list(reasons or []), data_gaps=list(gaps or []))
    return Candidate(item=item, score=score)


class SignNoTest(unittest.TestCase):
    def test_is_deterministic(self) -> None:
        self.assertEqual(render.sign_no(2026, "1100"), render.sign_no(2026, "1100"))

    def test_within_three_digits(self) -> None:
        for code in ("1100", "1700", "521952", "9900015602"):
            for seed in (1, 2026, 999999):
                number = render.sign_no(seed, code)
                self.assertTrue(100 <= int(number) <= 999, f"{seed}/{code} -> {number}")

    def test_differs_by_seed_or_code(self) -> None:
        self.assertNotEqual(render.sign_no(2026, "1100"), render.sign_no(2027, "1100"))
        self.assertNotEqual(render.sign_no(2026, "1100"), render.sign_no(2026, "1700"))


class ActionsTest(unittest.TestCase):
    def test_reveal_and_board_both_offer_three_actions(self) -> None:
        self.assertEqual(len(render.actions_for("reveal")), 3)
        self.assertEqual(len(render.actions_for("board")), 3)

    def test_unknown_turn_falls_back_to_board(self) -> None:
        self.assertEqual(render.actions_for("nonsense"), render.actions_for("board"))

    def test_labels_are_unique_within_a_turn(self) -> None:
        for turn in ("reveal", "board"):
            labels = [action["label"] for action in render.actions_for(turn)]
            self.assertEqual(len(labels), len(set(labels)))

    def test_returns_copies_so_callers_cannot_corrupt_registry(self) -> None:
        first = render.actions_for("reveal")
        first[0]["label"] = "被改了"
        self.assertEqual(render.actions_for("reveal")[0]["label"], "就它了")


class RevealBlockTest(unittest.TestCase):
    def test_opens_with_ceremony_line_per_style(self) -> None:
        for style, opening in render.REVEAL_OPENING.items():
            block = render.reveal_block(make_candidate(), 35, 2026, style)
            self.assertEqual(block["lines"][0], opening)

    def test_carries_sign_and_price(self) -> None:
        block = render.reveal_block(make_candidate(), 35, 2026, "adventure")
        self.assertEqual(block["sign"], render.sign_no(2026, "1100"))
        joined = "\n".join(block["lines"])
        self.assertIn("第 ", joined)
        self.assertIn("¥26.0", joined)
        self.assertIn("官方菜单价", joined)

    def test_does_not_embed_action_buttons(self) -> None:
        block = render.reveal_block(make_candidate(), 35, 2026, "adventure")
        joined = "\n".join(block["lines"])
        for action in render.actions_for("reveal"):
            self.assertNotIn(action["label"], joined)

    def test_reasons_capped_at_four(self) -> None:
        reasons = [f"理由{i}" for i in range(8)]
        block = render.reveal_block(make_candidate(reasons=reasons), 35, 2026, "balanced")
        joined = "\n".join(block["lines"])
        self.assertIn("理由3", joined)
        self.assertNotIn("理由4", joined)


class BoardBlockTest(unittest.TestCase):
    def _entries(self, count: int = 3):
        return [
            render.board_entry(i, make_candidate(code=f"10{i}", name=f"餐品{i}", price=10.0 + i))
            for i in range(count)
        ]

    def test_uses_chinese_numerals(self) -> None:
        lines = render.board_block(self._entries(3), 50, "无券", 0)
        self.assertEqual(lines[0], "今日三签：")

    def test_single_entry_says_one_sign(self) -> None:
        lines = render.board_block(self._entries(1), 50, "无券", 0)
        self.assertEqual(lines[0], "今日一签：")

    def test_never_embeds_action_buttons(self) -> None:
        lines = render.board_block(self._entries(3), 50, "无券", 0)
        joined = "\n".join(lines)
        for action in render.actions_for("board"):
            self.assertNotIn(action["label"], joined)

    def test_budget_and_coupon_appear_once(self) -> None:
        lines = render.board_block(self._entries(3), 50, "暂无结构化券数据", 2)
        self.assertEqual(sum(1 for line in lines if line.startswith("预算：")), 1)
        self.assertEqual(sum(1 for line in lines if line.startswith("优惠：")), 1)

    def test_flags_over_budget_items(self) -> None:
        entries = self._entries(3)
        lines = render.board_block(entries, 10, "无券", 0)
        joined = "\n".join(lines)
        self.assertIn("超出", joined)

    def test_reports_dropped_count_only_when_positive(self) -> None:
        with_drops = "\n".join(render.board_block(self._entries(2), 50, "无券", 5))
        without = "\n".join(render.board_block(self._entries(2), 50, "无券", 0))
        self.assertIn("排除 5 项", with_drops)
        self.assertNotIn("排除", without)

    def test_entry_reasons_capped_at_two(self) -> None:
        entry = render.board_entry(0, make_candidate(reasons=[f"理由{i}" for i in range(5)]))
        joined = "\n".join(entry["lines"])
        self.assertIn("理由1", joined)
        self.assertNotIn("理由2", joined)


class BudgetLineTest(unittest.TestCase):
    def test_no_budget_set(self) -> None:
        self.assertIn("未设置上限", render.budget_line(make_candidate(), None))

    def test_missing_price_is_reported_as_unknown(self) -> None:
        line = render.budget_line(make_candidate(price=None), 35)
        self.assertIn("无法确认", line)

    def test_within_budget_marks_unverified(self) -> None:
        line = render.budget_line(make_candidate(price=20.0), 35)
        self.assertIn("预算内", line)
        self.assertIn("未官方核价", line)

    def test_over_budget_is_flagged(self) -> None:
        line = render.budget_line(make_candidate(price=99.0), 35)
        self.assertIn("超过", line)


if __name__ == "__main__":
    unittest.main()
