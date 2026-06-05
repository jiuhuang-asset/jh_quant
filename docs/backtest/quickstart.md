# 快速开始

`jh_quant.backtest` 的核心逻辑不关心数据来源。进入 `backtest()` 前，价格数据需要先转换为统一 schema：

```text
symbol, date, open, high, low, close, volume
```

推荐优先使用 TuShare 前复权日线数据 `DataTypes.TS_DAILY_QFQ`，再通过 `to_backtest_price_frame()` 转换。

## 导入

```python
from jh_quant.data import JHData, DataTypes, to_backtest_price_frame
from jh_quant.backtest import (
    backtest,
    StrategyTurtle,
    StrategyVolumeTrend,
    StrategyBuyAndHold,
)
from jh_quant.dashboard import display_backtesting
```

## 基本流程

三步完成一次回测：

1. 准备 TuShare 行情数据。
2. 定义策略。
3. 调用 `backtest()`。

## 1. 准备数据

TuShare 股票代码需要带交易所后缀，例如 `.SH`、`.SZ`、`.BJ`。

```python
jhd = JHData()

symbols = [
    "600135.SH",
    "000001.SZ",
    "600036.SH",
    "600519.SH",
    "000858.SZ",
    "601318.SH",
    "000002.SZ",
    "600030.SH",
    "600887.SH",
    "000333.SZ",
    "002415.SZ",
]

stock_price = jhd.get_data(
    DataTypes.TS_DAILY_QFQ,
    ts_code=",".join(symbols),
    start="2024-12-25",
    end="2026-03-11",
)
stock_price = to_backtest_price_frame(stock_price)
```

`to_backtest_price_frame()` 会把 TuShare 字段转换成回测 schema，例如：

| TuShare 字段 | 回测字段 |
| --- | --- |
| `ts_code` | `symbol` |
| `trade_date` | `date` |
| `vol` | `volume` |

## 2. 定义策略

策略以字典形式传入，key 是展示名称，value 是策略实例：

```python
strategies = {
    "海龟": StrategyTurtle(),
    "放量趋势": StrategyVolumeTrend(),
    "买入持有": StrategyBuyAndHold(),
}
```

更多内置策略见 [策略详解](./strategies.md)。

## 3. 执行回测

```python
trading_history, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
)
```

## 完整示例

```python
from jh_quant.data import JHData, DataTypes, to_backtest_price_frame
from jh_quant.backtest import (
    backtest,
    StrategyTurtle,
    StrategyVolumeTrend,
    StrategyBuyAndHold,
)
from jh_quant.dashboard import display_backtesting


def main():
    jhd = JHData()
    symbols = [
        "600135.SH",
        "000001.SZ",
        "600036.SH",
        "600519.SH",
        "000858.SZ",
        "601318.SH",
        "000002.SZ",
        "600030.SH",
        "600887.SH",
        "000333.SZ",
        "002415.SZ",
    ]

    stock_price = jhd.get_data(
        DataTypes.TS_DAILY_QFQ,
        ts_code=",".join(symbols),
        start="2024-12-25",
        end="2026-03-11",
    )
    stock_price = to_backtest_price_frame(stock_price)

    strategies = {
        "海龟": StrategyTurtle(),
        "放量趋势": StrategyVolumeTrend(),
        "买入持有": StrategyBuyAndHold(),
    }

    trading_history, backtest_perf = backtest(
        strategies=strategies,
        price_data=stock_price,
    )

    display_backtesting(trading_history, backtest_perf)


if __name__ == "__main__":
    main()
```

## 费用设置

```python
trading_history, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
    commission_rate=0.0003,
    stamp_tax_rate=0.001,
)
```

## 信号应用时点

`use_next_day_return=True` 是默认值，表示当日信号在次日收益上体现，避免使用未来信息：

```python
trading_history, _ = backtest(
    strategies=strategies,
    price_data=stock_price,
    use_next_day_return=True,
)
```

如果你的信号已经在外部做了滞后处理，可以显式关闭：

```python
trading_history, _ = backtest(
    strategies=strategies,
    price_data=stock_price,
    use_next_day_return=False,
)
```

## 可视化

```python
from jh_quant.dashboard import display_backtesting

display_backtesting(trading_history, backtest_perf)
```

## 下一步

- 查看 [策略详解](./strategies.md)
- 查看 [风险管理规则](./risk-rules.md)
- 查看 [回测指标说明](./metrics.md)
