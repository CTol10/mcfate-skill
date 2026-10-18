# 示例

| 文件 | 用途 |
|---|---|
| `sample-menu.json` | 精简菜单快照（13 款，价格取自官方菜单实际返回，门店编码为占位符） |
| `sample-coupons.json` | 示例券结构（券 ID/券码虚构，仅用于演示解析与门槛逻辑） |
| `sample-payload.json` | 模式 A：替我决定，预算 35、排除咖啡 → `turn=board` |
| `blindbox-payload.json` | 模式 C：命运盲盒，冒险派、预算 35、排除汉堡 → `turn=reveal` |
| `save-payload.json` | 模式 B：麦运省钱，预算 50、带券 |
| `quotes-payload.json` | 算价重排：可成交 / 原价 / 算价失败三种状态 |
| `out-decide.json` | 模式 A 的实际输出（摆盘回合） |
| `out-blindbox.json` | 模式 C 的实际输出（揭晓回合，含签号与仪式句） |
| `out-save.json` | 模式 B 的实际输出（含 `combos` 与 `pricing_requests`） |
| `out-rerank.json` | 重排结果（含 `unverified` 降级示例） |

## 运行

```bash
cd mcfate

# 模式 A：摆盘，一屏三个候选
python3 scripts/mcfate.py recommend --input examples/sample-payload.json

# 模式 C：揭晓，一次只出一支签
python3 scripts/mcfate.py recommend --input examples/blindbox-payload.json

# 模式 B
python3 scripts/mcfate.py recommend --input examples/save-payload.json

# 拿 pricing_requests 调用 calculate-price 后，把原始返回填入 entries 再重排
python3 scripts/mcfate.py rerank --input examples/quotes-payload.json
```

`sample-payload.json` 里 `menu_file` 使用的是相对**当前工作目录**的路径，
因此请在 `mcfate/` 目录下执行，或把它改成绝对路径。

## 看输出里的这两个字段

- `turn`：`board`（摆盘）或 `reveal`（揭晓）。它决定这一轮该给用户看什么结构。
- `meta.stop_after_turn`：恒为 `true`。本轮输出后必须停，等用户选动作。

`blindbox-payload.json` 固定 `seed`，因此每次运行得到的签号与餐品完全一致
（示例为第 427 签 · 大堡口福三件套）。改 `seed` 才能换签，这是可复现抽签的前提。
