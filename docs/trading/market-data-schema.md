# 行情数据 Schema

## 执行层需要的字段

所有进入 `TradingEngine` 的价格数据都会被校验并转换成统一 schema：

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `symbol` | 是 | 交易侧统一使用纯代码，例如 `600519` |
| `date` | 是 | 交易日期，转换为 pandas datetime |
| `open` | 是 | 开盘价 |
| `high` | 是 | 最高价 |
| `low` | 是 | 最低价 |
| `close` | 是 | 收盘价 |
| `volume` | 否 | 成交量 |
| `amount` | 否 | 成交额 |
| `price` | 否 | 当前价格；缺失时默认等于 `close` |

`TradingEngine.get_price_data()` 会在边界再次调用 schema adapter。即使用户替换了 provider，只要返回字段不符合 schema，就会在进入执行层前直接报错。

## 数据源字段转换

转换发生在 `jh_quant.trading.market_data.adapters.to_trading_price_frame()`。

常见字段映射：

| 来源字段 | trading 字段 |
| --- | --- |
| `ts_code` | `symbol` |
| `trade_date` | `date` |
| `vol` | `volume` |
| `change` | `chg` |
| `dt` / `datetime` | `date` |
| `latest` / `last_price` | `close` |

TuShare 的 `600519.SH` 会在 trading schema 中规范为 `600519`。请求 TuShare 数据时，provider 会根据纯代码自动补 `.SH`、`.SZ` 或 `.BJ`。

## Provider 边界

允许依赖具体数据源的地方：

- `TuShareHistoricalBarProvider`
- `AkShareHistoricalBarProvider`
- `AkShareRealtimeQuoteProvider`
- `XtQuantRealtimeQuoteProvider`
- 与数据查询直接相关的 loader 或 service API

不应该依赖具体数据源字段的地方：

- `TradingEngine`
- 策略信号聚合
- 仓位计算
- 风控规则
- portfolio runtime
- session cycle

这保证了替换 provider 时，只需要保证 provider 输出能被 adapter 转成 trading schema，执行层逻辑不需要跟着改。
