"""场景：加权抽取 —— 可复现、避开拒绝项、候选不足时正常降级。"""

from __future__ import annotations

import random
import unittest
from dataclasses import dataclass

from mcfate_core import sampler


@dataclass
class Fake:
    code: str
    total: float


class SamplerTest(unittest.TestCase):
    def test_same_seed_is_reproducible(self) -> None:
        pool = [Fake(f"c{i}", 0.5 + i * 0.02) for i in range(10)]
        first = sampler.select(pool, 3, random.Random(42), score_of=lambda f: f.total, code_of=lambda f: f.code)
        second = sampler.select(pool, 3, random.Random(42), score_of=lambda f: f.total, code_of=lambda f: f.code)
        self.assertEqual([f.code for f in first], [f.code for f in second])

        other = sampler.select(pool, 3, random.Random(7), score_of=lambda f: f.total, code_of=lambda f: f.code)
        self.assertNotEqual([f.code for f in first], [f.code for f in other])

    def test_rejected_items_are_avoided(self) -> None:
        pool = [Fake(f"c{i}", 0.9 - i * 0.05) for i in range(6)]
        picked = sampler.select(
            pool, 2, random.Random(1), score_of=lambda f: f.total, code_of=lambda f: f.code, rejected=["c0"]
        )
        self.assertNotIn("c0", [item.code for item in picked])

    def test_insufficient_candidates_returns_fewer(self) -> None:
        pool = [Fake("a", 0.9), Fake("b", 0.8)]
        picked = sampler.select(pool, 5, random.Random(3), score_of=lambda f: f.total, code_of=lambda f: f.code)
        self.assertEqual(len(picked), 2)

    def test_rejection_falls_back_when_pool_too_small(self) -> None:
        pool = [Fake("a", 0.9), Fake("b", 0.8)]
        picked = sampler.select(
            pool, 2, random.Random(3), score_of=lambda f: f.total, code_of=lambda f: f.code, rejected=["a"]
        )
        self.assertEqual(len(picked), 2)  # 宁可回退，也不编造餐品

    def test_high_score_is_sampled_more_often_but_not_always(self) -> None:
        # 真实打分区间通常在 0.45~0.70，这里用接近现实的差距验证 softmax 行为
        pool = [Fake("top", 0.62), Fake("mid", 0.58), Fake("low", 0.55)]
        top_hits = 0
        low_hits = 0
        for seed in range(300):
            picked = sampler.select(
                pool, 1, random.Random(seed), score_of=lambda f: f.total, code_of=lambda f: f.code, pool_size=3
            )
            if picked[0].code == "top":
                top_hits += 1
            elif picked[0].code == "low":
                low_hits += 1
        self.assertGreater(top_hits, low_hits)
        self.assertGreater(low_hits, 0)  # 仍然会抽到低分项，保留新鲜感
        self.assertLess(top_hits, 300)  # 不是每次都取最高分


if __name__ == "__main__":
    unittest.main()
