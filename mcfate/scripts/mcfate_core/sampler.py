"""候选抽取：高分池 + 加权随机，保证可复现。

为什么不是直接取 Top-N：同一份菜单重复推荐会让“食运局”退化成排行榜。
做法是在高分池内按分数做加权随机（Efraimidis-Spirakis 无放回抽样），
传入固定 seed 即可复现同一结果，方便写测试。
"""

from __future__ import annotations

import math
import random
from typing import Iterable, List, Sequence, TypeVar

from . import config

T = TypeVar("T")


def weighted_sample(pool: Sequence[T], k: int, rng: random.Random, weight_of) -> List[T]:
    """按权重无放回抽取 k 个元素。返回顺序保持原池顺序。"""
    if k <= 0 or not pool:
        return []
    if len(pool) <= k:
        return list(pool)

    scored = []
    for index, item in enumerate(pool):
        weight = max(float(weight_of(item)), 1e-6)
        key = rng.random() ** (1.0 / weight)
        scored.append((key, -index, item))
    scored.sort(reverse=True)
    chosen = {id(entry[2]): entry[2] for entry in scored[:k]}
    return [item for item in pool if id(item) in chosen]


def select(
    candidates: Iterable[T],
    k: int,
    rng: random.Random,
    score_of,
    code_of,
    rejected: Iterable[str] = (),
    pool_size: int = config.RANDOM_POOL_SIZE,
    temperature: float = config.RANDOM_TEMPERATURE,
) -> List[T]:
    """从候选中抽 k 个；优先避开用户刚拒绝的餐品。

    权重用 softmax(score / temperature)：分高者更容易被抽中，但不会被固定选中，
    因此「再来一个」能换出新结果。
    """
    ordered = sorted(candidates, key=lambda c: (-score_of(c), code_of(c)))
    rejected_set = {str(code) for code in rejected}
    if rejected_set:
        filtered = [c for c in ordered if code_of(c) not in rejected_set]
        # 候选不足时才允许回退，绝不为了凑数编造餐品
        if len(filtered) >= k:
            ordered = filtered

    pool = ordered[: max(pool_size, k)]
    top = max((score_of(c) for c in pool), default=0.0)
    weights = {id(c): math.exp((score_of(c) - top) / max(temperature, 1e-6)) for c in pool}
    picked = weighted_sample(pool, min(k, len(pool)), rng, lambda c: weights[id(c)])
    return sorted(picked, key=lambda c: (-score_of(c), code_of(c)))
