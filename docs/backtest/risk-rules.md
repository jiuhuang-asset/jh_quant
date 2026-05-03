# 风险管理规则

风控规则用于在策略信号的基础上叠加风险控制逻辑，实现止损、止盈、持仓限制等。规则可以全局应用，也可以按策略分别绑定。

## 基本用法

```python
from jh_quant.backtest import backtest
from jh_quant.backtest import (
    StrategyTurtle,
    StopLossRule,
    TakeProfitRule,
    TrailingStopRule,
)

# 方式一：全局规则（所有策略共用）
trading_history, perf = backtest(
    strategies={"海龟": StrategyTurtle()},
    price_data=stock_price,
    rules=[StopLossRule(0.05), TakeProfitRule(0.10)],
)

# 方式二：按策略绑定不同规则
trading_history, perf = backtest(
    strategies={"海龟": StrategyTurtle()},
    price_data=stock_price,
    rules={
        "海龟": [StopLossRule(0.05), TrailingStopRule(0.03)],
    },
)

# 方式三：混合使用（None 的策略使用全局规则）
trading_history, perf = backtest(
    strategies={
        "海龟": StrategyTurtle(entry_window=20),
        "激进海龟": StrategyTurtle(entry_window=10),
    },
    price_data=stock_price,
    rules={
        "海龟": [StopLossRule(0.05)],
        # "激进海龟" 不指定 → 无风控
    },
)
```

## PositionState

每只股票在每个交易日维护一个 `PositionState`，记录当前持仓的运行状态：

| 字段 | 类型 | 说明 |
|------|------|------|
| `in_position` | bool | 是否处于持仓状态 |
| `entry_price` | float | 入场价格 |
| `highest_price` | float | 持仓期间最高价（用于移动止损） |
| `holding_bars` | int | 已持仓 K 线数（交易日数） |
| `consecutive_up` | int | 连续上涨 K 线数 |
| `consecutive_down` | int | 连续下跌 K 线数 |

状态在以下时机更新：

1. **买入信号触发** → 重置 `PositionState`，设置 `in_position=True`，记录 `entry_price`
2. **每个持仓日** → 更新 `highest_price`、`holding_bars`、`consecutive_up/down`
3. **卖出信号或风控触发** → `in_position=False`，清空状态

## 规则总览

| 规则 | 触发条件 | 关键参数 |
|------|---------|---------|
| [StopLossRule](#stoplossrule) | 亏损超过固定比例 | `pct` |
| [TakeProfitRule](#takeprofitrule) | 盈利超过固定比例 | `pct` |
| [TrailingStopRule](#trailingstoprule) | 从最高点回撤超过比例 | `pct` |
| [ATRTrailingStopRule](#atrtrailingstoprule) | 从最高点回撤超过 ATR 倍数 | `multiplier`, `window` |
| [MaxHoldingBarsRule](#maxholdingbarsrule) | 持仓 K 线数超过限制 | `bars` |
| [MaxConsecutiveRisingBarsRule](#maxconsecutiverisingbarsrule) | 连续上涨超过限制 | `bars` |
| [MaxConsecutiveFallingBarsRule](#maxconsecutivefallingbarsrule) | 连续下跌超过限制 | `bars` |

## StopLossRule

固定比例止损。当持仓亏损超过指定比例时强制卖出。

```python
from jh_quant.backtest import StopLossRule

rule = StopLossRule(pct=0.05)  # 亏损 5% 止损
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pct` | float | 0.05 | 亏损比例阈值（正数，如 0.05 = 5%） |

**触发逻辑**：`(current_price - entry_price) / entry_price <= -pct`

止损是最后一道防线 —— 即使策略没有卖出信号，止损也会强制平仓。

## TakeProfitRule

固定比例止盈。当持仓盈利达到指定比例时强制卖出。

```python
from jh_quant.backtest import TakeProfitRule

rule = TakeProfitRule(pct=0.10)  # 盈利 10% 止盈
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pct` | float | 0.10 | 盈利比例阈值（正数） |

**触发逻辑**：`(current_price - entry_price) / entry_price >= pct`

## TrailingStopRule

移动止损（回撤止盈）。从持仓期间的最高点回撤超过指定比例时卖出。

```python
from jh_quant.backtest import TrailingStopRule

rule = TrailingStopRule(pct=0.03)  # 从最高点回撤 3% 止损
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pct` | float | 0.03 | 回撤比例阈值（正数） |

**触发逻辑**：`(highest_price - current_price) / highest_price >= pct`

与 StopLossRule 的区别：StopLossRule 基于入场价，TrailingStopRule 基于持仓期间最高价。后者允许利润奔跑，只在趋势反转时离场。

## ATRTrailingStopRule

基于 ATR（平均真实波幅）的移动止损。比固定比例止损更适应市场波动率。

```python
from jh_quant.backtest import ATRTrailingStopRule

rule = ATRTrailingStopRule(
    multiplier=2.0,   # ATR 倍数
    window=14,         # ATR 计算窗口
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `multiplier` | float | 2.0 | ATR 倍数（止损距离 = multiplier × ATR） |
| `window` | int | 14 | 计算 ATR 的窗口 |

**触发逻辑**：`current_price <= highest_price - multiplier * ATR`

框架会在回测开始时预计算所有股票的 ATR 值，避免重复计算。

## MaxHoldingBarsRule

最大持仓 K 线数限制。持仓超过指定交易日数后强制卖出。

```python
from jh_quant.backtest import MaxHoldingBarsRule

rule = MaxHoldingBarsRule(bars=20)  # 最多持有 20 个交易日
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bars` | int | 20 | 最大持仓交易日数 |

适合短线策略，避免持仓时间过长。

## MaxConsecutiveRisingBarsRule

最大连续上涨 K 线数限制。连续上涨超过指定天数后强制止盈。

```python
from jh_quant.backtest import MaxConsecutiveRisingBarsRule

rule = MaxConsecutiveRisingBarsRule(bars=5)  # 连涨 5 天后卖出
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bars` | int | 5 | 最大连续上涨 K 线数 |

捕捉短期超买反转机会。

## MaxConsecutiveFallingBarsRule

最大连续下跌 K 线数限制。连续下跌超过指定天数后强制止损。

```python
from jh_quant.backtest import MaxConsecutiveFallingBarsRule

rule = MaxConsecutiveFallingBarsRule(bars=5)  # 连跌 5 天后卖出
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bars` | int | 5 | 最大连续下跌 K 线数 |

避免在持续下跌中继续持仓。

## 规则执行顺序

当绑定多个规则时，按列表顺序依次检查。任一规则触发卖出，后续规则不再执行：

```python
rules = [
    StopLossRule(0.05),          # 1. 先检查止损
    TrailingStopRule(0.03),      # 2. 再检查移动止损
    MaxHoldingBarsRule(20),      # 3. 最后检查持仓时间
]
```

建义将止损类规则放在最前面，确保风险控制优先执行。

## 自定义规则

继承 `RiskRule` 基类，实现相关钩子方法：

```python
from jh_quant.backtest import RiskRule, PositionState
import pandas as pd

class GapDownStopRule(RiskRule):
    """跳空低开止损：开盘价低于前日收盘价超过阈值则止损"""

    def __init__(self, pct=0.03):
        self.pct = pct

    def on_tick(self, i: int, df: pd.DataFrame, state: PositionState) -> bool:
        """每个持仓日调用，返回 True 表示触发卖出"""
        if i == 0 or not state.in_position:
            return False
        gap = (df.iloc[i]['open'] - df.iloc[i-1]['close']) / df.iloc[i-1]['close']
        return gap <= -self.pct
```

| 钩子方法 | 调用时机 | 返回值 |
|---------|---------|--------|
| `on_enter(i, df, state)` | 买入信号触发后、进入持仓前 | `True` 阻止入场 |
| `on_tick(i, df, state)` | 每个持仓交易日 | `True` 触发卖出 |
| `should_sell(i, df, state)` | 卖出信号评估时 | `True` 确认卖出 |

`i` 为当前行在 `df` 中的索引，`df` 为单只股票的完整价格数据。
