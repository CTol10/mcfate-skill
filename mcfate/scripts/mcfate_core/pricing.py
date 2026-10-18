"""官方算价与预算判定。

最终价格只能来自 calculate-price；本模块不做任何“估价替代官方价”的行为。
算价失败时 state 必须是 unverified，payable 必须为 None。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from . import config
from .models import Combo, Quote


def format_yuan(value: Optional[float]) -> str:
    if value is None:
        return "未核价"
    return f"¥{value:.1f}"


def build_request(
    store_code: str,
    order_type: int,
    be_type: int,
    items: Sequence[Dict[str, Any]],
    be_code: Optional[str] = None,
    coupon_id: Optional[str] = None,
    coupon_code: Optional[str] = None,
    reservation_date: Optional[str] = None,
    need_tableware: Optional[bool] = None,
) -> Dict[str, Any]:
    """生成可直接传给 calculate-price 的参数对象（不含任何副作用）。

    注意：calculate-price 没有 takeWayCode 参数，取餐方式由算价返回的 takeWayList 提供，
    下单时才使用。这里只构造算价真正接受的字段，避免 additionalProperties 报错。
    """
    payload: Dict[str, Any] = {
        "storeCode": str(store_code),
        "orderType": int(order_type),
        "beType": int(be_type),
        "items": [
            {"productCode": str(row["code"]), "quantity": int(row.get("quantity") or 1)} for row in items
        ],
    }
    if be_code:
        payload["beCode"] = str(be_code)
    if coupon_id:
        payload["items"][0]["couponId"] = str(coupon_id)
    if coupon_code:
        payload["items"][0]["couponCode"] = str(coupon_code)
    if reservation_date:
        payload["reservationDate"] = str(reservation_date)
    if need_tableware is not None:
        payload["needTableware"] = bool(need_tableware)
    return payload


def price_requests(
    combos: Sequence[Combo],
    store_code: str,
    order_type: int,
    be_type: int,
    be_code: Optional[str] = None,
    max_calls: int = config.MAX_PRICE_CALLS,
) -> List[Dict[str, Any]]:
    """把组合转成算价请求，数量受控，避免对整份菜单无差别调用。"""
    requests: List[Dict[str, Any]] = []
    for combo in list(combos)[:max_calls]:
        requests.append(
            {
                "label": combo.label,
                "with_coupon": build_request(
                    store_code,
                    order_type,
                    be_type,
                    combo.items,
                    be_code=be_code,
                    coupon_id=combo.coupon.coupon_id if combo.coupon else None,
                    coupon_code=combo.coupon.coupon_code if combo.coupon else None,
                ),
                "without_coupon": build_request(store_code, order_type, be_type, combo.items, be_code=be_code),
            }
        )
    return requests


def judge(quote: Quote, budget: Optional[float]) -> Dict[str, Any]:
    """把算价结果转成可展示的判定。"""
    if not quote.ok:
        return {
            "state": config.PRICE_UNVERIFIED,
            "payable": None,
            "original": None,
            "official_discount": None,
            "over_budget": None,
            "note": f"官方算价失败：{quote.error or '未知原因'}。本轮不展示最终价格，也不会用估价替代。",
        }

    over = None
    if budget is not None and quote.payable is not None:
        over = quote.payable > budget + config.BUDGET_TOLERANCE_YUAN

    if over:
        return {
            "state": config.PRICE_OVER_BUDGET,
            "payable": quote.payable,
            "original": quote.original,
            "official_discount": quote.discount,
            "over_budget": True,
            "note": f"官方算价 {format_yuan(quote.payable)}，超出预算 {format_yuan(quote.payable - budget)}",
        }

    saved = f"，官方优惠 {format_yuan(quote.discount)}" if quote.discount else "，官方未体现优惠"
    return {
        "state": config.PRICE_PRICED,
        "payable": quote.payable,
        "original": quote.original,
        "official_discount": quote.discount,
        "over_budget": False if over is False else None,
        "note": f"官方算价 {format_yuan(quote.payable)}{saved}",
    }


def rerank(entries: Sequence[Dict[str, Any]], budget: Optional[float] = None) -> List[Dict[str, Any]]:
    """按“是否可核价 → 是否超预算 → 应付金额”排序。"""
    enriched: List[Dict[str, Any]] = []
    for entry in entries:
        quote = entry.get("quote")
        verdict = judge(quote, budget) if isinstance(quote, Quote) else judge(Quote(ok=False, error="未提供算价结果"), budget)
        row = dict(entry)
        row.pop("quote", None)
        row.update(verdict)
        enriched.append(row)

    def sort_key(row: Dict[str, Any]):
        state_rank = {
            config.PRICE_PRICED: 0,
            config.PRICE_OVER_BUDGET: 1,
            config.PRICE_UNVERIFIED: 2,
        }.get(row["state"], 3)
        payable = row.get("payable")
        return (state_rank, payable if payable is not None else float("inf"), str(row.get("label") or ""))

    return sorted(enriched, key=sort_key)
