"""把结构化结果渲染成可直接贴给用户的文本块。

渲染只做“事实陈述 + 数据来源标注”，不做营销夸张，也不补全未知信息。
模型可以在此基础上润色语气，但不得修改金额、券状态与预算结论。

游戏交互的关键不在文案花哨，而在**回合结构**：
- `reveal`（盲盒 / 就它了）：一次只揭一支签，动作只出现一次，输出后必须停。
- `board`（替我决定）：一屏摆出全部候选，动作统一收在末尾出现一次。

两者都不允许把同一组按钮重复挂在每个候选下面。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from . import config
from .models import Candidate

MARKS = ("①", "②", "③", "④", "⑤")
CHINESE_NUM = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五"}
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

# 开场只描述“抽”这个动作，不描述用户的历史（历史未知时描述就是编造）
REVEAL_OPENING = {
    "steady": "签筒摇三下，落出一支。",
    "balanced": "摇了三下，落出一支。",
    "adventure": "手伸进签筒，抽了一支出来。",
    "frugal": "先过了一遍账，再从签筒里抽。",
}

ACTIONS: Dict[str, List[Dict[str, str]]] = {
    "reveal": [
        {"id": "take", "label": "就它了", "hint": "按这款调用 calculate-price 核价，出订单摘要"},
        {"id": "again", "label": "再来一个", "hint": "把这款写入 rejected 重抽，且真的换一支"},
        {"id": "retune", "label": "换个口味", "hint": "只改一个维度（预算 / 忌口 / 风格），其余不动"},
    ],
    "board": [
        {"id": "pick", "label": "就它了", "hint": "用户报编号后，用对应编码核价"},
        {"id": "again", "label": "再来一个", "hint": "把本轮全部编码写入 rejected 重抽"},
        {"id": "retune", "label": "换个口味", "hint": "只改一个维度，其余不动"},
    ],
}


def sign_no(seed: int, code: str) -> str:
    """确定性签号：同一 seed + 同一餐品永远得到同一个号，便于复盘与测试。"""
    digest = hashlib.sha256(f"{seed}:{code}".encode("utf-8")).hexdigest()
    return str(int(digest[:6], 16) % 900 + 100)


def actions_for(turn: str) -> List[Dict[str, str]]:
    return [dict(action) for action in ACTIONS.get(turn, ACTIONS["board"])]


def budget_line(candidate: Candidate, budget: Optional[float]) -> str:
    item = candidate.item
    if item.price is None:
        return "预算：菜单未返回价格，无法确认是否在预算内"
    if budget is None:
        return f"预算：未设置上限，本款菜单价 ¥{item.price:.1f}"
    if item.price <= budget + config.BUDGET_TOLERANCE_YUAN:
        return f"预算：¥{item.price:.1f} 在 ¥{budget:.0f} 预算内（菜单价，未官方核价）"
    return f"预算：¥{item.price:.1f} 已超过 ¥{budget:.0f}（不应出现在候选里）"


def header(mode: str, style: str, budget: Optional[float], store_name: Optional[str]) -> str:
    parts = [f"【{MODE_LABEL.get(mode, mode)} · {STYLE_LABEL.get(style, style)}】"]
    if store_name:
        parts.append(store_name)
    if budget is not None:
        parts.append(f"预算 ¥{budget:.0f}")
    return "｜".join(parts)


def _reasons(candidate: Candidate, limit: int = 4) -> str:
    reasons = candidate.score.reasons or ["在符合你条件的餐品里落的一支"]
    return "；".join(reasons[:limit])


def reveal_block(
    candidate: Candidate,
    budget: Optional[float],
    seed: int,
    style: str,
    coupon_hint: str = "未核验到可用券，未计入任何优惠",
) -> Dict[str, Any]:
    """盲盒 / 单签揭晓：一支签的全部信息，动作不在这里给。"""
    item = candidate.item
    number = sign_no(seed, candidate.code)
    lines: List[str] = [
        REVEAL_OPENING.get(style, REVEAL_OPENING["balanced"]),
        "",
        f"第 {number} 签　{item.name} · {item.price_label}（官方菜单价）",
        f"　为什么是它：{_reasons(candidate)}",
        f"　{budget_line(candidate, budget)}",
        f"　优惠：{coupon_hint}",
    ]
    # 数据说明放在最后：它是透明度义务，不该打断“揭晓”的节奏
    if candidate.score.data_gaps:
        lines.append(f"　数据说明：{'；'.join(candidate.score.data_gaps[:2])}")
    return {
        "code": candidate.code,
        "name": item.name,
        "price": item.price,
        "sign": number,
        "score": candidate.score.total,
        "lines": lines,
    }


def board_entry(index: int, candidate: Candidate) -> Dict[str, Any]:
    """多候选择一屏预览：只给编号、名称、价格、一条理由。"""
    item = candidate.item
    mark = MARKS[index] if index < len(MARKS) else f"({index + 1})"
    return {
        "mark": mark,
        "code": candidate.code,
        "name": item.name,
        "price": item.price,
        "sign": None,
        "score": candidate.score.total,
        "lines": [
            f"{mark} {item.name} · {item.price_label}（官方菜单价）",
            f"　 为什么：{_reasons(candidate, limit=2)}",
        ],
    }


def board_block(
    entries: List[Dict[str, Any]],
    budget: Optional[float],
    coupon_summary: str,
    dropped_count: int = 0,
) -> List[str]:
    """把多候选拼成一屏，末尾统一给一条预算/优惠说明，不逐条重复。"""
    lines = [f"今日{CHINESE_NUM.get(len(entries), len(entries))}签："]
    for entry in entries:
        lines.extend(entry["lines"])
    if budget is None:
        lines.append("预算：未设置上限")
    else:
        over = [e["name"] for e in entries if e["price"] is not None and e["price"] > budget + config.BUDGET_TOLERANCE_YUAN]
        if over:
            lines.append(f"预算：{'、'.join(over)} 超出 ¥{budget:.0f}，不建议")
        else:
            lines.append(f"预算：全部在 ¥{budget:.0f} 内（菜单价，未官方核价）")
    lines.append(f"优惠：{coupon_summary}")
    if dropped_count:
        lines.append(f"已按硬性约束排除 {dropped_count} 项")
    return lines


def degrade_notice(notes: List[str]) -> List[str]:
    return [f"提示：{note}" for note in notes if note]
