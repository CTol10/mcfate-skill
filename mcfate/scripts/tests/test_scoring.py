"""场景：软偏好评分 —— 可解释、可复现、不假装掌握个人历史。"""

from __future__ import annotations

import unittest

from mcfate_core import config, normalize
from mcfate_core.profile import Profile
from mcfate_core.scoring import ScoringContext, score_item
from tests import fixtures


def make_profile(items=None, recent=None, preferences=None) -> Profile:
    return Profile(
        items=items or {},
        recent=recent or [],
        preferences=preferences or {},
        dates=[],
        warnings=[],
    )


class ScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {item.code: item for item in normalize.normalize_menu(fixtures.MENU_RAW)}

    def test_without_history_novelty_is_neutral_not_assumed(self) -> None:
        profile = make_profile()
        ctx = ScoringContext.build("balanced", profile)
        score = score_item(self.items["1100"], ctx)
        self.assertAlmostEqual(score.components["novelty"], config.NOVELTY_UNKNOWN)
        self.assertTrue(any("暂无可靠" in gap for gap in score.data_gaps))
        self.assertFalse(profile.history_reliable)

    def test_tried_item_has_lower_novelty(self) -> None:
        profile = make_profile({"1100": {"name": "巨无霸", "category": "巨无霸牛鱼肉堡", "status": "tried", "date": "2026-10-01"}})
        ctx = ScoringContext.build("balanced", profile)
        score = score_item(self.items["1100"], ctx)
        self.assertLessEqual(score.components["novelty"], 0.2)
        self.assertTrue(any("之前记录过" in reason for reason in score.reasons))

    def test_adventure_style_prefers_unexplored_category(self) -> None:
        profile = make_profile(
            {"1100": {"name": "巨无霸", "category": "巨无霸牛鱼肉堡", "status": "tried", "date": "2026-10-01"}},
            recent=[{"code": "1100", "name": "巨无霸", "category": "巨无霸牛鱼肉堡", "date": "2026-10-01"}],
        )
        ctx = ScoringContext.build("adventure", profile, recent_codes=["1100"], recent_categories=["巨无霸牛鱼肉堡"])
        coffee = score_item(self.items["507411"], ctx)
        burger = score_item(self.items["1100"], ctx)
        self.assertGreater(coffee.components["novelty"], burger.components["novelty"])
        self.assertGreater(coffee.total, burger.total)

    def test_liked_item_gets_preference_boost(self) -> None:
        profile = make_profile({"1700": {"name": "麦辣鸡翅", "category": "炸鸡", "status": "liked", "date": "2026-10-01"}})
        ctx = ScoringContext.build("steady", profile)
        liked = score_item(self.items["1700"], ctx)
        other = score_item(self.items["9900008751"], ctx)
        self.assertGreater(liked.components["preference"], other.components["preference"])

    def test_recent_recommendation_reduces_diversity(self) -> None:
        profile = make_profile()
        ctx = ScoringContext.build("balanced", profile, recent_codes=["1100"], recent_categories=["巨无霸牛鱼肉堡"])
        self.assertAlmostEqual(score_item(self.items["1100"], ctx).components["diversity"], 0.0)
        self.assertAlmostEqual(score_item(self.items["4810"], ctx).components["diversity"], 1.0)

    def test_weights_are_configurable_and_validated(self) -> None:
        custom = config.Weights(novelty=0.7, preference=0.1, diversity=0.1, mission_fit=0.1)
        profile = make_profile()
        default_ctx = ScoringContext.build("balanced", profile)
        custom_ctx = ScoringContext.build("balanced", profile, weights=custom)
        item = self.items["1100"]
        self.assertNotAlmostEqual(score_item(item, default_ctx).total, score_item(item, custom_ctx).total)
        with self.assertRaises(ValueError):
            config.Weights(novelty=0.9, preference=0.9, diversity=0.0, mission_fit=0.0)

    def test_all_components_normalized(self) -> None:
        profile = make_profile({}, preferences={"like_tags": ["牛肉", "炸鸡", "冷饮"], "avoid_tags": ["咖啡"]})
        ctx = ScoringContext.build("frugal", profile)
        for item in self.items.values():
            score = score_item(item, ctx)
            for name, value in score.components.items():
                self.assertGreaterEqual(value, 0.0, name)
                self.assertLessEqual(value, 1.0, name)
            self.assertGreaterEqual(score.total, 0.0)
            self.assertLessEqual(score.total, 1.0)


if __name__ == "__main__":
    unittest.main()
