# 麦门食运局 McFate

> 麦当劳程序员节创意开发大赛参赛作品。非麦当劳官方产品，输出仅供参考；>   
> 餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准。

「今天不知道吃什么」这件事，通常不是缺选项，而是缺一个**敢下决定的理由**。  
McFate 用真实在售菜单做签筒、用可解释的规则做签文，把点餐变成一次可复盘的抽取：  
推荐要说得清依据，价格要经得起核对，优惠不能靠猜。

## 一、已实现的能力

| 能力        | 状态     | 说明                                         |
| --------- | ------ | ------------------------------------------ |
| 真实菜单候选池   | ✅      | 只从 `query-meals` 返回建模，无自造商品                |
| 模式 A 替我决定 | ✅      | 自然语言约束 → 硬过滤 → 打分 → 加权抽取 → 3 个候选           |
| 模式 B 麦运省钱 | ✅      | 券判定 + 组合生成 + 算价请求 + 官方价重排                  |
| 模式 C 命运盲盒 | ✅      | 稳妥 / 冒险 / 精算三种风格，可复现随机                     |
| 个人探索图鉴    | ✅      | 本地 JSON，只记显式标记；品类进度、连续记录                   |
| 预算硬约束     | ✅      | 超预算直接淘汰；价格缺失则标“无法确认”，不假装满足                 |
| 可解释推荐     | ✅      | 四分项 + 理由 + 数据缺口，理由全部来自真实字段                 |
| 官方核价      | ✅      | 只读 `calculate-price`；失败即 `unverified`，不出金额 |
| 券的真实节省    | ✅      | 需同组合两次算价才归因，否则只说官方优惠总额                     |
| 下单        | ⛔ 刻意不做 | 无 create-order 等副作用调用，止于订单摘要 + 用户确认        |

## 二、目录结构

```
mcfate/
├── SKILL.md                     # 触发条件、铁律、工作流、降级策略
├── references/
│   ├── mcp-tools.md             # 实测过的工具契约（字段、坑、降级）
│   ├── algorithm.md             # payload 全字段、评分细节、券规则、命令
│   └── gameplay.md              # 三种风格、文案规范、图鉴与示例对话
├── scripts/
│   ├── mcfate.py                # CLI 入口
│   ├── mcfate_core/
│   │   ├── config.py            # 权重与阈值（唯一可调入口，含校验）
│   │   ├── normalize.py         # MCP 返回 → 领域对象（容错、不推断）
│   │   ├── constraints.py       # 硬约束过滤
│   │   ├── scoring.py           # novelty/preference/diversity/mission_fit
│   │   ├── sampler.py           # softmax 加权抽取，seed 可复现
│   │   ├── coupons.py           # 券判定、组合生成、节省归属
│   │   ├── pricing.py           # 算价请求构造、预算判定、重排
│   │   ├── profile.py           # 个人图鉴（原子写入、损坏降级）
│   │   ├── render.py            # 文本块渲染
│   │   └── cli.py               # 子命令编排
│   └── tests/                   # 78 个单元/端到端测试
└── examples/                    # 可运行 payload 与真实输出
```

## 三、MCP 调用流程

```
query-nearby-stores / delivery-query-stores        # 定门店 + 取餐方式
        ↓
query-meals                    → 落盘 .mcfate/cache/menu-<storeCode>-<orderType>.json
        ↓
query-store-coupons            → 结构化券（无券时 data: []）
        ↓
mcfate recommend               → 候选 / 组合 / pricing_requests
        ↓
calculate-price (带券 & 不带券) → 官方应付金额
        ↓
mcfate rerank                  → 排序 + 预算判定 + 节省归因
        ↓
订单摘要 → 用户明确确认（之后是否下单，由用户走官方渠道决定）
```

只读工具：`query-meals`、`query-meal-detail`、`list-nutrition-foods`、  
`query-store-coupons`、`query-my-coupons`、`query-nearby-stores`、  
`delivery-query-stores`、`delivery-query-addresses`、`calculate-price`。

**不调用**：`create-order`、`cancel-order`、`auto-bind-coupons`、`draw-lottery`、  
`mall-create-order`、`party-order-create`。理由：这些会改变账户或产生交易，  
不属于“推荐”所需的授权范围。

## 四、算法与券规则（摘要）

- `score = 0.40·novelty + 0.25·preference + 0.20·diversity + 0.15·mission_fit`    
  （风格可切换：稳妥 0.20/0.35/0.20/0.25，冒险 0.50/0.15/0.15/0.20，精算 0.15/0.20/0.15/0.50）
- 无历史记录时，novelty / preference / diversity 取中性值并**显式告知**，不把“未知”当“没吃过”。
- 抽取：前 8 名进池，按 `softmax(score/0.08)` 无放回抽样；同 seed 结果完全一致。
- 主餐优先：主餐足够时不把饮料/小食当正餐推荐（`classify_role` + `prioritize_main`）。
- 券：`not_applicable` / `needs_extra` / `usable` / `unverified` 四态；门槛未知即 `unverified`。
- 节省归因必须“同商品、带券与不带券两次算价都成功”，否则不归因到具体券。
- 凑门槛加购的支出单独列出；预算内凑不到就明说凑不到。

## 五、测试

```bash
cd mcfate/scripts && python3 -m unittest discover -s tests -t .
# Ran 78 tests ... OK
```

覆盖任务书要求的 15 个场景，另加：接口空态/错误态归一化、权重校验、主餐优先、  
档案损坏降级、导入合并、幂等性、输出敏感字段扫描。

## 六、已知限制与降级

| 限制                        | 现状                                            | 降级                        |
| ------------------------- | --------------------------------------------- | ------------------------- |
| `available-coupons` 调用失败  | MCP 返回 schema 校验错误（`data/data must be array`） | 跳过该接口，不重试、不伪造券            |
| `query-my-coupons` 返回自然语言 | 无券时返回“暂无可用优惠券”文本                              | 判为 `unparsed`，不作为结构化券     |
| 券门槛/范围字段不保证存在             | 实测空券时无字段可参考                                   | 缺失即 `unverified`，不计入节省    |
| 无历史订单数据                   | MCP 不提供订单历史                                   | 图鉴只用显式标记，不推断“吃过”          |
| 菜单无库存/售罄字段                | `query-meals` 未返回库存                           | 以官方算价/下单结果为最终判断           |
| 无正式比赛规则文档                 | 仓库无 README/RANKING.md                         | 按通用 Agent Skill 规范实现，见第八节 |

## 七、本地运行（至少 5 个中文示例）

```bash
cd mcfate

# 1. 不知道吃什么
python3 scripts/mcfate.py recommend --input examples/sample-payload.json

# 2. 预算 35 + 排除咖啡 → 改 sample-payload.json 的 budget/exclude 即可
# 3. 省钱模式（带券）
python3 scripts/mcfate.py recommend --input examples/save-payload.json

# 4. 官方算价重排（可成交 / 原价 / 失败三态）
python3 scripts/mcfate.py rerank --input examples/quotes-payload.json

# 5. 记录与图鉴
python3 scripts/mcfate.py record --code 1100 --name 巨无霸 --category 巨无霸牛鱼肉堡 --status liked
python3 scripts/mcfate.py profile --menu examples/sample-menu.json
```

可直接对助手说的话：

1. 「今天不知道吃什么，帮我决定」
2. 「预算 35，最好能用掉合适的券，别总推荐一样的」
3. 「抽个盲盒，我吃腻汉堡了，来点刺激的」
4. 「再来一个，刚那个不想吃」
5. 「巨无霸我挺喜欢的，记一下，然后看看我的图鉴」

## 八、与同类作品的差异

榜单里以“省钱/券/预算/多人”为主的项目，核心是**在已选餐品上做最优解**。  
McFate 的差异点在决策层而非计算层：

| 维度    | 常见省钱/券类作品 | McFate                        |
| ----- | --------- | ----------------------------- |
| 起点    | 用户已有想吃的目标 | 用户没有目标，需要被决定                  |
| 核心    | 优惠最大化     | 决策 + 抽签 + 图鉴，省钱只是其中一档         |
| 随机性   | 通常无       | softmax 加权抽样，可复现且能“再来一个”      |
| 数据诚实度 | 常用估算价/推算券 | 价格只认 calculate-price，券缺失即标未验证 |
| 账户副作用 | 可能顺带领券/绑券 | 一律不碰有副作用的接口                   |

> 说明：本地没有 RANKING.md 与榜单项目说明，以上按公开品类做定位对比，>   
> 报名后应以官方榜单实际描述为准再校正。

## 九、比赛提交待补事项

- [x] SKILL.md 及合法 frontmatter
- [x] 可运行脚本 + 单元测试
- [x] 示例 payload 与输出
- [x] 无真实 Token / 账号凭证 / 他人个人信息（示例数据已脱敏）
- [ ] 按官方模板补 `README`/`RANKING` 要求的必交文件（当前仓库无这些文件，无法核对字段）
- [ ] 打包成 zip 提交（`scripts/` 下的 skill-creator 提供 `package_skill.py`）
- [ ] 报名信息与作品链接填写
- [ ] 提交前复核：示例中的门店编码、券码均为占位符
