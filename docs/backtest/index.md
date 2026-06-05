# jh_quant.backtest

`jh_quant.backtest` 是策略回测模块，支持多策略并行回测、风险规则、交易费用、绩效指标和可视化 Dashboard。

## 数据约定

backtest 核心逻辑不依赖具体数据源。推荐优先使用 TuShare 前复权日线：

```python
stock_price = jhd.get_data(
    DataTypes.TS_DAILY_QFQ,
    ts_code="600519.SH,000001.SZ",
    start="2024-01-01",
    end="2026-03-11",
)
stock_price = to_backtest_price_frame(stock_price)
```

进入 `backtest()` 前，数据应符合统一 schema：

```text
symbol, date, open, high, low, close, volume
```

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [快速开始](./quickstart.md) | 使用 TuShare 数据完成一次基础回测 |
| [策略详解](./strategies.md) | 内置策略参数、逻辑和自定义策略 |
| [风险管理规则](./risk-rules.md) | 止损、止盈、移动止损、ATR 止损、持仓限制 |
| [指标说明](./metrics.md) | 回测绩效指标和 FactorSelector 说明 |
