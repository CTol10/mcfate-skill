# MCP 工具实测契约

本文只记录**实际调用验证过**的字段与行为（2026-10-18，深圳某门店，到店自取）。
接口未返回的字段一律视为未知，代码与话术都不得补全。

## 通用约定

- 返回外壳：`{success, code, message, datetime, traceId, data}`，`code=200` 为成功。
- 金额单位不统一：
  - `query-meals` 的 `currentPrice` / `originalPrice` 是**元**（字符串，如 `"26.5"`）。
  - `calculate-price` 的所有金额字段是**分**（整数，如 `2650`）。
- `orderType`：`1` 到店（自取 + 得来速），`2` 外送（麦乐送 + 团餐）。
- `beType`：`1` 到店自取，`2` 麦乐送，`5` 得来速，`6` 企业团餐。
- `beCode` 传递矩阵：

| 场景 | orderType | beType | beCode |
|---|---|---|---|
| 到店自取 | 1 | 1 | 不传（传了会报错） |
| 得来速 | 1 | 5 | 必传，来自 `query-nearby-stores` |
| 麦乐送 | 2 | 2 | 必传，来自 `delivery-query-stores` |
| 企业团餐 | 2 | 6 | 必传，来自 `delivery-query-stores` |

## 门店

### query-nearby-stores
- 入参：`searchType`（1 收藏 / 2 按位置）、`beType`(1|5)；`searchType=2` 时 `city`、`keyword` 必填。
- 返回 `data[]`：`storeCode`、`storeName`、`address`、`distance`、`businessStatus`、
  `businessStartTime`、`businessEndTime`、`reservation`、`reservationTimeOptions[]`。
- 要点：`beType=1` 不返回 `beCode`；`beType=5` 返回 `beCode`，后续所有工具都要带上。

### delivery-query-stores
- 入参：`addressId`（先调 `delivery-query-addresses`）、`beType`(2|6)。
- 返回外送可用门店及其 `beCode`。

## 菜单

### query-meals
- 入参：`storeCode`、`orderType`、`beType`、`beCode?`、`reservationDate?`。
- 返回结构（实测）：

```
data.categories[]            # 分类导航，含营销位
  .name                      # 分类名，可能含换行，如 "巨无霸\n牛鱼肉堡"
  .meals[].code              # 餐品编码
  .meals[].tags[]            # 标签（"上新"、"单品"、"套餐"…）
data.meals{code}             # 详情映射表，权威数据源
  .name .image
  .currentPrice              # 现价（元，字符串）
  .originalPrice             # 划线价（元）
  .discountType              # 促销/麦金卡/随单购…，可能缺省
  .canWithOrder .withOrder   # 随单购信息
data.frequent{code,tags}     # 我的常点（可能缺失）
```

- 关键坑：同一餐品会出现在多个分类里（含“人气热卖”“精选单人餐”这类营销位）。
  本项目取**非营销位分类**作为口味品类，见 `config.MARKETING_BUCKETS`。
- 用途：候选池的**唯一**来源。没有菜单就不出推荐。

### query-meal-detail
- 入参：`storeCode`、`orderType`、`beType`、`code`、`beCode?`、`reservationDate?`。
- 返回餐品组成与 `modification`（特调）信息、`supportModify`。
- 本 Skill 只在用户问“这个套餐里有什么/能换吗”时调用；不主动展开特调列表。

### list-nutrition-foods
- 无入参，返回常见餐品营养数据。仅在用户主动问热量/营养时使用，不参与主推荐排序。

## 优惠券

### query-store-coupons（首选）
- 入参：`storeCode`、`orderType`、`beType`、`beCode?`、`reservationDate?`。
- 返回 `data[]`：`title`、`couponId`、`couponCode`、`tradeDateTime`、`products[]{productName, productCode}`。
- 实测：门店无可用券时返回 `data: []`，属正常空状态。
- **门槛字段不保证存在**。代码对 `threshold` / `minAmount` / `minSpend` 等做可选解析，
  缺失即 `None`，判定为“未验证”，不得假设无门槛。

### query-my-coupons
- 入参：`page`、`pageSize`（字符串，最大 200）。
- 实测：无券时返回**自然语言文本**（“暂无可用优惠券”），不是 JSON 数组。
- 处理：`normalize_coupons` 遇到字符串直接判 `unparsed`，不得据此判断“没有券”，
  也不得把它当结构化券用。判断门店可用券一律用 `query-store-coupons`。

### available-coupons
- 无入参，查可领取的麦麦省券。
- 实测：调用返回 MCP 错误
  `Structured content does not match the tool's output schema: data/data must be array`。
- 处理：**降级跳过**，不重试、不伪造券列表，话术里说明“领取入口暂时不可用”。

### auto-bind-coupons / query-survey-coupon
- 具备副作用（领券/绑券）或依赖问卷状态。MVP 不调用；“看看有什么券”不等于授权绑券。

### query-promotions
- 仅企业团餐（`beType=6`、`orderType=2`、`beCode` 必填）。
- 返回 `promotionType`(31 满额减 / 33 订单折扣)、`ruleCategory`(30 折扣 / 40 满减)、
  `products`(type=1 包含 / 2 不包含 / 3 全部)、`ruleDetail`。
- 工具不做最优推荐，只给规则原文；解读由本 Skill 的券判定层完成，且必须标注为“规则推算”。

## 算价

### calculate-price
- 入参：`storeCode`、`orderType`、`beType`、`beCode?`、`items[]`、`withOrder?`、`needTableware?`、`reservationDate?`。
- `items[]`：`productCode`、`quantity`（≥1）、`couponId?`、`couponCode?`、`modification?`、`roundList?`（套餐）。
- 返回（单位为分）：

| 字段 | 含义 |
|---|---|
| `data.price` | 应付现价 |
| `data.originalPrice` | 原价 |
| `data.discount` | 官方优惠总额（**不等于**某张券的贡献） |
| `data.productPrice` / `productOriginalPrice` | 商品部分金额 |
| `data.deliveryPrice` / `packingPrice` / `tablewarePrice` | 运费 / 打包费 / 餐具费 |
| `data.productList[]` | `productCode`、`productName`、`quantity`、`subtotal` |
| `data.takeWayList[]` | `code`（下单时的取餐方式）、`title`、`subtitle` |
| `data.enjoyed` / `data.enjoyable` | 已享受 / 可享受优惠，含 `amountType`、`realDiscount`、`balance`（门槛差额，分） |

- 注意：`calculate-price` **没有** `takeWayCode` 参数。取餐方式来自返回的 `takeWayList`，
  只有 `create-order` 才需要 `takeWayCode`。
- 本 Skill 只调用它做核价，不调用 `create-order`。

## 其他（本版不参与主流程）

`query-my-account`（积分）、`mall-points-products` / `mall-product-detail` / `mall-*`
（积分商城，兑换属副作用）、`query-party-*` / `party-order-create`（派对预订，副作用）、
`draw-lottery`（抽奖，副作用）、`campaign-calendar`（活动日历）、`now-time-info`（当前时间）。
其中 `now-time-info` 可在需要判断“今天/营业时段”时用于取时间，但不参与推荐打分。
