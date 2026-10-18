"""把 MCP 原始返回归一化成领域对象。

原则：
1. 只读已知字段，缺字段就当“未知”，绝不猜值。
2. 任何解析失败都不抛异常，转成可展示的降级状态，避免整个推荐链路中断。
3. 金额单位统一：菜单/券为元，calculate-price 返回分为分，这里统一转成元。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config
from .models import Coupon, MenuItem, Quote, classify_role

_PRICE_CLEAN = re.compile(r"[¥￥元\s,]")


def envelope(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """取出 MCP 返回中的 data，并返回错误说明（若有）。"""
    if not isinstance(raw, dict):
        return None, "返回不是 JSON 对象"
    if raw.get("success") is False:
        return None, str(raw.get("message") or "接口返回失败")
    code = raw.get("code")
    if code is not None and code not in (200, "200"):
        return None, str(raw.get("message") or f"接口返回 code={code}")
    data = raw.get("data")
    if data is None:
        return None, "返回缺少 data 字段"
    return data if isinstance(data, dict) else {"_list": data}, None


def to_float(value: Any) -> Optional[float]:
    """把 '33.5' / '¥33.5' / 3350 这类值转成元；无法解析返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _PRICE_CLEAN.sub("", str(value)).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_category(name: str) -> str:
    return "".join(str(name).split())


def _pick_category(categories: Sequence[str]) -> str:
    """同一餐品可能挂在多个分类下，优先取非营销位分类。"""
    if not categories:
        return "未分类"
    non_bucket = [c for c in categories if c not in config.MARKETING_BUCKETS]
    return (non_bucket or list(categories))[-1]


def normalize_menu(raw: Any) -> List[MenuItem]:
    """解析 query-meals 返回，也兼容精简后的 {"items": [...]} 结构。"""
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return _normalize_compact(raw["items"])

    data, _error = envelope(raw)
    if data is None:
        return []

    meals = data.get("meals") or {}
    categories = data.get("categories") or []
    if not isinstance(meals, dict) or not meals:
        return []

    cat_index: Dict[str, List[str]] = {}
    tag_index: Dict[str, List[str]] = {}
    for category in categories:
        name = _normalize_category(category.get("name") or "")
        for meal in category.get("meals") or []:
            code = str(meal.get("code") or "").strip()
            if not code:
                continue
            cat_index.setdefault(code, []).append(name or "未分类")
            tags = [str(t) for t in (meal.get("tags") or []) if t]
            if tags:
                tag_index.setdefault(code, [])
                for tag in tags:
                    if tag not in tag_index[code]:
                        tag_index[code].append(tag)

    items: List[MenuItem] = []
    for code, meal in meals.items():
        if not isinstance(meal, dict):
            continue
        name = str(meal.get("name") or "").strip()
        if not name:
            continue
        key = str(code).strip()
        category = _pick_category(cat_index.get(key, []))
        items.append(
            MenuItem(
                code=key,
                name=name,
                price=to_float(meal.get("currentPrice")),
                original_price=to_float(meal.get("originalPrice")),
                category=category,
                role=classify_role(name, category),
                tags=tuple(tag_index.get(key, [])),
                discount_type=meal.get("discountType"),
                can_with_order=bool(meal.get("canWithOrder")),
                image=meal.get("image"),
            )
        )
    return items


def _normalize_compact(items: Iterable[Any]) -> List[MenuItem]:
    result: List[MenuItem] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if not code or not name:
            continue
        result.append(
            MenuItem(
                code=code,
                name=name,
                price=to_float(row.get("price", row.get("currentPrice"))),
                original_price=to_float(row.get("original_price", row.get("originalPrice"))),
                category=_normalize_category(row.get("category") or "未分类"),
                role=classify_role(name, _normalize_category(row.get("category") or "未分类")),
                tags=tuple(str(t) for t in (row.get("tags") or []) if t),
                discount_type=row.get("discount_type") or row.get("discountType"),
                can_with_order=bool(row.get("can_with_order")),
            )
        )
    return result


# 券接口可能使用的字段别名；只用出现过的键，不补默认值。
_TITLE_KEYS = ("title", "couponName", "name", "couponTitle")
_AMOUNT_KEYS = ("amount", "discountAmount", "faceValue", "value", "couponAmount")
_THRESHOLD_KEYS = ("threshold", "minAmount", "minSpend", "limitAmount", "useThreshold")
_VALID_KEYS = ("tradeDateTime", "validUntil", "expireTime", "endTime")


def _first(row: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _maybe_cents(key: str, value: Optional[float]) -> Tuple[Optional[float], bool]:
    """分/元单位判断：仅当字段名显式带 cent/fen 时按分处理。"""
    if value is None:
        return None, False
    lowered = key.lower()
    if "cent" in lowered or lowered.endswith("fen"):
        return round(value / 100.0, 2), False
    return round(value, 2), True


def normalize_coupons(raw: Any, source: str = "query-store-coupons") -> Tuple[List[Coupon], str, str]:
    """解析券接口，返回 (券列表, 状态, 说明)。

    状态取值：ok / empty / unparsed / error。
    unparsed 表示接口返回的是自然语言文本（如 query-my-coupons），不能当作结构化券使用。
    """
    if isinstance(raw, str):
        return [], "unparsed", "该接口返回自然语言摘要，无法作为结构化券使用"
    if raw is None:
        return [], "empty", "未提供券数据"
    if isinstance(raw, dict) and raw.get("success") is False:
        return [], "error", str(raw.get("message") or "券接口返回失败")

    rows: Any = None
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        rows = raw["data"]
    elif isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get("coupons"), list):
        rows = raw["coupons"]

    if rows is None:
        return [], "unparsed", "券返回结构不是数组，已忽略"
    if not rows:
        return [], "empty", "该门店/账户当前没有可用的结构化券"

    coupons: List[Coupon] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _first(row, _TITLE_KEYS)
        if not title:
            continue
        products = row.get("products") or []
        codes: List[str] = []
        names: List[str] = []
        for product in products if isinstance(products, list) else []:
            if not isinstance(product, dict):
                continue
            code = product.get("productCode")
            if code not in (None, ""):
                codes.append(str(code))
            pname = product.get("productName")
            if pname:
                names.append(str(pname))

        amount_key = next((k for k in _AMOUNT_KEYS if row.get(k) not in (None, "")), "")
        face_value, assumed = _maybe_cents(amount_key, to_float(row.get(amount_key)) if amount_key else None)
        threshold_key = next((k for k in _THRESHOLD_KEYS if row.get(k) not in (None, "")), "")
        threshold, threshold_assumed = _maybe_cents(
            threshold_key, to_float(row.get(threshold_key)) if threshold_key else None
        )
        valid = _first(row, _VALID_KEYS)

        coupons.append(
            Coupon(
                title=str(title),
                coupon_id=str(row["couponId"]) if row.get("couponId") not in (None, "") else None,
                coupon_code=str(row["couponCode"]) if row.get("couponCode") not in (None, "") else None,
                valid_until=str(valid) if valid is not None else None,
                product_codes=tuple(codes),
                product_names=tuple(names),
                face_value=face_value,
                threshold=threshold,
                unit_assumed=assumed or threshold_assumed,
                source=source,
            )
        )
    if not coupons:
        return [], "empty", "券列表存在但无可识别的券名，已忽略"
    return coupons, "ok", f"解析到 {len(coupons)} 张结构化券"


def normalize_quote(raw: Any) -> Quote:
    """解析 calculate-price 返回。任何异常都返回 ok=False 且 payable=None。"""
    if isinstance(raw, str):
        return Quote(ok=False, error="算价返回为文本，无法确认最终价格")
    data, error = envelope(raw)
    if data is None:
        return Quote(ok=False, error=error or "算价失败")

    if "_list" in data:
        return Quote(ok=False, error="算价返回结构异常")

    price_cent = data.get("price")
    if price_cent is None:
        return Quote(ok=False, error="算价返回缺少 price 字段")

    def yuan(key: str) -> Optional[float]:
        value = data.get(key)
        if value is None:
            return None
        number = to_float(value)
        return None if number is None else round(number / 100.0, 2)

    products = []
    for row in data.get("productList") or []:
        if not isinstance(row, dict):
            continue
        subtotal_cent = to_float(row.get("subtotal"))
        products.append(
            {
                "code": str(row.get("productCode") or ""),
                "name": row.get("productName"),
                "quantity": row.get("quantity"),
                "subtotal": None if subtotal_cent is None else round(subtotal_cent / 100.0, 2),
            }
        )

    return Quote(
        ok=True,
        payable=yuan("price"),
        original=yuan("originalPrice"),
        discount=yuan("discount") or 0.0,
        products=products,
        take_way=[
            {"code": str(t.get("code") or ""), "title": t.get("title")}
            for t in (data.get("takeWayList") or [])
            if isinstance(t, dict)
        ],
    )
