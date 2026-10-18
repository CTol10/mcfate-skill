# 本地 UX 原型

把 Skill 的回合结构做成能点着玩的界面。**不是**产品界面，是让人在 30 秒内
感知「抽签 → 揭晓 → 三个动作 → 再抽」这个节奏到底长什么样。

```bash
# 在仓库根目录
python demo/server.py            # 默认 http://127.0.0.1:8788
python demo/server.py --port 9000
```

只绑 `127.0.0.1`，不对外。

## 它调用的是同一套引擎

`server.py` 直接 `from mcfate_core import cli` 并调用 `cli.build_recommendation()`，
与命令行共用打分、抽样、券判定、预算过滤。**没有第二套 JS 实现**，
所以界面上看到的分数与 `python scripts/mcfate.py recommend` 完全一致。

这一点是刻意的：如果前端另写一份算法，演示就会和 Skill 真实行为漂移，
演示越好看，误导越深。

## 数据边界

| 项 | 演示环境 | 真实 Skill |
|---|---|---|
| 菜单 | `examples/sample-menu.json` 快照（官方菜单价） | `query-meals` 实时拉取 |
| 门店 | 占位「演示门店」 | `query-nearby-stores` 真实门店 |
| 应付金额 | **不提供** | `calculate-price` 官方算价 |
| 券 | 示例结构 | `query-store-coupons` / `query-my-coupons` |

所以「就它了」只给订单摘要，并明确写着「这不是应付金额」。
演示环境没有 `calculate-price`，编一个数字出来才是最坏的做法。

## 已实现的交互

- 抽签：签筒抖动 → 飞签 → 卡片浮现，签号来自真实 `sign_no(seed, code)`
- 三种模式：盲盒（reveal 单签）、替我决定（board 三签）、麦运省钱（组合 + 核价请求）
- 三个动作：就它了 / 再来一个 / 换个口味；「再来一个」会把当前编码写进 `rejected`
- 换口味：只改一个维度（预算 / 风格 / 品类），改完重抽
- 图鉴：记录喜欢 / 吃过了 / 不喜欢，实时影响后续推荐的 `novelty` 与 `diversity`
- 分数明细：每张卡都展开 novelty / preference / diversity / mission_fit 四条真实分数

## 已知限制

- 单人本地演示，无并发保护；`ThreadingHTTPServer` 够用但不适合公网
- 图鉴存在 `demo/.demo-profile.json`（已 gitignore），删掉即重置
- 盲盒每次抽签 `seed+1`，否则同 seed 会抽出同一支 —— 这是确定性设计的正常表现
