# 快速开始

## 导入

```python
from jh_quant.backtest import backtest
from jh_quant.backtest import (
    StrategyTurtle,
    StrategyMovingAverageCrossover,
    StrategyBuyAndHold,
)
from jh_quant.data import JHData, DataTypes
```

## 基本回测流程

三步完成一个回测：准备数据 → 定义策略 → 执行回测。

### 1. 准备数据

回测需要两类数据：**价格数据**（必需）和**股票信息**（可选，用于展示股票名称和行业）。

```python
jh = JHData()

# 价格数据 — 必须包含 open, high, low, close, volume 列
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519,300750",   # 逗号分隔多只股票
    start="2024-01-01",
    end="2025-12-31",
)

# 股票信息 — 可选，用于回测结果中附加 name、industry
stock_info = jh.get_data(DataTypes.AK_STOCK_INDIVIDUAL_INFO_EM)
```

价格数据至少需要包含 `open`、`high`、`low`、`close`、`volume` 列。`volume` 为 0 时视为停牌。

### 2. 定义策略

策略以字典形式传入，key 为策略名称，value 为策略实例：

```python
strategies = {
    "海龟策略": StrategyTurtle(entry_window=20, exit_window=10),
    "均线交叉": StrategyMovingAverageCrossover(short_window=12, long_window=24),
    "买入持有": StrategyBuyAndHold(),
}
```

所有内置策略详见 [策略详解](./strategies.md)。

### 3. 执行回测

```python
trading_history, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
    stock_info=stock_info,
)
```

### 返回值

`backtest()` 返回一个元组 `(trading_history, backtest_perf)`：

**trading_history**（`JhDataType`，包装了 DataFrame）：

| 列 | 说明 |
|----|------|
| `symbol` | 股票代码 |
| `date` | 交易日期 |
| `open/high/low/close/volume` | 行情数据 |
| `buy_signal` / `sell_signal` | 策略信号 |
| `position` | 持仓状态（1=持仓, 0=空仓） |
| `strategy` | 策略名称 |
| `strategy_return` | 策略日收益率 |
| `cumulative_return` | 累计收益率 |
| `drawdown` | 当前回撤 |

**backtest_perf**（`pd.DataFrame`）：

| 列 | 说明 |
|----|------|
| `symbol` | 股票代码 |
| `strategy` | 策略名称 |
| `name` | 股票名称（若传入了 stock_info） |
| `industry` | 行业（若传入了 stock_info） |
| `累积收益率` | 整个回测期的累计收益 |
| `最大回撤` | 最大回撤幅度 |
| `胜率` | 盈利交易日占比 |
| `夏普比率` | 年化夏普比率 |
| `卡玛比率` | 年化收益 / 最大回撤 |
| ... | 更多指标 |

## 完整示例

```python
import warnings
warnings.filterwarnings("ignore")

from jh_quant.data import JHData, DataTypes
from jh_quant.backtest import (
    backtest,
    StrategyTurtle,
    StrategyMovingAverageCrossover,
    StrategyBuyAndHold,
    StrategyRSI,
    StrategyBollingerBands,
)

# 1. 数据
jh = JHData()
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600036,600519,000858,601318",
    start="2024-01-01",
    end="2025-12-31",
)
stock_info = jh.get_data(DataTypes.AK_STOCK_INDIVIDUAL_INFO_EM)

# 2. 策略
strategies = {
    "海龟": StrategyTurtle(entry_window=20, exit_window=10),
    "均线交叉": StrategyMovingAverageCrossover(12, 24),
    "买入持有": StrategyBuyAndHold(),
    "RSI": StrategyRSI(rsi_window=14),
    "布林带": StrategyBollingerBands(window=20, num_std=2.0),
}

# 3. 回测
trading_history, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
    stock_info=stock_info,
)

# 4. 查看结果
print(backtest_perf[["symbol", "strategy", "累积收益率", "夏普比率", "最大回撤"]])

# 按策略汇总
summary = backtest_perf.groupby("strategy")[["累积收益率", "夏普比率", "最大回撤"]].mean()
print(summary)
```

## 费率设置

```python
trading_history, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
    commission_rate=0.0003,   # 佣金费率（默认 0.0002 = 万二）
    stamp_tax_rate=0.001,      # 印花税率（默认 0.0005 = 万五，仅卖出收取）
)
```

## 信号模式

`use_next_day_return` 控制买卖信号的应用时机：

```python
# 默认 True：当日信号 → 次日持仓（避免未来信息）
trading_history, _ = backtest(strategies, stock_price, use_next_day_return=True)

# False：当日信号 → 当日持仓（用于已引入滞后的信号）
trading_history, _ = backtest(strategies, stock_price, use_next_day_return=False)
```

## 指标精度

`metric_decimal` 控制绩效指标的小数位数（默认 2 位）：

```python
trading_history, backtest_perf = backtest(strategies, stock_price, metric_decimal=4)
```

## 可视化

如果安装了 `jh_quant.dashboard` 模块，可以展示回测仪表盘：

```python
from jh_quant.dashboard import display_backtesting

display_backtesting(trading_history, backtest_perf)
```

## 下一步

- 了解 [11 种内置策略的详细参数](./strategies.md)
- 配置 [风险管理规则](./risk-rules.md)（止损、止盈等）
- 查看 [回测指标说明](./metrics.md)
