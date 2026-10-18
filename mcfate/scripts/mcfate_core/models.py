"""McFate 领域模型。

只做数据承载与轻量序列化，不含业务判断，方便被 normalize / scoring / cli 复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _clean(value: Any) -> Any:
    """去掉 None 字段，保证输出的 JSON 紧凑可读。"""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


ROLE_MAIN = "main"
ROLE_SIDE = "side"
ROLE_DRINK = "drink"
ROLE_LABEL = {ROLE_MAIN: "主餐", ROLE_SIDE: "小食", ROLE_DRINK: "饮品"}

_DRINK_CATEGORY_HINTS = ("饮品", "咖啡", "麦咖啡")
_DRINK_NAME_HINTS = ("可乐", "雪碧", "芬达", "咖啡", "拿铁", "美式", "牛奶", "果汁", "红茶", "奶茶", "雪冰", "麦炫酷", "柠")
_MAIN_NAME_HINTS = ("套餐", "三件套", "四件套", "双人餐", "单人餐", "拼盘", "四宫格", "随心配", "堡", "卷", "饭", "鸡", "鱼", "牛肉")
_SIDE_CATEGORY_HINTS = ("小食", "甜品", "蘸酱")
_SIDE_NAME_HINTS = ("薯条", "薯饼", "玉米", "苹果片", "冰淇淋", "圆筒", "新地", "派", "酱")


def classify_role(name: str, category: str) -> str:
    """把餐品粗分为主餐 / 小食 / 饮品，避免把一杯可乐当成“今天吃什么”的答案。"""
    text = f"{name}{category}"
    if any(hint in category for hint in _DRINK_CATEGORY_HINTS):
        return ROLE_DRINK
    if any(hint in name for hint in _DRINK_NAME_HINTS) and not any(
        hint in name for hint in ("堡", "卷", "饭", "套餐")
    ):
        return ROLE_DRINK
    if any(hint in name for hint in _MAIN_NAME_HINTS[:9]):
        return ROLE_MAIN
    if any(hint in category for hint in _SIDE_CATEGORY_HINTS) or any(hint in text for hint in _SIDE_NAME_HINTS):
        return ROLE_SIDE
    return ROLE_MAIN


@dataclass
class MenuItem:
    """来自 query-meals 的真实在售餐品。"""

    code: str
    name: str
    price: Optional[float]  # 官方菜单现价（元），未知为 None
    original_price: Optional[float]  # 官方划线价（元）
    category: str = "未分类"
    role: str = ROLE_MAIN
    tags: Tuple[str, ...] = ()
    discount_type: Optional[str] = None
    can_with_order: bool = False
    image: Optional[str] = None

    @property
    def price_label(self) -> str:
        if self.price is None:
            return "价格未提供"
        return f"¥{self.price:.1f}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "original_price": self.original_price,
            "category": self.category,
            "role": self.role,
            "tags": list(self.tags),
            "discount_type": self.discount_type,
            "can_with_order": self.can_with_order,
        }


@dataclass
class Coupon:
    """来自 query-store-coupons / query-my-coupons 的券。

    字段全部可能是 None：接口未返回即视为“未知”，不得自行推断。
    """

    title: str
    coupon_id: Optional[str] = None
    coupon_code: Optional[str] = None
    valid_until: Optional[str] = None
    product_codes: Tuple[str, ...] = ()
    product_names: Tuple[str, ...] = ()
    face_value: Optional[float] = None  # 券面额（元），未知为 None
    threshold: Optional[float] = None  # 使用门槛（元），未知为 None
    unit_assumed: bool = False  # 门槛/面额单位是否为推断值
    source: str = "query-store-coupons"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "coupon_id": self.coupon_id,
            "coupon_code": self.coupon_code,
            "valid_until": self.valid_until,
            "product_codes": list(self.product_codes),
            "face_value": self.face_value,
            "threshold": self.threshold,
            "unit_assumed": self.unit_assumed,
            "source": self.source,
        }


@dataclass
class Quote:
    """calculate-price 的归一化结果。金额统一为元；失败时 payable 必须为 None。"""

    ok: bool
    payable: Optional[float] = None
    original: Optional[float] = None
    discount: Optional[float] = None
    products: List[Dict[str, Any]] = field(default_factory=list)
    take_way: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "payable": self.payable,
            "original": self.original,
            "discount": self.discount,
            "products": self.products,
            "take_way": self.take_way,
            "error": self.error,
        }


@dataclass
class Score:
    """可解释的评分结果。"""

    components: Dict[str, float]
    total: float
    reasons: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "total": round(self.total, 4),
            "reasons": self.reasons,
            "data_gaps": self.data_gaps,
        }


@dataclass
class Candidate:
    """一位候选餐品 + 推荐解释。"""

    item: MenuItem
    score: Score
    flags: Tuple[str, ...] = ()

    @property
    def code(self) -> str:
        return self.item.code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "score": self.score.to_dict(),
            "flags": list(self.flags),
        }


@dataclass
class Combo:
    """候选组合：可用于官方算价的商品清单。"""

    label: str
    items: List[Dict[str, Any]]  # [{"code","name","quantity"}]
    estimated_subtotal: Optional[float] = None
    coupon: Optional[Coupon] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _clean(
            {
                "label": self.label,
                "items": self.items,
                "estimated_subtotal": self.estimated_subtotal,
                "coupon": self.coupon.to_dict() if self.coupon else None,
                "notes": self.notes,
            }
        )
