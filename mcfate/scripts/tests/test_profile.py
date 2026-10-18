"""场景：个人探索图鉴 —— 只记录显式标记，损坏文件不崩溃。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mcfate_core import normalize
from mcfate_core.profile import Profile, merge
from tests import fixtures


class ProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "profile.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roundtrip(self) -> None:
        profile = Profile.empty()
        profile.mark("1100", "巨无霸", "巨无霸牛鱼肉堡", "liked", "2026-10-01")
        profile.save(self.path)
        reloaded = Profile.load(self.path)
        self.assertEqual(reloaded.status("1100"), "liked")
        self.assertTrue(reloaded.history_reliable)

    def test_no_marks_means_history_unreliable(self) -> None:
        profile = Profile.empty()
        profile.add_recent("1100", "巨无霸", "巨无霸牛鱼肉堡", "2026-10-01")
        self.assertFalse(profile.history_reliable)  # 推荐过 ≠ 吃过

    def test_corrupt_file_degrades_with_warning(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        profile = Profile.load(self.path)
        self.assertFalse(profile.history_reliable)
        self.assertTrue(profile.warnings)
        self.assertEqual(profile.items, {})

    def test_streak_requires_consecutive_dates(self) -> None:
        profile = Profile.empty()
        profile.mark("1100", "巨无霸", "汉堡", "tried", "2026-10-16")
        profile.mark("1700", "麦辣鸡翅", "炸鸡", "tried", "2026-10-17")
        profile.mark("4810", "薯条", "小食", "tried", "2026-10-18")
        self.assertEqual(profile.streak_days("2026-10-18"), 3)
        self.assertEqual(profile.streak_days("2026-10-25"), 0)

    def test_recent_is_deduplicated_and_bounded(self) -> None:
        profile = Profile.empty()
        for i in range(30):
            profile.add_recent(str(i), f"餐品{i}", "汉堡", "2026-10-18")
        profile.add_recent("5", "餐品5", "汉堡", "2026-10-18")
        self.assertEqual(len(profile.recent), 20)
        self.assertEqual(profile.recent[0]["code"], "5")
        self.assertEqual(len({row["code"] for row in profile.recent}), len(profile.recent))

    def test_progress_counts_categories(self) -> None:
        items = normalize.normalize_menu(fixtures.MENU_RAW)
        profile = Profile.empty()
        profile.mark("1100", "巨无霸", "巨无霸牛鱼肉堡", "tried", "2026-10-18")
        progress = profile.progress(items)
        self.assertGreater(progress["total_categories"], 0)
        finished = next(row for row in progress["categories"] if row["category"] == "巨无霸牛鱼肉堡")
        self.assertEqual(finished["tried"], 1)

    def test_merge_keeps_existing_records(self) -> None:
        base = Profile.empty()
        base.mark("1100", "巨无霸", "汉堡", "disliked", "2026-10-18")
        merged = merge(base, {"items": {"1100": {"name": "巨无霸", "category": "汉堡", "status": "liked", "date": "2026-09-01"}}})
        self.assertEqual(merged.status("1100"), "disliked")  # 旧记录更早，不覆盖
        merged2 = merge(base, {"items": {"1700": {"name": "麦辣鸡翅", "category": "炸鸡", "status": "liked", "date": "2026-10-19"}}})
        self.assertEqual(merged2.status("1700"), "liked")

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Profile.empty().mark("1", "x", "y", "eaten")


if __name__ == "__main__":
    unittest.main()
