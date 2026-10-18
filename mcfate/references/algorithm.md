# 算法与命令参考

## 1. recommend

```bash
python3 scripts/mcfate.py recommend --input payload.json [--seed 42] [--profile PATH] [--output out.json]
```

### payload 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `mode` | `decide` \| `save` \| `blindbox` | 否 | 默认 `decide`；`save` 追加组合与算价请求 |
| `style` | `steady` \| `balanced` \| `adventure` \| `frugal` | 否 | 默认：`blindbox`→`adventure`，其余→`balanced` |
| `budget` | number | 否 | 元；`null`/`0` 视为不限。硬约束 |
| `exclude` | string[] | 否 | 排除词，匹配名称/分类/标签 |
| `count` | int | 否 | 1–5，默认 3（盲盒默认 1） |
| `seed` | int | 否 | 不传则随机生成，并回显在结果里便于复现 |
| `menu` | object | 二选一 | `query-meals` 原始返回，或 `{"items":[...]}` 精简结构 |
| `menu_file` | string | 二选一 | 菜单 JSON 路径（相对当前工作目录） |
| `coupons` / `coupons_file` | object / string | 否 | `query-store-coupons` 原始返回 |
| `profile` | object | 否 | 内联档案；缺省读 `--profile` 指向的文件 |
| `recent` / `recent_categories` | string[] | 否 | 覆盖档案里的推荐历史（“再来一个”时传上一次结果） |
| `rejected` | string[] | 否 | 本轮用户明确拒绝的餐品编码 |
| `store` | object | 省钱模式建议 | `code`、`name`、`order_type`、`be_type`、`be_code` |

`menu` 同时支持两种形态，因此既能直接粘贴原始返回，也能用精简结构做轻量调用。

### 输出要点

- `candidates[]`：`code`、`name`、`price`、`score`、`lines`（可直接展示的四行说明）
- `detail[]`：完整四分项、理由、数据缺口
- `meta`：`menu_total`、`kept`、`dropped[]`（含丢弃原因）、`history_reliable`、
  `coupon_status`、`warnings`
- `combos[]` / `pricing_requests[]`：仅 `save` 模式
- `seed`：本次使用的随机种子

## 2. rerank

```bash
python3 scripts/mcfate.py rerank --input quotes.json
```

```json
{
  "budget": 35,
  "entries": [
    {"label": "方案A", "items": [{"code": "521952", "quantity": 1}], "quote": { /* calculate-price 原始返回 */ }}
  ]
}
```

排序权重：`priced`（按应付金额升序）→ `over_budget`（按超支金额升序）→ `unverified`。
`recommended` 只会在 `priced` 里产生；全部不可核价时为 `null`。

## 3. coupon-plan

```bash
python3 scripts/mcfate.py coupon-plan --input payload.json
```

入参：`menu`/`menu_file`、`coupons`/`coupons_file`、`items[]`、`subtotal?`、`budget?`。
输出每张券的 `status`（`usable`/`needs_extra`/`not_applicable`/`unverified`）、
`extra_needed`、以及可执行组合 `combos[]`。

## 4. 打分

```
score = w_novelty·novelty + w_preference·preference + w_diversity·diversity + w_mission_fit·mission_fit
```

| 风格 | novelty | preference | diversity | mission_fit |
|---|---|---|---|---|
| steady | 0.20 | 0.35 | 0.20 | 0.25 |
| balanced | 0.40 | 0.25 | 0.20 | 0.15 |
| adventure | 0.50 | 0.15 | 0.15 | 0.20 |
| frugal | 0.15 | 0.20 | 0.15 | 0.50 |

权重在 `scripts/mcfate_core/config.py`，可改，但四项之和必须为 1（构造时校验）。

### novelty

| 条件 | 分值 |
|---|---|
| 无可靠历史 | 0.50（中性） |
| 标记为不喜欢 | 0.05 |
| 已尝试 | 0.20 |
| 已标记喜欢 | 0.30 |
| 未尝试、但同品类试过 | 0.65 |
| 未尝试、品类也没记录 | 1.00 |

### preference
基准 0.50；喜欢 +0.45，不喜欢 −0.55；`like_tags` 命中每项 +0.08（上限 +0.24）；
`avoid_tags` 命中每项 −0.30（上限 −0.40）；`taste` 命中每项 +0.10（上限 +0.20）。结果裁剪到 0–1。

### diversity
无历史 0.60；与上次相同 0.00；最近 3 条内 0.10；更早推荐过 0.30；
与上次同品类 0.45；其余 1.00。

### mission_fit
- `steady`：0.45 起，非上新/限定 +0.30，已记录过 +0.15，可随单购 +0.05。
- `adventure`：未尝试且品类空白 1.00；未尝试的新品 0.90；未尝试 0.80；已尝试 0.40。
- `frugal`：0.40 + 0.60×min(折扣深度/0.5, 1)；有券覆盖 +0.15。
- `balanced`：0.60 起，有可靠历史且未尝试 +0.10，折扣深度 ≥15% +0.15，有券覆盖 +0.10。

### 抽取
候选按分数降序进入大小为 8 的池（`RANDOM_POOL_SIZE`），用 `softmax(score / 0.08)`
作权重做无放回加权抽样。分数越高越容易被抽中，但不会固定选中，因此“再来一个”能换出结果。
被拒绝的餐品在候选充足时剔除；候选不足才回退，绝不复制餐品凑数。

### 主餐优先
`classify_role` 把餐品粗分为 `main` / `side` / `drink`（依据分类名与名称关键词）。
主餐数量足够时，`prioritize_main` 只保留主餐，避免“今天吃什么”的答案是可乐加薯条；
主餐不足时才回退到全部候选。打分里另有轻量修正：主餐 +0.08，小食 −0.15，饮品 −0.20
（精算派减半），并在理由中说明“属于小食/饮品，更适合做搭配”。

## 5. 券判定

| 状态 | 条件 | 话术要求 |
|---|---|---|
| `not_applicable` | 券的适用餐品与所选无交集 | 直说不适用，不展示节省 |
| `needs_extra` | 门槛已知且未达到 | 明确“还差 ¥X，需加购” |
| `usable` | 适用餐品匹配，且门槛已知已满足或无门槛记录 | 仍要加一句“以官方算价为准” |
| `unverified` | 缺少适用范围/门槛等必要字段 | 明说无法判断，不计入节省 |

### 节省归属
`attribute_savings(with_quote, without_quote)` 要求：两次算价都成功、且商品清单一致，
才把 `应付差额` 记为该券的节省。任一条件不满足就返回“未验证”。

### 凑门槛成本
`suggest_combos` 从券的适用餐品里挑最便宜的打底，不足门槛时按价格升序加购；
加购不会突破预算上限（预算存在时）。若预算内无法凑到门槛，明确提示“需自行判断是否值得加购”，
不得把券面额当成净收益。

## 6. 退出码

| 码 | 含义 |
|---|---|
| 0 | 正常 |
| 2 | 入参错误（payload 无法解析、菜单为空、未知风格） |

## 7. 测试

```bash
cd scripts && python3 -m unittest discover -s tests -t .
```

覆盖：默认推荐、预算过滤、拒绝后不重复、无历史不臆测、无券降级、门槛未验证、
加购权衡、算价失败不伪造价格、候选不足、随机复现、无下单能力、结果幂等、敏感字段扫描。
