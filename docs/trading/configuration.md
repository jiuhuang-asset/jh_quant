# 配置指南

`SessionServiceConfigBuilder` 是配置交易会话的入口，采用流式 Builder 模式串联所有配置。

## SessionServiceConfigBuilder

```python
from jh_quant.trading.config import SessionServiceConfigBuilder

config = (
    SessionServiceConfigBuilder.defaults()
    .with_session(...)       # 会话基础配置
    .with_selection(...)     # 选股器配置
    .with_portfolio(...)     # 组合优化配置（可选）
    .add_strategy(...)       # 添加策略（可多次调用）
    .add_risk_rule(...)      # 添加风险规则（可多次调用）
    .build()
)
```

支持基于已有配置派生：

```python
config_b = (
    SessionServiceConfigBuilder(base_config=config)
    .with_session(session_id="session-b")
    .add_strategy(name="dual_thrust", weight=1.0, params=DualThrustStrategyConfig())
    .build()
)
```

---

## 会话基础配置 (`with_session`)

```python
.with_session(
    session_id="my-session",           # 会话唯一标识
    mode="paper",                      # "paper" 模拟 / "live" 实盘
    price_lookback_days=365,           # 价格数据回溯天数
    max_candidates=10,                 # 每周期最大候选标的数
    auto_start=True,                   # 创建后是否自动启动调度
    frequency="daily",                 # 运行频率
    price_slippage=0.001,              # 成交滑点（0.001 = 0.1%）
    cron_expression="0 16 * * 1-5",    # Cron 表达式（交易日 16:00）
    timezone="Asia/Shanghai",          # 时区
    restore_persisted_state=True,      # 是否从持久化恢复状态
    enable_backfill=True,              # 是否启用历史回填
    backfill_from="2025-01-01",        # 回填起始日期
)
```

### 运行频率 (`frequency`)

`Frequency` 枚举支持以下值：

| 值 | 含义 |
|----|------|
| `DAILY` / `"daily"` | 日频 |
| `MINUTE_1` / `"1m"` | 1 分钟 |
| `MINUTE_5` / `"5m"` | 5 分钟 |
| `MINUTE_15` / `"15m"` | 15 分钟 |
| `MINUTE_30` / `"30m"` | 30 分钟 |
| `MINUTE_60` / `"60m"` | 60 分钟 |
| `HOUR_1` / `"1h"` | 1 小时 |

---

## 策略配置 (`add_strategy`)

系统内置 **11 种策略**。可多次调用 `.add_strategy()` 来组合多策略。

```python
.add_strategy(
    name="momentum",          # 策略名称（必填，见下表）
    alias="my_momentum",      # 别名（可选，用于日志区分）
    weight=1.0,               # 权重（多策略时用于信号加权）
    params=MomentumStrategyConfig(...),  # 策略参数
)
```

### 内置策略一览

| 策略名称 (`name`) | 配置类 | 说明 |
|---|---|---|
| `momentum` | `MomentumStrategyConfig` | 动量策略，基于收益率排序 |
| `moving_average_crossover` | `MovingAverageCrossoverStrategyConfig` | 均线交叉策略 |
| `buy_and_hold` | `BuyAndHoldStrategyConfig` | 买入持有策略 |
| `volume_trend` | `VolumeTrendStrategyConfig` | 量价趋势策略 |
| `volume_divergence` | `VolumeDivergenceStrategyConfig` | 量价背离策略 |
| `mean_reversion` | `MeanReversionStrategyConfig` | 均值回归策略 |
| `rsi` | `RSIStrategyConfig` | RSI 相对强弱策略 |
| `bollinger_bands` | `BollingerBandsStrategyConfig` | 布林带策略 |
| `breakout` | `BreakoutStrategyConfig` | 突破策略 |
| `dual_thrust` | `DualThrustStrategyConfig` | 双重推力策略 |
| `turtle` | `TurtleStrategyConfig` | 海龟交易策略 |

### 多策略组合

系统会自动按权重聚合多个策略的买卖信号（加权求和）。

```python
config = (
    SessionServiceConfigBuilder.defaults()
    # ...
    .add_strategy(name="momentum", alias="mom", weight=0.6,
                  params=MomentumStrategyConfig(window=20))
    .add_strategy(name="mean_reversion", alias="mr", weight=0.4,
                  params=MeanReversionStrategyConfig(window=10))
    .build()
)
```

### 查看可用策略及参数

```python
from jh_quant.trading.config import list_strategy_definitions

for s in list_strategy_definitions():
    print(f"{s.name}: {s.description}")
    print(f"  参数: {s.params_schema}")
```

---

## 风险规则配置 (`add_risk_rule`)

系统内置 **7 种风险规则**。风险规则在每周期对候选标的进行过滤。

```python
.add_risk_rule(
    name="stop_loss",                  # 规则名称（见下表）
    params=StopLossRuleConfig(...),    # 规则参数
)
```

### 内置风险规则一览

| 规则名称 (`name`) | 配置类 | 说明 |
|---|---|---|
| `stop_loss` | `StopLossRuleConfig` | 固定止损：亏损超过阈值则卖出 |
| `take_profit` | `TakeProfitRuleConfig` | 固定止盈：盈利超过阈值则卖出 |
| `trailing_stop` | `TrailingStopRuleConfig` | 移动止损：从最高点回撤超过阈值止损 |
| `atr_trailing_stop` | `ATRTrailingStopRuleConfig` | ATR 移动止损：基于 ATR 的动态止损 |
| `max_holding_bars` | `MaxHoldingBarsRuleConfig` | 最大持仓周期：超过 N 根 K 线则卖出 |
| `max_consecutive_rising_bars` | `MaxConsecutiveRisingBarsRuleConfig` | 连续上涨 N 根 K 线后止盈 |
| `max_consecutive_falling_bars` | `MaxConsecutiveFallingBarsRuleConfig` | 连续下跌 N 根 K 线后止损 |

### 示例

```python
from jh_quant.trading.config import (
    StopLossRuleConfig,
    TakeProfitRuleConfig,
    ATRTrailingStopRuleConfig,
)

config = (
    SessionServiceConfigBuilder.defaults()
    # ...
    .add_risk_rule(name="stop_loss",
                   params=StopLossRuleConfig(threshold=-0.08))
    .add_risk_rule(name="take_profit",
                   params=TakeProfitRuleConfig(threshold=0.20))
    .add_risk_rule(name="atr_trailing_stop",
                   params=ATRTrailingStopRuleConfig(multiplier=3.0, window=20))
    .build()
)
```

### 查看可用风险规则

```python
from jh_quant.trading.config import list_risk_rule_definitions

for r in list_risk_rule_definitions():
    print(f"{r.name}: {r.description}")
```

---

## 选股器配置 (`with_selection`)

### 使用内置因子选股

```python
from jh_quant.trading.config import FactorSelectionConfig

config = (
    SessionServiceConfigBuilder.defaults()
    .with_selection(
        name="factor",
        params=FactorSelectionConfig(
            factor="momentum_20",          # 因子名称
            start="2020-01-01",
            top_n=10,                      # 选取前 N 名
            bottom_n=0,                    # 做空前 N 名
            period="monthly",              # 调仓周期
        ),
    )
    .build()
)
```

### 使用自定义选股器

先注册，再引用：

```python
register_selection_provider(
    name="my_picker",
    provider_cls=MySelectionProvider,
    config_model=MySelectionConfig,
)

config = (
    SessionServiceConfigBuilder.defaults()
    .with_selection(name="my_picker", params=MySelectionConfig(...))
    .build()
)
```

详见[扩展开发 - 自定义选股器](customization.md#自定义选股器)。

---

## 组合优化配置 (`with_portfolio`)

组合优化为可选功能。启用后系统自动计算最优持仓权重并管理再平衡。

```python
from jh_quant.trading.config import RebalanceMode, RebalancePolicySpec

config = (
    SessionServiceConfigBuilder.defaults()
    .with_portfolio(
        enabled=True,                         # 启用组合优化
        objective="MinRisk",                  # 优化目标
        risk_measure="MV",                    # 风险度量
        model="Classic",                      # 风险模型
        covariance_method="hist",             # 协方差估计方法
        min_weight=0.01,                      # 单标的最小权重
        max_weight=0.20,                      # 单标的最大权重
        lookback=252,                         # 回看天数
        rebalance_policy=RebalancePolicySpec(
            mode=RebalanceMode.DRIFT_THRESHOLD,
            drift_threshold=0.10,             # 漂移阈值 10%
            min_rebalance_interval_seconds=86400,
        ),
    )
    .build()
)
```

### 再平衡模式 (`RebalanceMode`)

| 模式 | 说明 |
|------|------|
| `DISABLED` | 禁用再平衡 |
| `INITIAL_ONLY` | 仅在初次建仓时再平衡 |
| `EVERY_CYCLE` | 每个周期都再平衡 |
| `DRIFT_THRESHOLD` | 持仓偏离超过阈值时触发再平衡 |
| `SCHEDULE` | 按 Cron 表达式定时再平衡 |
| `MANUAL_ONLY` | 仅手动触发再平衡 |

详见[组合优化](portfolio.md)。

---

## 配置导入导出

```python
from jh_quant.trading.config import export_config_to_file, import_config_from_file

# 导出为 JSON 文件
export_config_to_file(config, "my_config.json")

# 从 JSON 文件导入
config = import_config_from_file("my_config.json")
```
