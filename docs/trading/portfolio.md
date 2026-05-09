# 组合优化

`jh_quant.trading` 集成了 [Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) 进行组合优化与再平衡管理。

## 启用组合优化

通过 `.with_portfolio()` 配置：

```python
from jh_quant.trading.config import (
    SessionServiceConfigBuilder,
    RebalanceMode,
    RebalancePolicySpec,
)

config = (
    SessionServiceConfigBuilder.defaults()
    .with_session(session_id="optimized-portfolio", mode="paper")
    .with_selection(...)
    .add_strategy(...)
    .with_portfolio(
        enabled=True,
        objective="MinRisk",           # 优化目标
        risk_measure="MV",             # 风险度量
        model="Classic",               # 风险模型
        covariance_method="hist",      # 协方差估计方法
        min_weight=0.01,
        max_weight=0.20,
        lookback=252,                  # 回看天数
        rebalance_policy=RebalancePolicySpec(
            mode=RebalanceMode.DRIFT_THRESHOLD,
            drift_threshold=0.10,
        ),
    )
    .build()
)
```

## 优化参数

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `objective` | `MinRisk`, `MaxRet`, `MaxSharpe`, `MaxUtility`, `MinRiskCDaR`, `MaxSTARR` | 优化目标函数 |
| `risk_measure` | `MV`, `MAD`, `MSV`, `FLPM`, `SLPM`, `CVaR`, `CDaR`, `EVaR`, `EDaR`, `ADD`, `UCI` 等 | 风险度量方法 |
| `model` | `Classic`, `BL`, `FM`, `HRP`, `HERC`, `NCO` | 风险/组合模型 |
| `covariance_method` | `hist`, `ewma1`, `ewma2`, `ledoit`, `oas`, `shrunk`, `gl`, `jse`, `fixed` | 协方差矩阵估计方法 |

> 参数最终传给 Riskfolio-Lib，具体含义参见 [Riskfolio-Lib 文档](https://riskfolio-lib.readthedocs.io/)。

---

## 再平衡模式

### `DRIFT_THRESHOLD`（漂移触发）

实际持仓偏离目标权重超过阈值时触发。

```python
rebalance_policy=RebalancePolicySpec(
    mode=RebalanceMode.DRIFT_THRESHOLD,
    drift_threshold=0.10,           # 漂移 10% 触发
    min_rebalance_interval_seconds=86400,  # 最小间隔 1 天
)
```

### `EVERY_CYCLE`（每周期）

每个交易周期都运行优化并再平衡。

```python
rebalance_policy=RebalancePolicySpec(mode=RebalanceMode.EVERY_CYCLE)
```

### `INITIAL_ONLY`（仅首次建仓）

初始运行一次建仓，之后不再自动再平衡，由策略自主调仓。

```python
rebalance_policy=RebalancePolicySpec(mode=RebalanceMode.INITIAL_ONLY)
```

### `SCHEDULE`（定时调度）

按 Cron 表达式定时再平衡。

```python
rebalance_policy=RebalancePolicySpec(
    mode=RebalanceMode.SCHEDULE,
    schedule_cron="0 16 * * 5",  # 每周五 16:00
)
```

### `MANUAL_ONLY`（仅手动）

仅通过 API 或编程接口手动触发再平衡。

---

## 再平衡执行流程

```
策略选股信号
    │
    ▼
Riskfolio-Lib 优化 ── 输入：历史收益率矩阵 + 选股信号
    │                    输出：原始目标权重
    ▼
权重后处理 ── 信号引导的权重微调
    │         单标的上限/下限约束截断
    │
    ▼
再平衡计划 (build_rebalance_plan)
    │   对比目标权重 vs 当前持仓
    │   生成买入/卖出订单
    │   ├── T+1 约束：当日买入不可当日卖出
    │   ├── 资金约束：买入总额不超过可用资金
    │   └── 取整约束：A 股 100 股整倍数
    │
    ▼
TradingEngine 执行订单
```

---

## REST API

### 优化预览

```
POST /sessions/{session_id}/portfolio/optimize
```

预览优化结果，不实际执行。

```json
{
  "as_of_date": "2025-06-01",
  "symbols": ["000001", "000002"],
  "preview_only": true
}
```

### 触发再平衡

```
POST /sessions/{session_id}/portfolio/rebalance
```

请求体：

```json
{
  "as_of_date": "2025-06-01",
  "preview_only": false,
  "force": false
}
```

`force=true` 跳过漂移阈值检查，强制再平衡。

### 查看组合分析

```
GET /sessions/{session_id}/portfolio/analysis
```

返回当前持仓权重、目标权重、漂移情况。

### 查看组合历史

```
GET /sessions/{session_id}/portfolio/history
```

返回历史权重变化时间序列。

---

## 编程接口

直接调用底层 API 而不经过服务层：

```python
from jh_quant.trading.portfolio import (
    RiskfolioPortfolioOptimizer,
    optimize_portfolio_preview,
    build_rebalance_plan,
)
from jh_quant.trading.config.portfolio import PortfolioSpec

# 构造优化规格
spec = PortfolioSpec(
    objective="MinRisk",
    risk_measure="MV",
    model="Classic",
    covariance_method="hist",
    min_weight=0.01,
    max_weight=0.20,
    lookback=252,
)

# 运行优化
optimizer = RiskfolioPortfolioOptimizer()
result = optimizer.optimize(
    returns=returns_df,       # 历史收益率 DataFrame
    portfolio_spec=spec,
    signals=signal_scores,    # 可选：选股信号分数，用于权重微调
)
print(result.weights)          # 目标权重 Series
print(result.diagnostics)      # 优化诊断信息

# 生成再平衡订单
plan = build_rebalance_plan(
    target_weights=result.weights,
    positions=current_positions,
    latest_prices=prices,
    portfolio_spec=spec,
)
print(plan["buy_orders"])      # 买入订单列表
print(plan["sell_orders"])     # 卖出订单列表
```

### `optimize_portfolio_preview` 快捷函数

```python
result = optimize_portfolio_preview(
    returns=returns_df,
    portfolio_spec=spec,
    signals=signal_scores,
)
# 返回 PortfolioOptimizationResult
```
