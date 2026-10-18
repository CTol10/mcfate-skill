"""优惠券调度：判定可用性、生成组合、核算真实节省。

三条铁律：
1. 接口没给的字段（门槛、适用范围、叠加规则）一律视为未知，不推断。
2. 券面额不等于净收益；若为凑门槛多买了东西，必须把这笔多花的钱说清楚。
3. “节省”只有在同一组合带券/不带券两次官方算价都成功时，才允许说成“这张券省了多少”。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import config
from .models import Combo, Coupon, MenuItem, Quote


@dataclass
class CouponCheck:
    coupon: Coupon
    status: str
    applicable: Optional[bool]
    extra_needed: Optional[float]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.coupon.title,
            "coupon_id": self.coupon.coupon_id,
            "status": self.status,
            "applicable": self.applicable,
            "face_value": self.coupon.face_value,
            "threshold": self.coupon.threshold,
            "extra_needed": self.extra_needed,
            "unit_assumed": self.coupon.unit_assumed,
            "note": self.note,
        }


def check(coupon: Coupon, item_codes: Sequence[str], subtotal: Optional[float]) -> CouponCheck:
    """判断券与当前商品清单的关系。不做任何金额推断。"""
    codes = {str(code) for code in item_codes}

    if coupon.product_codes and codes and not (set(coupon.product_codes) & codes):
        return CouponCheck(
            coupon,
            config.COUPON_NOT_APPLICABLE,
            False,
            None,
            "券的适用餐品与当前所选没有交集",
        )

    if coupon.threshold is not None and subtotal is not None:
        if subtotal + config.BUDGET_TOLERANCE_YUAN < coupon.threshold:
            extra = round(coupon.threshold - subtotal, 2)
            return CouponCheck(
                coupon,
                config.COUPON_NEEDS_EXTRA,
                True,
                extra,
                f"还差 ¥{extra:.1f} 才到门槛，需额外加购",
            )
        return CouponCheck(coupon, config.COUPON_USABLE, True, None, "已达到使用门槛，需官方算价确认实际优惠")

    if coupon.product_codes and not coupon.threshold:
        return CouponCheck(
            coupon,
            config.COUPON_USABLE,
            True,
            None,
            "适用餐品匹配；门槛未在接口返回，需官方算价确认",
        )

    return CouponCheck(
        coupon,
        config.COUPON_UNVERIFIED,
        None,
        None,
        "接口未返回可用的适用范围与门槛信息，无法判断是否可用",
    )


def attribute_savings(with_quote: Quote, without_quote: Quote) -> tuple[Optional[float], bool]:
    """只有在两次算价都成功且商品一致时，才把差额记为这张券的节省。"""
    if not (with_quote.ok and without_quote.ok):
        return None, False
    if with_quote.payable is None or without_quote.payable is None:
        return None, False
    with_codes = sorted(str(p.get("code")) for p in with_quote.products)
    without_codes = sorted(str(p.get("code")) for p in without_quote.products)
    if with_codes != without_codes:
        return None, False
    diff = round(without_quote.payable - with_quote.payable, 2)
    return max(diff, 0.0), True


def _cheapest(items: Iterable[MenuItem], exclude: Sequence[str] = ()) -> Optional[MenuItem]:
    pool = [item for item in items if item.price is not None and item.code not in exclude]
    if not pool:
        return None
    return sorted(pool, key=lambda i: (i.price, i.code))[0]


def suggest_combos(
    coupons: Sequence[Coupon],
    items: Sequence[MenuItem],
    budget: Optional[float] = None,
    max_combos: int = config.MAX_COMBOS,
) -> tuple[List[Combo], List[str]]:
    """生成少量可执行组合。返回 (组合列表, 说明)。

    组合只做“候选筛选”，金额一律标注为菜单价估算，最终以 calculate-price 为准。
    """
    notes: List[str] = []
    by_code = {item.code: item for item in items}
    combos: List[Combo] = []

    for index, coupon in enumerate(sorted(coupons, key=lambda c: c.title)):
        if len(combos) >= max_combos:
            break
        applicable = [by_code[code] for code in coupon.product_codes if code in by_code]
        if not applicable:
            notes.append(f"「{coupon.title}」的适用餐品不在当前菜单候选中，已跳过")
            continue

        base = _cheapest(applicable)
        chosen = [base]
        subtotal = base.price or 0.0
        combo_notes: List[str] = [f"使用「{coupon.title}」的适用餐品打底（¥{subtotal:.1f}）"]

        if coupon.threshold is not None and subtotal + config.BUDGET_TOLERANCE_YUAN < coupon.threshold:
            extra_needed = round(coupon.threshold - subtotal, 2)
            combo_notes.append(f"距门槛还差 ¥{extra_needed:.1f}")
            pool = [
                item
                for item in items
                if item.price is not None and item.code not in {c.code for c in chosen}
            ]
            for filler in sorted(pool, key=lambda i: (i.price, i.code)):
                if subtotal + config.BUDGET_TOLERANCE_YUAN >= coupon.threshold:
                    break
                if budget is not None and subtotal + (filler.price or 0) > budget + config.BUDGET_TOLERANCE_YUAN:
                    continue
                chosen.append(filler)
                subtotal += filler.price or 0.0
                combo_notes.append(f"为凑门槛加购「{filler.name}」¥{filler.price:.1f}")
            if budget is not None and subtotal + config.BUDGET_TOLERANCE_YUAN < coupon.threshold:
                combo_notes.append("在预算内无法凑到门槛，需自行判断是否值得加购")
            elif coupon.threshold is not None and subtotal + config.BUDGET_TOLERANCE_YUAN < coupon.threshold:
                combo_notes.append("当前菜单内找不到可凑门槛的商品，方案不可执行")

        combos.append(
            Combo(
                label=f"用券方案{index + 1}：{coupon.title}",
                items=[
                    {"code": item.code, "name": item.name, "quantity": 1, "unit_price": item.price}
                    for item in chosen
                ],
                estimated_subtotal=round(subtotal, 2),
                coupon=coupon,
                notes=combo_notes,
            )
        )

    if not combos:
        notes.append("没有可用的结构化券，省钱模式只给出菜单价基准方案")
    return combos, notes


def budget_note(coupon: Coupon, current_subtotal: Optional[float]) -> str:
    """给展示层用的门槛说明，未知即明说未知。"""
    if coupon.threshold is None:
        return "门槛：接口未返回"
    if current_subtotal is None:
        return f"门槛：¥{coupon.threshold:.1f}（当前组合金额未知）"
    if current_subtotal + config.BUDGET_TOLERANCE_YUAN < coupon.threshold:
        return f"门槛：¥{coupon.threshold:.1f}，还差 ¥{coupon.threshold - current_subtotal:.1f}"
    return f"门槛：¥{coupon.threshold:.1f}，已满足"
