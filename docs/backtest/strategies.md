# 策略详解

框架内置 11 种经典策略，所有策略继承自 `Strategy` 基类，统一通过 `_execute_one(symbol, df)` 方法生成 `buy_signal` 和 `sell_signal` 列（值为 0 或 1）。

## 策略总览

| 策略 | 核心逻辑 | 关键参数 | 适用场景 |
|------|---------|---------|---------|
| [买入持有](#买入持有) | 全程持仓 | 无 | 基准对比 |
| [均线交叉](#均线交叉) | 短期均线上穿/下穿长期均线 | `short_window`, `long_window` | 趋势跟踪 |
| [海龟交易](#海龟交易) | Donchian 通道突破 | `entry_window`, `exit_window` | 趋势跟踪 |
| [RSI](#rsi) | 超买超卖反转 | `rsi_window`, `oversold_threshold`, `overbought_threshold` | 均值回归 |
| [布林带](#布林带) | 价格触及上下轨反转 | `window`, `num_std` | 均值回归/突破 |
| [动量](#动量) | 价格动量突破阈值 | `momentum_window`, `momentum_threshold` | 趋势跟踪 |
| [均值回归](#均值回归) | 价格偏离均线回归 | `ma_window`, `deviation_threshold` | 均值回归 |
| [突破](#突破) | 价格突破 N 日最高价 | `lookback_period`, `atr_multiplier` | 趋势跟踪 |
| [Dual Thrust](#dual-thrust) | 前 N 日价格区间上下轨突破 | `k1`, `k2`, `lookback_period` | 日内/短线 |
| [成交量趋势](#成交量趋势) | 量价配合趋势确认 | `ma_window`, `volume_window` | 量价分析 |
| [成交量背离](#成交量背离) | 价格与成交量背离 | `rsi_window`, `volume_window` | 反转信号 |

## 买入持有

最简单的基准策略：回测期首日买入，一直持有到期末。

```python
from jh_quant.backtest import StrategyBuyAndHold

strategy = StrategyBuyAndHold()
```

无参数。通常用作策略对比的基准 —— 如果主动策略跑不赢买入持有，说明策略无效。

## 均线交叉

短期均线上穿长期均线时买入，下穿时卖出。

```python
from jh_quant.backtest import StrategyMovingAverageCrossover

strategy = StrategyMovingAverageCrossover(
    short_window=12,   # 短期均线窗口
    long_window=24,    # 长期均线窗口
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `short_window` | int | 12 | 短期均线计算窗口 |
| `long_window` | int | 24 | 长期均线计算窗口 |

**买卖逻辑**：

- **买入**：短期均线从下方上穿长期均线（金叉），且当前无持仓
- **卖出**：短期均线从上方下穿长期均线（死叉），且当前有持仓

经典参数组合：5/20（短线）、12/24（中短线）、20/60（中长线）。

## 海龟交易

基于 Donchian 通道突破的经典趋势跟踪策略。

```python
from jh_quant.backtest import StrategyTurtle

strategy = StrategyTurtle(
    entry_window=20,   # 入场通道窗口
    exit_window=10,    # 离场通道窗口
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `entry_window` | int | 20 | 入场突破窗口（突破 N 日最高价买入） |
| `exit_window` | int | 10 | 离场突破窗口（跌破 N 日最低价卖出） |

**买卖逻辑**：

- **买入**：收盘价突破 `entry_window` 日最高价
- **卖出**：收盘价跌破 `exit_window` 日最低价

原始海龟法则中 `entry_window=20`、`exit_window=10`。

## RSI

基于相对强弱指标（RSI）的超买超卖反转策略。

```python
from jh_quant.backtest import StrategyRSI

strategy = StrategyRSI(
    rsi_window=14,              # RSI 计算窗口
    oversold_threshold=30,      # 超卖阈值（买入）
    overbought_threshold=70,    # 超买阈值（卖出）
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rsi_window` | int | 14 | RSI 计算周期 |
| `oversold_threshold` | float | 30 | RSI 低于此值视为超卖，产生买入信号 |
| `overbought_threshold` | float | 70 | RSI 高于此值视为超买，产生卖出信号 |

**买卖逻辑**：

- **买入**：RSI 从下方上穿 `oversold_threshold`
- **卖出**：RSI 从上方下穿 `overbought_threshold`

阈值越低越保守（买入机会少），越高越激进。常见组合：30/70（标准）、20/80（极端）。

## 布林带

基于布林带的价格触及上下轨策略。

```python
from jh_quant.backtest import StrategyBollingerBands

strategy = StrategyBollingerBands(
    window=20,                  # 均线和标准差窗口
    num_std=2.0,                # 标准差倍数
    use_mean_reversion=True,    # True=均值回归, False=突破
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `window` | int | 20 | 中轨（MA）和标准差的计算窗口 |
| `num_std` | float | 2.0 | 上下轨与中轨的标准差倍数 |
| `use_mean_reversion` | bool | True | True：触及下轨买入、上轨卖出；False：突破上轨买入、下轨卖出 |

**买卖逻辑**：

- `use_mean_reversion=True`（默认）：价格触及下轨 → 买入（期待反弹）；价格触及上轨 → 卖出
- `use_mean_reversion=False`：价格突破上轨 → 买入（追涨）；价格跌破下轨 → 卖出

## 动量

基于价格动量的趋势跟踪策略。

```python
from jh_quant.backtest import StrategyMomentum

strategy = StrategyMomentum(
    momentum_window=20,          # 动量计算窗口
    momentum_threshold=0.05,     # 动量阈值（小数，如 0.05 = 5%）
    ma_window=60,                # 趋势过滤均线窗口
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `momentum_window` | int | 20 | 计算动量的回顾窗口 |
| `momentum_threshold` | float | 0.05 | 动量绝对值超过此阈值才产生信号 |
| `ma_window` | int | 60 | 用于趋势过滤的均线窗口（价格在 MA 之上才做多） |

**买卖逻辑**：

- **买入**：N 日动量 > `momentum_threshold`，且价格在 MA 之上
- **卖出**：N 日动量 < `-momentum_threshold`，或价格跌破 MA

动量 = (当日收盘价 - N 日前收盘价) / N 日前收盘价。

## 均值回归

基于价格偏离均线程度的均值回归策略。

```python
from jh_quant.backtest import StrategyMeanReversion

strategy = StrategyMeanReversion(
    ma_window=20,                 # 均线窗口
    deviation_threshold=0.02,     # 偏离阈值（小数）
    rsi_window=14,                # RSI 辅助过滤窗口
    rsi_oversold=30,              # RSI 超卖辅助确认
    rsi_overbought=70,            # RSI 超买辅助确认
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ma_window` | int | 20 | 均线计算窗口 |
| `deviation_threshold` | float | 0.02 | 价格偏离均线超过此比例触发信号 |
| `rsi_window` | int | 14 | RSI 辅助指标的窗口 |
| `rsi_oversold` | float | 30 | RSI 低于此值辅助确认买入 |
| `rsi_overbought` | float | 70 | RSI 高于此值辅助确认卖出 |

**买卖逻辑**：

- **买入**：价格低于均线超过 `deviation_threshold`，且 RSI 处于超卖区
- **卖出**：价格高于均线超过 `deviation_threshold`，且 RSI 处于超买区

RSI 辅助过滤可减少假信号。

## 突破

基于价格突破 N 日极值的通道策略。

```python
from jh_quant.backtest import StrategyBreakout

strategy = StrategyBreakout(
    lookback_period=20,          # 回顾窗口
    atr_multiplier=2.0,          # ATR 止损倍数
    use_atr_stop=True,           # 是否使用 ATR 跟踪止损
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `lookback_period` | int | 20 | 计算最高价的回顾窗口 |
| `atr_multiplier` | float | 2.0 | ATR 止损距离倍数 |
| `use_atr_stop` | bool | True | 是否启用 ATR 跟踪止损离场 |

**买卖逻辑**：

- **买入**：收盘价突破 `lookback_period` 日最高价
- **卖出**：若 `use_atr_stop=True`，从最高点回落超过 `atr_multiplier * ATR` 时卖出；否则跌破 `lookback_period` 日最低价时卖出

## Dual Thrust

经典短线突破策略，基于前 N 日价格区间计算上下轨。

```python
from jh_quant.backtest import StrategyDualThrust

strategy = StrategyDualThrust(
    k1=0.7,                       # 上轨系数
    k2=0.7,                       # 下轨系数
    lookback_period=20,           # 回顾窗口
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `k1` | float | 0.7 | 上轨偏移系数（越大越不容易触发买入） |
| `k2` | float | 0.7 | 下轨偏移系数（越大越不容易触发卖出） |
| `lookback_period` | int | 20 | 计算 Range 的回顾窗口 |

**买卖逻辑**：

```
Range = Max(HH - LC, HC - LL)
上轨 = Open + k1 * Range
下轨 = Open - k2 * Range
```

- **买入**：价格突破上轨
- **卖出**：价格跌破下轨

其中 HH/LL 为前 N 日最高/最低价，HC/LC 为前 N 日最高/最低收盘价。

## 成交量趋势

量价配合的趋势确认策略。

```python
from jh_quant.backtest import StrategyVolumeTrend

strategy = StrategyVolumeTrend(
    ma_window=20,                 # 价格均线窗口
    volume_window=20,             # 成交量均线窗口
    buy_threshold=0.02,           # 买入信号强度阈值
    sell_threshold=-0.02,         # 卖出信号强度阈值
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ma_window` | int | 20 | 价格均线计算窗口 |
| `volume_window` | int | 20 | 成交量均线计算窗口 |
| `buy_threshold` | float | 0.02 | 综合信号超过此值产生买入 |
| `sell_threshold` | float | -0.02 | 综合信号低于此值产生卖出 |

**买卖逻辑**：综合价格趋势和成交量变化生成信号。价格在均线上方且放量时倾向买入；价格在均线下方且缩量时倾向卖出。

## 成交量背离

捕捉价格与成交量背离的反转策略。

```python
from jh_quant.backtest import StrategyVolumeDivergence

strategy = StrategyVolumeDivergence(
    rsi_window=14,                # RSI 窗口
    volume_window=20,             # 成交量均线窗口
    buy_threshold=0.02,           # 买入信号强度阈值
    sell_threshold=-0.02,         # 卖出信号强度阈值
)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rsi_window` | int | 14 | RSI 计算窗口 |
| `volume_window` | int | 20 | 成交量均线计算窗口 |
| `buy_threshold` | float | 0.02 | 综合信号超过此值产生买入 |
| `sell_threshold` | float | -0.02 | 综合信号低于此值产生卖出 |

**买卖逻辑**：当价格下跌但成交量萎缩（下跌动能减弱）时产生买入信号；当价格上涨但成交量未能放大（上涨动能不足）时产生卖出信号。

## 自定义策略

继承 `Strategy` 基类，实现 `_execute_one(self, symbol, df)` 方法即可：

```python
from jh_quant.backtest import Strategy
import pandas as pd

class MyStrategy(Strategy):
    def __init__(self, ma_window=20):
        super().__init__()
        self.ma_window = ma_window

    def _execute_one(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """
        参数:
            symbol: 股票代码
            df: 单只股票的价格数据，包含 open/high/low/close/volume
        返回:
            原 df 增加 buy_signal 和 sell_signal 列（0/1 整数）
        """
        df = df.copy()
        df['ma'] = df['close'].rolling(self.ma_window).mean()

        # 价格上穿 MA 买入
        df['buy_signal'] = (
            (df['close'] > df['ma']) &
            (df['close'].shift(1) <= df['ma'].shift(1))
        ).astype(int)

        # 价格下穿 MA 卖出
        df['sell_signal'] = (
            (df['close'] < df['ma']) &
            (df['close'].shift(1) >= df['ma'].shift(1))
        ).astype(int)

        return df
```

**注意事项**：

- `_execute_one` 接收的 `df` 已按日期排序，只包含单只股票的数据
- 基类会自动并行处理多只股票（使用 joblib，`n_jobs = cpu_count - 1`）
- `buy_signal` 和 `sell_signal` 必须是整数 0 或 1
- 同一交易日可以同时产生买入和卖出信号（框架以最后信号为准）
- 不要在 `__init__` 中执行耗时操作，策略实例会被 pickle 序列化以支持并行
