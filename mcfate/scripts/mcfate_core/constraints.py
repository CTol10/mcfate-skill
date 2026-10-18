"""硬约束过滤。

硬约束永远优先于游戏得分：预算、用户明确排除、缺失必要数据。
这里只做“能不能进入候选”的判断，不做打分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from . import config
from .models import ROLE_MAIN, MenuItem


@dataclass(frozen=True)
class Constraints:
    budget: Optional[float] = None
    exclude: Tuple[str, ...] = ()

    @classmethod
    def build(cls, budget: Optional[float], exclude: Optional[Sequence[str]]) -> "Constraints":
        terms: List[str] = []
        for term in exclude or []:
            text = str(term).strip()
            if text and text not in terms:
                terms.append(text)
        return cls(budget=None if budget is None else float(budget), exclude=tuple(terms))


@dataclass
class FilterOutcome:
    kept: List[MenuItem] = field(default_factory=list)
    flags: dict = field(default_factory=dict)  # code -> tuple[str, ...]
    dropped: List[dict] = field(default_factory=list)

    def flag_for(self, code: str) -> Tuple[str, ...]:
        return tuple(self.flags.get(code, ()))


def _haystack(item: MenuItem) -> str:
    return " ".join((item.name, item.category, " ".join(item.tags)))


def _matched_terms(item: MenuItem, terms: Sequence[str]) -> List[str]:
    text = _haystack(item)
    return [term for term in terms if term in text]


def apply(items: Sequence[MenuItem], constraints: Constraints) -> FilterOutcome:
    outcome = FilterOutcome()
    for item in items:
        hits = _matched_terms(item, constraints.exclude)
        if hits:
            outcome.dropped.append(
                {"code": item.code, "name": item.name, "reason": f"命中排除项：{'、'.join(hits)}"}
            )
            continue

        if constraints.budget is not None and item.price is not None:
            if item.price > constraints.budget + config.BUDGET_TOLERANCE_YUAN:
                outcome.dropped.append(
                    {
                        "code": item.code,
                        "name": item.name,
                        "reason": f"超出预算（¥{item.price:.1f} > ¥{constraints.budget:.0f}）",
                    }
                )
                continue

        flags: List[str] = []
        if item.price is None:
            flags.append("price_unknown")
        if constraints.budget is not None and item.price is None:
            flags.append("budget_unverified")

        outcome.kept.append(item)
        outcome.flags[item.code] = tuple(flags)
    return outcome


def prioritize_main(items: Sequence[MenuItem], need: int) -> Tuple[List[MenuItem], List[str]]:
    """主餐优先：当主餐数量足够时，不把小食/饮品当作“今天吃什么”的答案。"""
    mains = [item for item in items if item.role == ROLE_MAIN]
    if need > 0 and len(mains) >= need and len(mains) < len(items):
        return mains, ["已排除小食与饮品候选，避免把配餐当成一顿饭"]
    return list(items), []
