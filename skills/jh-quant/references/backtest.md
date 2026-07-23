# 策略回测模块 (backtest)

## 快速开始

```python
from jh_quant.data import JHData, DataTypes, to_backtest_price_frame
from jh_quant.backtest import backtest, StrategyTurtle, StrategyBuyAndHold
from jh_quant.dashboard import display_backtesting

# 1. 准备数据
jh = JHData()
stock_price = jh.get_data(
    DataTypes.TS_DAILY_QFQ,
    ts_code="000001.SZ,600519.SH,300750.SZ",
    start="2025-01-01",
    end="2026-05-07",
)
stock_price = to_backtest_price_frame(stock_price)

# 2. 定义策略
strategies = {
    "海龟策略": StrategyTurtle(entry_window=20, exit_window=10),
    "买入持有": StrategyBuyAndHold(),
}

# 3. 执行回测
trading_hist, backtest_perf = backtest(strategies=strategies, price_data=stock_price)

# 4. 可视化
display_backtesting(trading_hist, backtest_perf)
```

## 数据格式

回测前数据必须通过 `to_backtest_price_frame()` 转换为统一 schema：

```
symbol, date, open, high, low, close, volume
```

| TuShare 原始字段 | 回测字段 |
|---|---|
| `ts_code` | `symbol` |
| `trade_date` | `date` |
| `vol` | `volume` |

## 回测参数

```python
trading_hist, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
    commission_rate=0.0003,        # 佣金费率（默认 0.03%）
    stamp_tax_rate=0.001,          # 印花税率（默认 0.1%）
    use_next_day_return=True,      # 今日信号→次日收益（避免未来信息）
)
```

- `use_next_day_return=True`（默认）：当日信号在次日收益上体现
- 如果你的信号已在外部做了滞后处理，可设为 `False`

## 11 种内置策略

所有策略继承自 `Strategy` 基类，统一通过 `_execute_one(symbol, df)` 方法生成 `buy_signal` 和 `sell_signal` 列（值为 0 或 1）。

### 策略总览

| 策略类 | 核心逻辑 | 关键参数 | 适用场景 |
|--------|---------|---------|---------|
| `StrategyBuyAndHold` | 全程持仓 | 无 | 基准对比 |
| `StrategyMovingAverageCrossover` | 短期均线上穿/下穿长期均线 | `short_window=12`, `long_window=24` | 趋势跟踪 |
| `StrategyTurtle` | Donchian 通道突破 | `entry_window=20`, `exit_window=10` | 趋势跟踪 |
| `StrategyRSI` | 超买超卖反转 | `rsi_window=14`, `oversold_threshold=30`, `overbought_threshold=70` | 均值回归 |
| `StrategyBollingerBands` | 价格触及/突破上下轨 | `window=20`, `num_std=2.0`, `use_mean_reversion=True` | 均值回归/突破 |
| `StrategyMomentum` | 价格动量趋势 | `momentum_window=20`, `momentum_threshold=0.05`, `ma_window=60` | 趋势跟踪 |
| `StrategyMeanReversion` | 价格偏离均线回归 | `ma_window=20`, `deviation_threshold=0.02`, RSI 辅助 | 均值回归 |
| `StrategyBreakout` | N 日高点突破 + ATR 止损 | `lookback_period=20`, `atr_multiplier=2.0` | 趋势跟踪 |
| `StrategyDualThrust` | 前 N 日区间上下轨突破 | `k1=0.7`, `k2=0.7`, `lookback_period=20` | 日内/短线 |
| `StrategyVolumeTrend` | 量价配合趋势确认 | `ma_window=20`, `volume_window=20` | 量价分析 |
| `StrategyVolumeDivergence` | 价格与成交量背离 | `rsi_window=14`, `volume_window=20` | 反转信号 |

### 各策略用法示例

```python
# 均线交叉
StrategyMovingAverageCrossover(short_window=12, long_window=24)

# 海龟交易
StrategyTurtle(entry_window=20, exit_window=10)

# RSI
StrategyRSI(rsi_window=14, oversold_threshold=30, overbought_threshold=70)

# 布林带
StrategyBollingerBands(window=20, num_std=2.0, use_mean_reversion=True)

# 动量
StrategyMomentum(momentum_window=20, momentum_threshold=0.05, ma_window=60)

# 均值回归
StrategyMeanReversion(ma_window=20, deviation_threshold=0.02)

# 突破
StrategyBreakout(lookback_period=20, atr_multiplier=2.0, use_atr_stop=True)

# Dual Thrust
StrategyDualThrust(k1=0.7, k2=0.7, lookback_period=20)

# 成交量趋势
StrategyVolumeTrend(ma_window=20, volume_window=20)

# 成交量背离
StrategyVolumeDivergence(rsi_window=14, volume_window=20)
```

## 自定义策略

**不要修改 `jh_quant/backtest/strategy.py`。** 在项目根目录创建独立的 `.py` 文件，继承 `Strategy` 基类即可：

```python
# my_strategy.py（新建的独立文件）
from jh_quant.backtest import Strategy
import pandas as pd

class MyStrategy(Strategy):
    def __init__(self, ma_window=20):
        super().__init__()
        self.ma_window = ma_window

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        data['ma'] = data['close'].rolling(self.ma_window).mean()

        data['buy_signal'] = (
            (data['close'] > data['ma']) &
            (data['close'].shift(1) <= data['ma'].shift(1))
        ).astype(int)

        data['sell_signal'] = (
            (data['close'] < data['ma']) &
            (data['close'].shift(1) >= data['ma'].shift(1))
        ).astype(int)

        return data
```

然后在测试脚本中导入：
```python
from my_strategy import MyStrategy

strategies = {
    "我的策略": MyStrategy(ma_window=20),
}
```

**注意事项**：
- `_execute_one` 接收的 `data` 已按日期排序，只包含单只股票（基类用 joblib 自动并行）
- `buy_signal` 和 `sell_signal` 必须是整数 0 或 1
- 同一交易日可以同时产生买入和卖出信号（框架以最后信号为准）
- **不要在 `__init__` 中执行耗时操作**，策略实例会被 pickle 序列化以支持并行
