"""McFate 确定性推荐内核。

模块划分：
- config: 权重与阈值（唯一可调参数入口）
- normalize: MCP 返回 → 领域对象（容错、不推断）
- constraints: 硬约束过滤
- scoring: 四分项软评分
- sampler: 可复现加权抽取
- coupons: 券判定 / 组合 / 节省归属
- pricing: 官方算价与预算判定
- profile: 本地探索图鉴
- render: 文本块渲染
- cli: 命令行编排
"""

__all__ = ["config", "normalize", "constraints", "scoring", "sampler", "coupons", "pricing", "profile", "render", "cli"]
__version__ = "1.0.0"
