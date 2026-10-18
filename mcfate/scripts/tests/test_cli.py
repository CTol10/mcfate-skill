"""端到端场景：模型只做理解与调用，脚本给出可复现结论。"""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from mcfate_core import cli
from tests import fixtures


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile_path = self.root / "profile.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, argv, payload):
        path = self.root / "payload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main([*argv, "--input", str(path), "--profile", str(self.profile_path)])
        return code, json.loads(buffer.getvalue())

    # 场景 1：用户只说“不知道吃什么”
    def test_default_recommendation_without_any_preference(self) -> None:
        code, out = self._run(["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "seed": 7})
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["candidates"]), 3)
        self.assertIn("替我决定", out["header"])
        self.assertFalse(out["meta"]["history_reliable"])
        self.assertTrue(any("没有明确标记" in note for note in out["meta"]["warnings"]))

    # 场景 2：预算硬约束
    def test_budget_filter_end_to_end(self) -> None:
        _code, out = self._run(
            ["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "budget": 15, "count": 5, "seed": 1}
        )
        self.assertTrue(out["ok"])
        for candidate in out["candidates"]:
            self.assertLessEqual(candidate["price"], 15.0)

    # 场景 3+4：尝鲜与拒绝后不重复
    def test_rejected_item_is_avoided(self) -> None:
        profile = {
            "items": {"1100": {"name": "巨无霸", "category": "巨无霸牛鱼肉堡", "status": "rejected", "date": "2026-10-18"}}
        }
        _code, out = self._run(
            ["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "profile": profile, "seed": 3}
        )
        self.assertNotIn("1100", [candidate["code"] for candidate in out["candidates"]])

    # 场景 6：没有券，省钱模式仍然可用
    def test_save_mode_without_coupons_still_works(self) -> None:
        code, out = self._run(
            ["recommend"],
            {"mode": "save", "menu": fixtures.MENU_RAW, "budget": 35, "store": {"code": "1234567"}, "seed": 5},
        )
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["combos"], [])
        self.assertTrue(any("没有可用的结构化券" in note for note in out["combo_notes"]))
        self.assertTrue(out["candidates"])

    # 场景 7+8：攒券调度与算价请求
    def test_save_mode_generates_pricing_requests(self) -> None:
        _code, out = self._run(
            ["recommend"],
            {
                "mode": "save",
                "menu": fixtures.MENU_RAW,
                "coupons": fixtures.COUPONS_RAW,
                "budget": 50,
                "store": {"code": "1234567", "order_type": 1, "be_type": 1},
                "seed": 5,
            },
        )
        self.assertTrue(out["combos"])
        self.assertTrue(out["pricing_requests"])
        first = out["pricing_requests"][0]
        self.assertIn("with_coupon", first)
        self.assertIn("without_coupon", first)
        self.assertEqual(first["with_coupon"]["items"][0]["productCode"], "1100")

    # 场景 10：菜单为空时明确失败，不编造
    def test_empty_menu_returns_clear_error(self) -> None:
        code, out = self._run(["recommend"], {"mode": "decide", "menu": {"success": False, "message": "打烊"}})
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertIn("未解析到", out["error"])

    # 场景 11：候选不足时返回较少结果
    def test_few_candidates_returns_fewer(self) -> None:
        _code, out = self._run(
            ["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "budget": 10, "count": 5, "seed": 2}
        )
        self.assertLessEqual(len(out["candidates"]), 1)  # 10 元内只有可乐
        self.assertTrue(out["ok"])

    # 场景 12：随机可复现
    def test_seed_makes_result_reproducible(self) -> None:
        payload = {"mode": "decide", "menu": fixtures.MENU_RAW, "seed": 42}
        _code, first = self._run(["recommend"], payload)
        _code2, second = self._run(["recommend"], payload)
        self.assertEqual([c["code"] for c in first["candidates"]], [c["code"] for c in second["candidates"]])

    # 场景 9：算价失败不伪造价格
    def test_rerank_marks_failure_without_price(self) -> None:
        code, out = self._run(
            ["rerank"],
            {
                "budget": 35,
                "entries": [{"label": "方案A", "quote": fixtures.QUOTE_FAIL}],
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["ranked"][0]["state"], "unverified")
        self.assertIsNone(out["ranked"][0]["payable"])
        self.assertIsNone(out["recommended"])

    # 场景 13+14：不提供任何下单能力，重复执行结果一致
    def test_no_order_side_effect_commands(self) -> None:
        parser = cli.build_parser()
        sub_actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
        commands = set(sub_actions[0].choices)
        self.assertEqual(commands, {"recommend", "rerank", "coupon-plan", "record", "profile", "export", "import"})
        for name in commands:
            self.assertNotIn("order", name)

    def test_rerank_is_idempotent(self) -> None:
        payload = {
            "budget": 35,
            "entries": [
                {"label": "方案A", "quote": fixtures.QUOTE_WITH_COUPON},
                {"label": "方案B", "quote": fixtures.QUOTE_OK},
            ],
        }
        _code, first = self._run(["rerank"], payload)
        _code2, second = self._run(["rerank"], payload)
        self.assertEqual(first, second)

    # 场景 15：输出不含令牌类敏感字段
    def test_output_has_no_sensitive_keys(self) -> None:
        _code, out = self._run(
            ["recommend"], {"mode": "save", "menu": fixtures.MENU_RAW, "coupons": fixtures.COUPONS_RAW, "seed": 1}
        )
        forbidden = {"token", "accesstoken", "authorization", "cookie", "accountid", "traceid", "password"}
        found = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if str(key).lower().replace("_", "") in forbidden:
                        found.append(key)
                    walk(value)
            elif isinstance(node, list):
                for row in node:
                    walk(row)

        walk(out)
        self.assertEqual(found, [])

    # 图鉴：记录与读取
    def test_record_and_profile_roundtrip(self) -> None:
        path = self.root / "payload.json"
        path.write_text("{}", encoding="utf-8")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(
                [
                    "record",
                    "--code",
                    "1100",
                    "--name",
                    "巨无霸",
                    "--category",
                    "巨无霸牛鱼肉堡",
                    "--status",
                    "liked",
                    "--day",
                    "2026-10-18",
                    "--profile",
                    str(self.profile_path),
                ]
            )
        self.assertEqual(code, 0)
        self.assertTrue(self.profile_path.exists())

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli.main(["profile", "--profile", str(self.profile_path), "--today", "2026-10-18"])
        summary = json.loads(buffer.getvalue())["summary"]
        self.assertEqual(summary["liked_count"], 1)
        self.assertEqual(summary["streak_days"], 1)

    def test_coupon_plan_command(self) -> None:
        code, out = self._run(
            ["coupon-plan"],
            {
                "menu": fixtures.MENU_RAW,
                "coupons": fixtures.COUPONS_RAW,
                "items": ["1100"],
                "budget": 35,
            },
        )
        self.assertEqual(code, 0)
        statuses = {check["status"] for check in out["checks"]}
        self.assertIn("needs_extra", statuses)
        self.assertIn("not_applicable", statuses)

    def test_menu_file_is_expanded(self) -> None:
        menu_path = self.root / "menu.json"
        menu_path.write_text(json.dumps(fixtures.MENU_RAW, ensure_ascii=False), encoding="utf-8")
        code, out = self._run(["recommend"], {"mode": "decide", "menu_file": str(menu_path), "seed": 1})
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["meta"]["menu_total"], 8)

    def test_missing_menu_file_degrades_gracefully(self) -> None:
        code, out = self._run(["recommend"], {"mode": "decide", "menu_file": str(self.root / "nope.json")})
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertIn("未解析到", out["error"])

    def test_drinks_are_not_recommended_as_a_meal(self) -> None:
        _code, out = self._run(
            ["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "count": 3, "seed": 9}
        )
        codes = {candidate["code"] for candidate in out["candidates"]}
        self.assertNotIn("9900008751", codes)  # 可乐
        self.assertNotIn("4810", codes)  # 薯条


class TurnStructureTest(unittest.TestCase):
    """回合结构：游戏交互靠它成立，不是靠文案。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile_path = self.root / "profile.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, argv, payload):
        path = self.root / "payload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main([*argv, "--input", str(path), "--profile", str(self.profile_path)])
        return code, json.loads(buffer.getvalue())

    def test_decide_is_a_board_turn(self) -> None:
        _code, out = self._run(["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "seed": 11})
        self.assertEqual(out["turn"], "board")
        self.assertIn("board_lines", out)
        self.assertNotIn("reveal_lines", out)
        self.assertNotIn("sign", out)

    def test_blindbox_is_a_reveal_turn_with_exactly_one_candidate(self) -> None:
        _code, out = self._run(["recommend"], {"mode": "blindbox", "menu": fixtures.MENU_RAW, "seed": 11})
        self.assertEqual(out["turn"], "reveal")
        self.assertEqual(len(out["candidates"]), 1)
        self.assertIn("reveal_lines", out)
        self.assertIsNotNone(out["sign"])
        self.assertIn("命运盲盒", out["header"])

    def test_count_one_also_reveals(self) -> None:
        _code, out = self._run(
            ["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "count": 1, "seed": 11}
        )
        self.assertEqual(out["turn"], "reveal")
        self.assertEqual(len(out["candidates"]), 1)

    def test_turn_forces_the_model_to_stop(self) -> None:
        _code, out = self._run(["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "seed": 11})
        self.assertTrue(out["meta"]["stop_after_turn"])

    def test_actions_are_structured_and_listed_once(self) -> None:
        for mode in ("decide", "blindbox"):
            _code, out = self._run(["recommend"], {"mode": mode, "menu": fixtures.MENU_RAW, "seed": 11})
            self.assertEqual(len(out["actions"]), 3)
            for action in out["actions"]:
                self.assertTrue(action["label"])
                self.assertTrue(action["hint"])
            # next_actions 只是 actions 的标签投影，不得多出一组按钮
            self.assertEqual(out["next_actions"], [a["label"] for a in out["actions"]])

    def test_candidates_never_carry_their_own_action_buttons(self) -> None:
        for mode in ("decide", "blindbox"):
            _code, out = self._run(["recommend"], {"mode": mode, "menu": fixtures.MENU_RAW, "seed": 11})
            labels = [a["label"] for a in out["actions"]]
            for candidate in out["candidates"]:
                joined = "\n".join(candidate["lines"])
                for label in labels:
                    self.assertNotIn(label, joined)

    def test_board_puts_budget_and_coupon_in_one_place(self) -> None:
        _code, out = self._run(
            ["recommend"], {"mode": "decide", "menu": fixtures.MENU_RAW, "budget": 40, "seed": 11}
        )
        lines = out["board_lines"]
        self.assertEqual(sum(1 for line in lines if line.startswith("预算：")), 1)
        self.assertEqual(sum(1 for line in lines if line.startswith("优惠：")), 1)

    def test_same_seed_reproduces_the_same_sign(self) -> None:
        _payload = {"mode": "blindbox", "menu": fixtures.MENU_RAW, "seed": 424242}
        _code, first = self._run(["recommend"], _payload)
        _code, second = self._run(["recommend"], _payload)
        self.assertEqual(first["sign"], second["sign"])
        self.assertEqual(first["candidates"][0]["code"], second["candidates"][0]["code"])

    def test_save_mode_offers_pricing_action(self) -> None:
        _code, out = self._run(
            ["recommend"],
            {"mode": "save", "menu": fixtures.MENU_RAW, "coupons": fixtures.COUPONS_RAW, "budget": 40, "seed": 5},
        )
        ids = [action["id"] for action in out["actions"]]
        self.assertIn("price", ids)
        self.assertEqual(out["next_actions"], [a["label"] for a in out["actions"]])



if __name__ == "__main__":
    unittest.main()
