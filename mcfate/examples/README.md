# 示例

| 文件 | 用途 |
|---|---|
| `sample-menu.json` | 精简菜单快照（13 款，价格取自官方菜单实际返回，门店编码为占位符） |
| `sample-coupons.json` | 示例券结构（券 ID/券码虚构，仅用于演示解析与门槛逻辑） |
| `sample-payload.json` | 模式 A：替我决定，预算 35、排除咖啡 |
| `save-payload.json` | 模式 B：麦运省钱，预算 50、带券 |
| `quotes-payload.json` | 算价重排：可成交 / 原价 / 算价失败三种状态 |
| `out-decide.json` | 模式 A 的实际输出 |
| `out-save.json` | 模式 B 的实际输出（含 `combos` 与 `pricing_requests`） |
| `out-rerank.json` | 重排结果（含 `unverified` 降级示例） |

## 运行

```bash
cd mcfate

# 模式 A
python3 scripts/mcfate.py recommend --input examples/sample-payload.json

# 模式 B
python3 scripts/mcfate.py recommend --input examples/save-payload.json

# 拿 pricing_requests 调用 calculate-price 后，把原始返回填入 entries 再重排
python3 scripts/mcfate.py rerank --input examples/quotes-payload.json
```

`sample-payload.json` 里 `menu_file` 使用的是相对**当前工作目录**的路径，
因此请在 `mcfate/` 目录下执行，或把它改成绝对路径。
