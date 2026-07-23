# 交易模块 (trading)

## 快速开始

### 模拟盘

```bash
# 默认启动（半导体观察池，paper-compare 模板）
jh-quant paper

# 指定策略
jh-quant paper --strategy turtle,momentum

# 自定义股票池 + 初始资金
jh-quant paper --symbols 688041,688256 --initial-capital 200000

# 纯 API 模式
jh-quant paper --no-dashboard --port 8080

# 关闭回填，仅实时行情
jh-quant paper --no-backfill
```

### 实盘

```bash
jh-quant live
```

运行前需要设置 MiniQMT 环境变量：

```bash
export MINIQMT_USERDATA_DIR=/path/to/userdata
export MINIQMT_STOCK_ACCOUNT=your_account
```

## 两种运行模式

| 维度 | Paper | Live |
|------|-------|------|
| Broker | `PaperBroker` 自动创建 | 必须显式配置真实 broker |
| 时钟模式 | `realtime` / `backfill` | 仅 `realtime` |
| 成交语义 | 本地模拟成交 | 真实柜台/终端成交 |
| 持仓与资金 | 本地状态机维护 | 以 broker 查询结果为准 |
| 回填 | 支持 | 不支持 |
| 适用场景 | 策略验证、影子组合、回放 | 实盘执行 |

## CLI 全部选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--template` | str | paper: `paper-compare` / live: `live-basic` | Bootstrap 模板 |
| `--backend` | str | `tushare` | 行情后端：`tushare`, `akshare`, `xquant` |
| `--strategy` | str | `momentum` | 策略名，逗号分隔，共 11 种可选 |
| `--symbols` | str | 半导体/AI芯片观察池 | 股票池纯代码，逗号分隔 |
| `--host` | str | `127.0.0.1` | API 绑定地址 |
| `--port` | int | `8000` | API 端口 |
| `--db-path` | str | paper: `trade_paper.db` / live: `trade_live.db` | SQLite 数据库路径 |
| `--initial-capital` | float | `100000` | 模拟盘初始资金（仅 paper） |
| `--cron` | str | `0 14 * * 1-5` | 交易循环 cron，默认交易日 14:00 |
| `--backfill-start` | str | 180 天前 | 回填起始日期 `YYYY-MM-DD`（仅 paper） |
| `--no-backfill` | flag | 关闭 | 关闭回填（仅 paper） |
| `--no-dashboard` | flag | 关闭 | 只启动 API |
| `--dashboard-refresh-ms` | int | `15000` | Dashboard 刷新间隔 |
| `--no-auto-start` | flag | 关闭 | 只创建 session，不自动启动 |

纸带交易可用策略：`bollinger_bands`, `breakout`, `buy_and_hold`, `dual_thrust`, `mean_reversion`, `momentum`, `moving_average_crossover`, `rsi`, `turtle`, `volume_divergence`, `volume_trend`

## Bootstrap 模板

| 模板 | 行为 | 默认策略 |
|------|------|---------|
| `paper-basic` | 创建一个模拟盘 session；多策略在同一 session 内等权聚合 | `momentum` |
| `paper-compare` | 为每个策略创建独立 session，始终保留 `turtle` 基准 | `turtle,momentum` |
| `live-basic` | 创建一个实盘 session | `momentum` |

## 行情 Backend

| backend | 历史行情 | 实时行情 |
|---------|---------|---------|
| `tushare` | `TuShareHistoricalBarProvider` | 复用 AkShare 实时行情合并 |
| `akshare` | `AkShareHistoricalBarProvider` | `AkShareRealtimeQuoteProvider` |
| `xquant` | `TuShareHistoricalBarProvider` | `XtQuantRealtimeQuoteProvider` |

## 三层架构

### 1. Bootstrap（一键启动）

```python
from jh_quant.trading.bootstrap import TradingBootstrapConfig, build_paper_manager

config = TradingBootstrapConfig(
    template="paper-compare",
    backend="tushare",
    strategies=["rsi"],
    symbols=["688041", "688256", "688981"],
    initial_capital=100_000,
    db_path="trade_paper.db",
    show_dashboard=True,
)
manager = build_paper_manager(config)
```

### 2. Builder（流式配置）

```python
from jh_quant.trading.config import (
    SessionServiceConfigBuilder,
    ATRTrailingStopRuleConfig,
    MomentumStrategyConfig,
    FactorSelectionConfig,
    RebalanceMode,
    RebalancePolicySpec,
)

config = (
    SessionServiceConfigBuilder.defaults()
    .with_session(session_id="my-session", mode="paper", auto_start=True)
    .with_selection(name="factor", params=FactorSelectionConfig(factor="momentum_20", top_n=10))
    .add_strategy(name="momentum", weight=1.0, params=MomentumStrategyConfig())
    .add_risk_rule(name="atr_trailing_stop", params=ATRTrailingStopRuleConfig(multiplier=3.0, window=20))
    .with_portfolio(enabled=True, objective="MinRisk",
                    rebalance_policy=RebalancePolicySpec(mode=RebalanceMode.DRIFT_THRESHOLD, drift_threshold=0.10))
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

### 3. 手动装配

适用于需要精确控制每个组件的场景。参见 `references/trading.md` 中的完整示例。

## 会话配置参数

```python
.with_session(
    session_id="my-session",           # 会话唯一标识
    mode="paper",                      # "paper" / "live"
    price_lookback_days=365,           # 价格回溯天数
    max_candidates=10,                 # 每周期最大候选标的数
    auto_start=True,                   # 自动启动调度
    frequency="daily",                 # 运行频率
    price_slippage=0.001,              # 成交滑点
    cron_expression="0 16 * * 1-5",    # Cron 表达式
    timezone="Asia/Shanghai",
    restore_persisted_state=True,
    enable_backfill=True,
    backfill_from="2025-01-01",
)
```

### 运行频率

| 值 | 含义 |
|----|------|
| `DAILY` / `"daily"` | 日频 |
| `MINUTE_1` / `"1m"` | 1 分钟 |
| `MINUTE_5` / `"5m"` | 5 分钟 |
| `MINUTE_15` / `"15m"` | 15 分钟 |
| `MINUTE_30` / `"30m"` | 30 分钟 |
| `MINUTE_60` / `"60m"` | 60 分钟 |
| `HOUR_1` / `"1h"` | 1 小时 |

## 选股器

| 选股器 | 说明 |
|--------|------|
| `watchlist` | 固定股票池选股（bootstrap 默认） |
| `factor_selector` | 基于因子排序选股（包装 `FactorSelector`） |

```python
# 内置因子选股
.with_selection(name="factor", params=FactorSelectionConfig(
    factor="momentum_20", top_n=10, period="monthly",
))

# 自定义选股器
register_selection_provider(
    name="my_picker",
    provider_cls=MySelectionProvider,
    config_model=MySelectionConfig,
)
```

## 7 种风控规则

| 规则名称 | 配置类 | 说明 |
|---------|--------|------|
| `stop_loss` | `StopLossRuleConfig` | 固定止损 |
| `take_profit` | `TakeProfitRuleConfig` | 固定止盈 |
| `trailing_stop` | `TrailingStopRuleConfig` | 移动止损 |
| `atr_trailing_stop` | `ATRTrailingStopRuleConfig` | ATR 动态止损 |
| `max_holding_bars` | `MaxHoldingBarsRuleConfig` | 最大持仓周期 |
| `max_consecutive_rising_bars` | `MaxConsecutiveRisingBarsRuleConfig` | 连续上涨止盈 |
| `max_consecutive_falling_bars` | `MaxConsecutiveFallingBarsRuleConfig` | 连续下跌止损 |

```python
.add_risk_rule(name="stop_loss", params=StopLossRuleConfig(threshold=-0.08))
.add_risk_rule(name="take_profit", params=TakeProfitRuleConfig(threshold=0.20))
.add_risk_rule(name="atr_trailing_stop", params=ATRTrailingStopRuleConfig(multiplier=3.0, window=20))
```

## 组合优化

```python
.with_portfolio(
    enabled=True,
    objective="MinRisk",              # 优化目标
    risk_measure="MV",                # 风险度量
    model="Classic",                  # 风险模型
    covariance_method="hist",         # 协方差估计
    min_weight=0.01,                  # 最小权重
    max_weight=0.20,                  # 最大权重
    lookback=252,                     # 回看天数
    rebalance_policy=RebalancePolicySpec(
        mode=RebalanceMode.DRIFT_THRESHOLD,
        drift_threshold=0.10,         # 漂移阈值 10%
    ),
)
```

### RebalanceMode

| 模式 | 说明 |
|------|------|
| `DISABLED` | 禁用再平衡 |
| `INITIAL_ONLY` | 仅初次建仓 |
| `EVERY_CYCLE` | 每周期再平衡 |
| `DRIFT_THRESHOLD` | 偏离阈值触发 |
| `SCHEDULE` | 按 Cron 定时 |
| `MANUAL_ONLY` | 仅手动触发 |

## 配置导入导出

```python
from jh_quant.trading.config import export_config_to_file, import_config_from_file

export_config_to_file(config, "my_config.json")
config = import_config_from_file("my_config.json")
```

## 常见开发任务

- **新增策略配置**：在 `trading/config.py` 中注册策略定义和 Config 类
- **新增选股器**：继承 `SelectionProvider`，通过 `register_selection_provider()` 注册
- **新增风控规则**：在 `trading/risk/` 下实现，注册到配置系统
- **新增 Broker**：实现 Broker 接口，对接真实柜台

## 查看可用定义

```python
from jh_quant.trading.config import list_strategy_definitions, list_risk_rule_definitions

for s in list_strategy_definitions():
    print(f"{s.name}: {s.description}")

for r in list_risk_rule_definitions():
    print(f"{r.name}: {r.description}")
```
