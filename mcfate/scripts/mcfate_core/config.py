"""McFate 集中配置：权重、阈值、风格预设。

设计原则：
1. 所有可调参数集中在此文件，业务代码不得散落魔法数字。
2. 权重改变必须能通过 `Weights` 的校验（四项之和为 1）。
3. 这里不做任何 I/O，方便单元测试直接构造。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping


@dataclass(frozen=True)
class Weights:
    """软偏好评分权重，四项之和必须为 1。"""

    novelty: float = 0.40
    preference: float = 0.25
    diversity: float = 0.20
    mission_fit: float = 0.15

    def __post_init__(self) -> None:
        for name, value in self.as_dict().items():
            if value < 0:
                raise ValueError(f"权重不能为负数：{name}={value}")
        total = sum(self.as_dict().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"权重之和必须为 1，当前为 {total:.4f}")

    def as_dict(self) -> Dict[str, float]:
        return {
            "novelty": self.novelty,
            "preference": self.preference,
            "diversity": self.diversity,
            "mission_fit": self.mission_fit,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, float]) -> "Weights":
        """从外部配置构造权重，缺项用默认值补齐，未知键直接报错。"""
        unknown = set(mapping) - {"novelty", "preference", "diversity", "mission_fit"}
        if unknown:
            raise ValueError(f"未知权重项：{sorted(unknown)}")
        base = cls().as_dict()
        base.update({k: float(v) for k, v in mapping.items()})
        return cls(**base)


# 四种抽取风格对应的权重组合。balanced 为任务书给出的初始权重。
STYLE_WEIGHTS: Dict[str, Weights] = {
    # 稳妥派：少踩雷
    "steady": Weights(novelty=0.20, preference=0.35, diversity=0.20, mission_fit=0.25),
    # 默认均衡
    "balanced": Weights(),
    # 冒险派：多尝鲜
    "adventure": Weights(novelty=0.50, preference=0.15, diversity=0.15, mission_fit=0.20),
    # 精算派：先看钱
    "frugal": Weights(novelty=0.15, preference=0.20, diversity=0.15, mission_fit=0.50),
}

DEFAULT_STYLE = "balanced"

# 结果与抽取
DEFAULT_RESULT_COUNT = 3
MAX_RESULT_COUNT = 5
RANDOM_POOL_SIZE = 8  # 加权抽取的候选池大小
RANDOM_TEMPERATURE = 0.08  # softmax 温度：越小越接近取最高分

# 优惠组合与算价
MAX_COMBOS = 12
MAX_PRICE_CALLS = 6  # 单轮最多发起的官方算价次数

# 个人记录
RECENT_LIMIT = 20
RECENT_STRONG_WINDOW = 3  # 最近 N 条视为“刚刚推过”
REJECT_MEMORY_LIMIT = 10

# 缺失历史数据时的中性分，避免把“未知”当成“没吃过”或“不喜欢”
NOVELTY_UNKNOWN = 0.50
PREFERENCE_UNKNOWN = 0.50
DIVERSITY_UNKNOWN = 0.60
MISSION_FIT_UNKNOWN = 0.60

# 预算比较容差（元），避免 34.999 判成超预算
BUDGET_TOLERANCE_YUAN = 0.01

# 菜单中的“营销位”分类，不作为口味品类参与新鲜感计算
MARKETING_BUCKETS = (
    "人气热卖",
    "精选单人餐",
    "小食拼盘/多人餐",
    "500大卡套餐",
    "随心配1+1",
    "大堡口福单人餐",
    "小食甜品/其他",
    "开心乐园",
)

# 状态机：优惠券判定结果
COUPON_USABLE = "usable"  # 当前方案明确可用
COUPON_NEEDS_EXTRA = "needs_extra"  # 可用但需加购到门槛
COUPON_NOT_APPLICABLE = "not_applicable"  # 明确不适用
COUPON_UNVERIFIED = "unverified"  # 信息不足，无法判断

# 价格状态
PRICE_PRICED = "priced"
PRICE_OVER_BUDGET = "over_budget"
PRICE_UNVERIFIED = "unverified"
