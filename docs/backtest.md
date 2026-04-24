# jh_quant.backtest

高性能金融回测和选股引擎，基于 jh_quant 数据层构建。

- **多进程并行回测**：内置多进程并行计算，回测速度极快
- **内置11种策略**：海龟交易、均线交叉、RSI、布林带、动量等经典策略
- **易于扩展**：支持自定义策略（继承 `Strategy` 基类）
- **完整的风险管理**：支持止损、跟踪止损、最大持仓天数等多种风险管理规则

## 快速开始

### 基本回测示例

```python
from jh_quant.data import JHData, DataTypes
from jh_quant.backtest import (
    backtest,
    StrategyTurtle,
    StrategyMovingAverageCrossover,
    StrategyBuyAndHold,
    display_backtesting,
)
import warnings

warnings.filterwarnings("ignore")

jh = JHData()

# 定义策略
strategies = {
    "海龟": StrategyTurtle(entry_window=20, exit_window=10),
    "移动均线交叉": StrategyMovingAverageCrossover(12, 24),
    "买入持有": StrategyBuyAndHold(),
}

# 获取数据
symbols = ["000001", "600036", "600519", "000858", "601318", "000002"]
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    start="2024-12-25",
    end="2026-03-11",
    symbol=",".join(symbols),
)
stock_info = jh.get_data(DataTypes.AK_STOCK_INDIVIDUAL_INFO_EM)

# 执行回测
trading_history, backtest_perf = backtest(
    strategies,
    stock_price,
    stock_info,
)

# 展示回测仪表盘
display_backtesting(trading_history, backtest_perf)
```

### 风险管理

```python
from jh_quant.backtest import RiskManagementParams

rmp = RiskManagementParams(
    max_holding_days=10,           # 最大持仓天数
    stop_loss_pct=0.05,            # 止损比例 (5%)
    trailing_stop_pct=0.03,        # 跟踪止损 (3%)
    max_consecutive_rising_days=5,  # 最大连续上涨天数
    max_consecutive_falling_days=5, # 最大连续下跌天数
)

# 传入风险管理参数
trading_history, backtest_perf = backtest(
    strategies,
    stock_price,
    stock_info,
    risk_params=rmp,
)
```

## 内置策略

| 策略        | 类名                             | 说明                     |
| ----------- | -------------------------------- | ------------------------ |
| 海龟交易    | `StrategyTurtle`                 | 趋势跟踪，基于高低点突破 |
| 均线交叉    | `StrategyMovingAverageCrossover` | 金叉买入，死叉卖出       |
| 买入持有    | `StrategyBuyAndHold`             | 长期投资基准             |
| RSI         | `StrategyRSI`                    | 超买超卖区域交易         |
| 布林带      | `StrategyBollingerBands`         | 突破或均值回归           |
| 动量        | `StrategyMomentum`               | 趋势延续                 |
| 突破        | `StrategyBreakout`               | 历史高低点突破           |
| Dual Thrust | `StrategyDualThrust`             | 日内突破                 |
| 成交量趋势  | `StrategyVolumeTrend`            | 量价配合                 |
| 量价背离    | `StrategyVolumeDivergence`       | 背离信号                 |
| 均值回归    | `StrategyMeanReversion`          | 回归均线                 |

### 策略示例

```python
from jh_quant.backtest import (
    StrategyTurtle,
    StrategyRSI,
    StrategyBollingerBands,
)

# 海龟策略
turtle = StrategyTurtle(entry_window=20, exit_window=10)

# RSI策略
rsi = StrategyRSI(rsi_window=14, rsi_oversold=30, rsi_overbought=70)

# 布林带策略（均值回归模式）
bb = StrategyBollingerBands(window=20, num_std=2.0, use_mean_reversion=True)
```

## 自定义策略

继承 `Strategy` 基类，实现 `_execute_one` 方法：

```python
from jh_quant.backtest import Strategy
import pandas as pd

class MyStrategy(Strategy):
    """自定义策略"""

    def __init__(self, param1=10, param2=20):
        super().__init__()
        self.param1 = param1
        self.param2 = param2

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的执行策略逻辑"""
        data = data.copy()

        # 计算指标
        data["ma"] = data["close"].rolling(window=self.param1).mean()

        # 生成信号
        data["buy_signal"] = (data["close"] > data["ma"]).astype(int)
        data["sell_signal"] = (data["close"] < data["ma"]).astype(int)

        return data
```

## 风险管理参数

```python
from jh_quant.backtest import RiskManagementParams

rmp = RiskManagementParams(
    max_holding_days=10,           # 最大持仓天数
    stop_loss_pct=0.05,            # 止损比例 (5%)
    trailing_stop_pct=0.03,        # 跟踪止损 (3%)
    max_consecutive_rising_days=5,  # 最大连续上涨天数
    max_consecutive_falling_days=5, # 最大连续下跌天数
)
```

## 核心功能

### backtest

主回测函数：

```python
from jh_quant.backtest import backtest

trading_history, backtest_perf = backtest(
    strategies,        # 策略字典 {"策略名": Strategy实例}
    stock_price,       # 股票价格数据
    stock_info,        # 股票基本信息
    initialCash=1000000,  # 初始资金（默认100万）
    risk_params=None,     # RiskManagementParams实例
)
```

### 可视化

展示回测仪表盘：

```python
from jh_quant.dashboard import display_backtesting

display_backtesting(trading_history, backtest_perf)
```

| 策略对比                                        | 策略分布                                     |
| ----------------------------------------------- | -------------------------------------------- |
| ![策略对比](../assets/strat_compare_resized.png) | ![策略分布](../assets/strat_dist_resized.png) |

| 交易历史                                          | 策略排名                                        |
| ------------------------------------------------- | ----------------------------------------------- |
| ![交易历史](../assets/trading_history_resized.png) | ![策略排名](../assets/strat_ranking_resized.png) |
