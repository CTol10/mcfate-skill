"""把结构化结果渲染成可直接贴给用户的文本块。

渲染只做“事实陈述 + 数据来源标注”，不做营销夸张，也不补全未知信息。
模型可以在此基础上润色语气，但不得修改金额、券状态与预算结论。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config
from .models import Candidate

MARKS = ("①", "②", "③", "④", "⑤")
STYLE_LABEL = {
    "steady": "稳妥派",
    "balanced": "均衡派",
    "adventure": "冒险派",
    "frugal": "精算派",
}
MODE_LABEL = {
    "decide": "替我决定",
    "save": "麦运省钱",
    "blindbox": "命运盲盒",
}
NEXT_ACTIONS = ("就它了（进入核价）", "再来一个", "换个口味")


def budget_line(candidate: Candidate, budget: Optional[float]) -> str:
    item = candidate.item
    if item.price is None:
        return "预算：菜单未返回价格，无法确认是否在预算内"
    if budget is None:
        return f"预算：未设置上限，本款菜单价 ¥{item.price:.1f}"
    if item.price <= budget + config.BUDGET_TOLERANCE_YUAN:
        return f"预算：¥{item.price:.1f} 在 ¥{budget:.0f} 预算内（菜单价，未官方核价）"
    return f"预算：¥{item.price:.1f} 已超过 ¥{budget:.0f}（不应出现在候选里）"


def candidate_block(
    index: int,
    candidate: Candidate,
    budget: Optional[float],
    coupon_hint: str = "未核验到可用券，未计入任何优惠",
) -> Dict[str, Any]:
    item = candidate.item
    mark = MARKS[index] if index < len(MARKS) else f"({index + 1})"
    reasons = candidate.score.reasons or ["菜单内可售，且满足当前硬性约束"]
    lines: List[str] = [
        f"{mark} {item.name} · {item.price_label}（官方菜单价）",
        f"　 为什么是它：{'；'.join(reasons[:4])}",
    ]
    if candidate.score.data_gaps:
        lines.append(f"　 数据说明：{'；'.join(candidate.score.data_gaps[:2])}")
    lines.append(f"　 {budget_line(candidate, budget)}")
    lines.append(f"　 优惠：{coupon_hint}")
    lines.append(f"　 下一步：{' / '.join(NEXT_ACTIONS)}")
    return {
        "code": item.code,
        "name": item.name,
        "price": item.price,
        "score": candidate.score.total,
        "lines": lines,
    }


def header(mode: str, style: str, budget: Optional[float], store_name: Optional[str]) -> str:
    parts = [f"【{MODE_LABEL.get(mode, mode)} · {STYLE_LABEL.get(style, style)}】"]
    if store_name:
        parts.append(store_name)
    if budget is not None:
        parts.append(f"预算 ¥{budget:.0f}")
    return "｜".join(parts)


def degrade_notice(notes: List[str]) -> List[str]:
    return [f"提示：{note}" for note in notes if note]
