---
name: mcfate
description: 麦门食运局 McFate——面向麦当劳点餐的游戏化推荐助手。当用户说“不知道吃什么”“帮我决定”“预算内怎么点”“把这些券用掉”“抽个盲盒”“看看我的菜单图鉴”“换个口味”时使用。基于真实菜单、官方算价与门店可用券，给出可解释、可复现的候选方案，并支持个人探索记录。
---

# 麦门食运局 McFate

把“今天吃什么”变成一次有依据的抽取：真实菜单 → 硬约束过滤 → 可解释打分 → 加权抽取 →
官方算价 → 券的真实节省。游戏化只是外壳，**价格与优惠必须可追溯**。

## 三条铁律（任何情况下不得违反）

1. **价格只认官方**：菜单价来自 `query-meals`，最终应付金额只能来自 `calculate-price`。
   算价失败就明确说“未核价”，禁止用菜单价、估算或“大概”替代。
2. **券不许猜**：接口没返回的门槛、适用范围、叠加规则一律标注“未验证”；券面额不等于净收益，
   为凑门槛多花的钱必须单独说明。
3. **不主动产生副作用**：不调用 `create-order`、`cancel-order`、`auto-bind-coupons`、
   `draw-lottery`、`mall-create-order`、`party-order-create`。本 Skill 的终点是
   “核价结果 + 订单摘要 + 等待用户明确确认”，确认后才由用户决定是否下单。

## 适用与不适用

适用：不知道吃什么、预算内选餐、想用掉真实可用的券、想尝鲜、想记录自己吃过什么。

不适用：需要真实支付/下单执行（超出本 Skill 边界）、需要历史订单分析（MCP 无此数据）、
营养或医疗建议（只做菜单字段的客观呈现）。

## 环境准备

- 运行环境：Python 3.9+，仅标准库；脚本入口 `scripts/mcfate.py`，以本文件所在目录为根。
  Windows 下把命令里的 `python3` 换成 `python`。
- 个人档案默认落在 `~/.mcfate/profile.json`，可用 `--profile` 或环境变量 `MCFATE_HOME` 改位置。
- 所有脚本输出 JSON；模型读 JSON 里的 `lines` / `ranked` 再组织成自然语言，**不要改金额与状态**。

## 标准工作流

### 第 0 步：确定门店与取餐方式（缺一不可）

1. 到店自取 / 得来速：`query-nearby-stores(searchType=2, city, keyword, beType=1|5)`。
   `beType=5` 时返回值带 `beCode`，后续调用必须一起传。
2. 外送 / 团餐：`delivery-query-addresses` → `delivery-query-stores(addressId, beType=2|6)`。

只有门店、预算、取餐方式都无法安全推断时才追问用户；其余用合理默认值（到店自取、不限预算）。

### 第 1 步：抓菜单并落地快照

调用 `query-meals(storeCode, orderType, beType[, beCode])`，把**原始返回**写入
`.mcfate/cache/menu-<storeCode>-<orderType>.json`。后续 payload 用 `menu_file` 引用，
避免整份菜单反复粘贴；同一门店当天可复用，跨天重新拉取。

### 第 2 步：按模式出候选

三种模式共用同一套过滤与打分，只是权重与产出不同：

| 模式 | 触发语 | 默认风格 | 产出 |
|---|---|---|---|
| A 替我决定 | 不知道吃什么 / 帮我决定 | balanced | 3 个候选 + 理由 |
| B 麦运省钱 | 想用券 / 省钱 / 预算内最优 | frugal | 券组合 + 算价请求 |
| C 命运盲盒 | 抽一个 / 盲盒 / 来点刺激 | 由用户选 steady/adventure/frugal | 1 个揭晓结果 |

```bash
python3 scripts/mcfate.py recommend --input payload.json
```

payload 最小形态（完整字段见 `references/algorithm.md`）：

```json
{
  "mode": "decide",
  "budget": 35,
  "exclude": ["咖啡"],
  "count": 3,
  "seed": 2026,
  "store": {"code": "门店编码", "name": "门店名", "order_type": 1, "be_type": 1},
  "menu_file": ".mcfate/cache/menu-1234567-1.json"
}
```

省钱模式额外传入 `coupons_file`（`query-store-coupons` 的原始返回）。
脚本会输出 `combos` 与 `pricing_requests`——后者是可直接投喂 `calculate-price` 的参数。

### 第 3 步：官方算价并重排

对每个 `pricing_requests[i]` 分别调用 `calculate-price`（带券 / 不带券各一次），
把原始返回填进 `entries[].quote`，再执行：

```bash
python3 scripts/mcfate.py rerank --input quotes.json
```

输出 `ranked` 与 `recommended`。`state` 三种取值：
`priced`（可成交）/ `over_budget`（超预算）/ `unverified`（算价失败，**不展示金额**）。

“这张券省了多少”只在同一组合的带券与不带券两次算价都成功时才能说，由
`attribute_savings` 保证；否则只说官方优惠总额，不归因到具体券。

### 第 4 步：记录与图鉴（用户主动要求时）

```bash
python3 scripts/mcfate.py record --code 1100 --name 巨无霸 --category 巨无霸牛鱼肉堡 --status liked
python3 scripts/mcfate.py profile --menu .mcfate/cache/menu-1234567-1.json
```

`--status` 取 `tried | liked | disliked | rejected`。只记录用户明确说过的内容，
**不得**从推荐结果或对话推测“他吃过了”。推荐过的餐品进 `recent`，不等于已尝试。

## 模型与脚本的分工

| 环节 | 归属 |
|---|---|
| 解析自然语言里的预算、排除项、口味偏好、模式 | 模型 |
| 选择门店/取餐方式、调用 MCP、保存原始返回 | 模型 |
| 硬约束过滤、四分项打分、加权抽取、组合生成、券判定、预算比较 | 脚本 |
| 措辞、追问、确认下单前的摘要 | 模型 |

脚本里没有任何网络调用，也不持有凭据：MCP 只由模型一侧发起。

## 输出规范

一次回复至少包含：候选名称与菜单价（标注“官方菜单价”）、推荐理由（来自 `lines`）、
是否满足预算（未知就写未知）、券的使用状态（可用/需加购/未验证/不适用）、
以及下一步动作：`就它了 / 再来一个 / 换个口味`。

金额必须带来源：`官方算价 ¥27.5`、`菜单价 ¥26.5（未核价）`。不得出现无来源的数字。
游戏化文案可以活泼，但不得模糊价格与门槛。

## 降级策略

| 情况 | 处理 |
|---|---|
| menu 为空 / 解析不到餐品 | 明确“未获取到在售菜单”，提示重新调用 `query-meals`，不编造餐品 |
| `calculate-price` 失败 | 该方案 `unverified`，不展示金额，其余方案照常 |
| 无结构化券（`query-my-coupons` 返回文本或空数组） | 省钱模式退化为“菜单价方案”，说明“没有可核验的券” |
| 券门槛/范围缺失 | 标 `unverified`，不计入节省 |
| 候选不足 | 返回较少结果，绝不重复或虚构 |
| 个人档案缺失/损坏 | 按空档案处理，历史相关指标取中性值并说明 |
| `available-coupons` 报 schema 错误 | 直接跳过该接口，不重试、不假装成功 |

## 合规与隐私

- 不写入、不展示任何令牌、账号 ID、traceId；示例数据一律脱敏。
- 不收集与点餐无关的个人信息；档案只存餐品偏好。
- 输出属参考信息，非麦当劳官方产品；价格与供应以官方渠道实时结果为准。

## 参考文档

- `references/mcp-tools.md`：各 MCP 工具的真实入参/返回结构与调用顺序
- `references/algorithm.md`：payload 全字段、评分细节、券判定与算价规则
- `references/gameplay.md`：三种模式的文案规范、图鉴与任务设计
- `examples/`：可直接运行的示例 payload 与输出
