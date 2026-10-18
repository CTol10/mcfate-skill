"""软偏好评分：novelty / preference / diversity / mission_fit。

硬约束已在 constraints 阶段完成；这里只负责 0-1 打点和生成可解释理由。
核心原则：历史缺失时使用中性分，不把“未知”当成“吃过”或“不喜欢”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set, Tuple

from . import config
from .models import ROLE_LABEL, ROLE_MAIN, ROLE_SIDE, MenuItem, Score
from .profile import Profile

NEW_TAG = "上新"
LIMITED_TAG = "限定"
NEW_HINTS = (NEW_TAG, LIMITED_TAG, "新品", "限时")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _is_new(item: MenuItem) -> bool:
    text = " ".join(item.tags)
    return any(hint in text for hint in NEW_HINTS)


@dataclass
class ScoringContext:
    weights: config.Weights
    style: str
    profile: Profile
    recent_codes: Tuple[str, ...]
    recent_categories: Tuple[str, ...]
    coupon_codes: Set[str] = field(default_factory=set)

    @classmethod
    def build(
        cls,
        style: str,
        profile: Profile,
        recent_codes: Sequence[str] = (),
        recent_categories: Sequence[str] = (),
        coupon_codes: Sequence[str] = (),
        weights: config.Weights | None = None,
    ) -> "ScoringContext":
        return cls(
            weights=weights or config.STYLE_WEIGHTS.get(style, config.STYLE_WEIGHTS[config.DEFAULT_STYLE]),
            style=style,
            profile=profile,
            recent_codes=tuple(recent_codes),
            recent_categories=tuple(recent_categories),
            coupon_codes=set(coupon_codes),
        )


def novelty(item: MenuItem, ctx: ScoringContext) -> Tuple[float, List[str], List[str]]:
    reasons: List[str] = []
    gaps: List[str] = []
    if not ctx.profile.history_reliable:
        gaps.append("暂无可靠的尝试记录，新鲜感按中性值处理")
        return config.NOVELTY_UNKNOWN, reasons, gaps

    status = ctx.profile.status(item.code)
    if status == "disliked":
        return 0.05, ["你之前标记过不喜欢这款，因此新鲜感很低"], gaps
    if status in ("tried", "liked"):
        reasons.append(f"「{item.name}」你之前记录过，属于回头选项")
        return (0.30 if status == "liked" else 0.20), reasons, gaps
    if item.category and item.category in ctx.profile.tried_categories():
        reasons.append(f"「{item.category}」这个品类你试过，但这款还没在记录里")
        return 0.65, reasons, gaps
    reasons.append(f"「{item.category}」这个品类在你的记录里还是空白")
    return 1.0, reasons, gaps


def preference(item: MenuItem, ctx: ScoringContext) -> Tuple[float, List[str], List[str]]:
    reasons: List[str] = []
    gaps: List[str] = []
    score = config.PREFERENCE_UNKNOWN
    status = ctx.profile.status(item.code)

    if status == "liked":
        score += 0.45
        reasons.append("你标记过喜欢这款")
    elif status == "disliked":
        score -= 0.55
        reasons.append("你标记过不喜欢这款")

    text = " ".join((item.name, item.category, " ".join(item.tags)))
    like_hits = [tag for tag in ctx.profile.preference("like_tags") if tag and tag in text]
    avoid_hits = [tag for tag in ctx.profile.preference("avoid_tags") if tag and tag in text]
    taste_hits = [tag for tag in ctx.profile.preference("taste") if tag and tag in text]

    if like_hits:
        score += min(0.24, 0.08 * len(like_hits))
        reasons.append(f"命中你点名的偏好：{'、'.join(like_hits[:3])}")
    if avoid_hits:
        score -= min(0.40, 0.30 * len(avoid_hits))
        reasons.append(f"命中你要求避开的口味：{'、'.join(avoid_hits[:3])}")
    if taste_hits:
        score += min(0.20, 0.10 * len(taste_hits))
        reasons.append(f"口味方向匹配：{'、'.join(taste_hits[:3])}")

    if not like_hits and not avoid_hits and not taste_hits and status is None:
        gaps.append("尚无口味偏好记录，偏好分按中性值处理")
    return _clamp(score), reasons, gaps


def diversity(item: MenuItem, ctx: ScoringContext) -> Tuple[float, List[str], List[str]]:
    if not ctx.recent_codes:
        return config.DIVERSITY_UNKNOWN, [], ["暂无推荐历史，差异度按中性值处理"]

    if item.code == ctx.recent_codes[0]:
        return 0.0, ["和上一次推荐完全相同"], []
    if item.code in ctx.recent_codes[: config.RECENT_STRONG_WINDOW]:
        return 0.10, ["最近刚推荐过这款，重复度较高"], []
    if item.code in ctx.recent_codes:
        return 0.30, ["之前推荐过这款"], []
    if ctx.recent_categories and item.category == ctx.recent_categories[0]:
        return 0.45, [f"和上次同属「{item.category}」品类，换了个具体餐品"], []
    return 1.0, [], []


def _role_adjust(role: str, style: str) -> float:
    """小食/饮品可以当搭配，但不该成为“今天吃什么”的答案。"""
    if role == ROLE_MAIN:
        return 0.05 if style == "frugal" else 0.08
    if role == ROLE_SIDE:
        return -0.10 if style == "frugal" else -0.15
    return -0.15 if style == "frugal" else -0.20


def mission_fit(item: MenuItem, ctx: ScoringContext) -> Tuple[float, List[str], List[str]]:
    """当前游戏/模式的匹配度。四种风格各有不同取向。"""
    status = ctx.profile.status(item.code)
    untried = status not in ("tried", "liked", "disliked")
    is_new = _is_new(item)
    depth = 0.0
    if item.price and item.original_price and item.original_price > item.price:
        depth = (item.original_price - item.price) / item.original_price

    reasons: List[str] = []
    if ctx.style == "steady":
        score = 0.45
        if not is_new:
            score += 0.30
        else:
            reasons.append("稳妥派：上新款只作为低权重参考")
        if status in ("tried", "liked"):
            score += 0.15
        if item.can_with_order:
            score += 0.05
    elif ctx.style == "adventure":
        if untried and item.category not in ctx.profile.tried_categories():
            score = 1.0
            reasons.append("冒险派：这款所在品类还没被记录过")
        elif untried and is_new:
            score = 0.90
            reasons.append("冒险派：没试过的新品")
        elif untried:
            score = 0.80
            reasons.append("冒险派：还没记录尝试过")
        else:
            score = 0.40
            reasons.append("冒险派：这款你已经记录过")
    elif ctx.style == "frugal":
        score = 0.40 + 0.60 * min(depth / 0.5, 1.0)
        if depth > 0:
            reasons.append(f"精算派：菜单现价较划线价低 {depth:.0%}")
        if item.code in ctx.coupon_codes:
            score += 0.15
            reasons.append("精算派：有已核验的券覆盖这款")
    else:
        score = config.MISSION_FIT_UNKNOWN
        if untried and ctx.profile.history_reliable:
            score += 0.10  # 新鲜感已在 novelty 里体现，这里不再重复解释
        if depth >= 0.15:
            score += 0.15
            reasons.append(f"菜单现价较划线价低 {depth:.0%}")
        if item.code in ctx.coupon_codes:
            score += 0.10
            reasons.append("有券覆盖这款")

    score += _role_adjust(item.role, ctx.style)
    if item.role != ROLE_MAIN:
        reasons.append(f"这一款属于{ROLE_LABEL.get(item.role, '配餐')}，更适合做搭配")
    return _clamp(score), reasons, []


def score_item(item: MenuItem, ctx: ScoringContext) -> Score:
    parts: Dict[str, float] = {}
    reasons: List[str] = []
    gaps: List[str] = []

    for name, func in (
        ("novelty", novelty),
        ("preference", preference),
        ("diversity", diversity),
        ("mission_fit", mission_fit),
    ):
        value, why, missing = func(item, ctx)
        parts[name] = round(_clamp(value), 4)
        reasons.extend(why)
        gaps.extend(missing)

    weights = ctx.weights.as_dict()
    total = sum(parts[name] * weights[name] for name in weights)
    if not reasons:
        # 至少给出一条有据可查的理由，避免空泛的“算法推荐”
        if item.price is not None:
            reasons.append(f"官方菜单价 ¥{item.price:.1f}，满足当前预算与排除条件")
        else:
            reasons.append("菜单内可售，满足当前硬性约束")
    return Score(components=parts, total=round(_clamp(total), 4), reasons=reasons, data_gaps=gaps)


def score_items(items: Sequence[MenuItem], ctx: ScoringContext) -> List[Score]:
    return [score_item(item, ctx) for item in items]
