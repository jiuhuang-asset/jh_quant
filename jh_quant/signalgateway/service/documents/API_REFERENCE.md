# SignalGateway API Reference v1

文档版本：`v1`

本文档偏“接口字典”，用于快速查：

- 路径
- 方法
- 请求体
- 响应体
- 关键字段

前端集成流程说明请看 [FRONTEND_INTEGRATION_GUIDE.md](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/documents/FRONTEND_INTEGRATION_GUIDE.md:1)。

## Base URL

- 默认：`http://127.0.0.1:8000`

## 1. Health

### `GET /health`

响应：

```json
{
  "status": "ok"
}
```

## 2. Service Status

### `GET /service/status`

响应字段：

- `session_id: string`
- `mode: "paper" | "live"`
- `running: boolean`
- `scheduler: SchedulerStatus`
- `last_error: string | null`
- `last_result: TradingCycleResultResponse | null`

`SchedulerStatus`：

- `interval_seconds: number`
- `cron_expression: string | null`
- `timezone: string`
- `schedule_type: string`
- `next_run_at: string | null`
- `next_run_in_seconds: number | null`
- `next_runs: string[]`

## 3. Runtime

### `GET /service/runtime`

响应字段：

- `session_id: string`
- `generated_at: string`
- `positions: Record<string, any>`
- `oms_state: Record<string, any> | null`

## 4. Performance

### `GET /service/performance`

响应字段：

- `session_id: string`
- `generated_at: string`
- `summary: Record<string, any>`
- `holding_returns: Record<string, any>[]`
- `turnover: Record<string, any>[]`
- `equity_curve: Record<string, any>[]`
- `trade_activity: Record<string, any>[]`
- `position_exposure: Record<string, any>`
- `latest_portfolio: Record<string, any>`

## 5. Analytics

### `GET /service/analytics`

响应字段：

- `session_id: string`
- `generated_at: string`
- `status: ServiceStatusResponse`
- `runtime: RuntimeSnapshotResponse`
- `performance: PerformanceSnapshotResponse`
- `config: ServiceConfigResponse`

## 6. Unified Config

### `GET /service/config`

响应字段：

- `session_id: string`
- `config_bundle: SignalGatewayServiceConfig`
- `service: Record<string, any>`
- `selection_spec: Record<string, any> | null`
- `selection_provider: Record<string, any>`
- `strategy_specs: Record<string, any>[]`
- `portfolio_spec: Record<string, any> | null`
- `config_source: string`
- `persisted_user_config_available: boolean`
- `persisted_user_config_updated_at: string | null`

### `PUT /service/config`

请求体：

```json
{
  "config_bundle": {
    "service": {},
    "selection_spec": null,
    "strategy_specs": [],
    "portfolio_spec": {}
  }
}
```

响应字段：

- `status: string`
- `session_id: string`
- `config_bundle: SignalGatewayServiceConfig`

## 7. Events

### `GET /service/events`

响应字段：

- `session_id: string`
- `count: number`
- `events: ServiceEventRecordResponse[]`

`ServiceEventRecordResponse`：

- `event_type: string`
- `event_time: string | null`
- `export_time: string | null`
- `state_data: Record<string, any>`

## 8. Service Actions

### `POST /service/start`

响应：

```json
{
  "status": "started",
  "session_id": "sg-paper-001"
}
```

### `POST /service/stop`

响应：

```json
{
  "status": "stopped",
  "session_id": "sg-paper-001"
}
```

### `POST /service/run-once`

响应字段：

- `session_id: string`
- `mode: string`
- `cycle_time: string`
- `selection_count: number`
- `long_candidate_count: number`
- `short_candidate_count: number`
- `executed_buy_count: number`
- `executed_sell_count: number`
- `selected_symbols: string[]`
- `long_symbols: string[]`
- `short_symbols: string[]`
- `status: string`
- `error: string | null`

## 9. Scheduler Config

### `GET /service/scheduler-config`

响应字段：

- `running: boolean`
- `auto_start: boolean`
- `scheduler: SchedulerStatus`

### `POST /service/scheduler-config`

请求体：

```json
{
  "interval_seconds": 300,
  "cron_expression": "0 15 * * 1-5",
  "timezone": "Asia/Shanghai",
  "auto_start": true
}
```

字段说明：

- `interval_seconds?: number`
- `cron_expression?: string | null`
- `timezone?: string | null`
- `auto_start?: boolean | null`

响应字段：

- `status: string`
- `running: boolean`
- `scheduler: SchedulerStatus`
- `auto_start: boolean`

## 10. Selection Config

### `GET /service/selection-config`

响应字段：

- `selection_spec: SelectionSpec | null`
- `active_selection_config: Record<string, any>`
- `available_selections: ConfigurableComponentDefinition[]`

`SelectionSpec`：

- `name: string`
- `params: Record<string, any>`
- `alias: string | null`

`ConfigurableComponentDefinition`：

- `name: string`
- `params_schema: Record<string, any>`
- `runtime_dependencies: string[]`

### `POST /service/selection-config`

请求体：

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "月频动量",
    "params": {
      "factor": "momentum",
      "start": "2020-01-01",
      "top_n": 100,
      "bottom_n": 100,
      "factor_alpha": 0.1,
      "default_weight": 0.1,
      "period": "M",
      "insignificant_weight_ratio": 0.5,
      "missing_data_threshold": 0.1,
      "test_window": 36,
      "verbose": true
    }
  }
}
```

响应字段：

- `status: string`
- `name: string`
- `alias: string | null`
- `selection_spec: SelectionSpec`

## 11. Strategy Config

### `GET /service/strategy-config`

响应字段：

- `strategy_specs: StrategySpec[]`
- `available_strategies: ConfigurableComponentDefinition[]`

`StrategySpec`：

- `name: string`
- `weight: number`
- `params: Record<string, any>`
- `alias: string | null`

### `POST /service/strategy-config`

请求体：

```json
{
  "strategy_specs": [
    {
      "name": "moving_average_crossover",
      "weight": 1,
      "alias": "均线交叉",
      "params": {
        "short_window": 20,
        "long_window": 60
      }
    }
  ]
}
```

响应字段：

- `status: string`
- `count: number`
- `strategy_specs: StrategySpec[]`

## 12. Portfolio Config

### `GET /service/portfolio/config`

响应字段：

- `portfolio_spec: PortfolioSpec`
- `available_optimizers: PortfolioOptimizerDefinitionResponse[]`

`PortfolioOptimizerDefinitionResponse`：

- `name: string`
- `params_schema: Record<string, any>`
- `optional_dependency: string | null`
- `notes: string[]`

### `POST /service/portfolio/config`

请求体：

```json
{
  "portfolio_spec": {
    "enabled": true,
    "optimizer": "riskfolio",
    "objective": "Sharpe",
    "risk_measure": "MV",
    "model": "Classic",
    "covariance_method": "ledoit",
    "historical_lookback_days": 252,
    "max_assets": 20,
    "min_weight": 0.0,
    "max_weight": 0.2,
    "weight_epsilon": 0.001,
    "cash_reserve_ratio": 0.02,
    "lot_size": 100,
    "allow_partial_rebalance": true,
    "rebalance_policy": {
      "mode": "manual_only",
      "drift_threshold": null,
      "min_rebalance_interval_seconds": null,
      "schedule_cron": null,
      "on_selection_change": true,
      "on_strategy_change": true
    },
    "analysis": {
      "enabled": true,
      "benchmark_symbol": "000300.SH",
      "risk_free_rate": 0.02,
      "rolling_window": 60
    }
  }
}
```

响应字段：

- `status: string`
- `portfolio_spec: PortfolioSpec`

## 13. Portfolio Optimize

### `POST /service/portfolio/optimize`

请求体：

```json
{
  "as_of_date": "2026-04-28",
  "preview_only": true,
  "symbols": ["000001", "600519"]
}
```

响应字段：

- `status: string`
- `optimizer: string`
- `as_of_date: string`
- `symbols: string[]`
- `weights: Record<string, any>[]`
- `diagnostics: Record<string, any>`
- `preview_only: boolean`

## 14. Portfolio Analysis

### `GET /service/portfolio/analysis`

响应字段：

- `portfolio_spec: PortfolioSpec`
- `current_portfolio: Record<string, any>`
- `drift: Record<string, any>`
- `latest_optimization: Record<string, any> | null`
- `latest_rebalance: Record<string, any> | null`

## 15. Portfolio History

### `GET /service/portfolio/history`

响应字段：

- `weight_history: Record<string, any>[]`
- `portfolio_value_history: Record<string, any>[]`

## 16. Portfolio Rebalance

### `POST /service/portfolio/rebalance`

请求体：

```json
{
  "as_of_date": "2026-04-28",
  "preview_only": true,
  "symbols": ["000001", "600519"],
  "force": false
}
```

响应字段：

- `status: string`
- `as_of_date: string`
- `preview_only: boolean`
- `should_rebalance: boolean`
- `reason: string`
- `execution_path: string | null`
- `target_allocations: Record<string, any>[]`
- `buy_orders: Record<string, any>[]`
- `sell_orders: Record<string, any>[]`
- `blocked_buy_orders: Record<string, any>[]`
- `blocked_sell_orders: Record<string, any>[]`
- `projected_buy_cost: number`
- `projected_sell_value: number`
- `projected_cash_after: number`
- `drift: Record<string, any>`
- `executed_buy_count: number`
- `executed_sell_count: number`

## 17. Trading Operations

### `POST /service/close-all-positions`

请求体：

```json
{
  "slippage": 0.001
}
```

响应字段：

- `status: string`
- `closed_count: number`
- `executed_trades: Record<string, any>[]`

### `POST /service/signal-buy`

请求体：

```json
{
  "symbol": "600519",
  "target_qty": 100,
  "slippage": 0.001
}
```

### `POST /service/signal-sell`

请求体：

```json
{
  "symbol": "600519",
  "target_qty": 100,
  "slippage": 0.001
}
```

单标的交易响应字段：

- `status: string`
- `action: string`
- `symbol: string`
- `executed: boolean`
- `trade: Record<string, any> | null`
- `message: string`

## 18. Core Config Models

### `SignalGatewayServiceConfig`

字段：

- `service: ServiceConfig`
- `selection_spec: SelectionSpec | null`
- `strategy_specs: StrategySpec[]`
- `portfolio_spec: PortfolioSpec`

### `ServiceConfig`

字段：

- `session_id: string | null`
- `mode: "paper" | "live"`
- `price_lookback_days: number`
- `max_candidates: number`
- `auto_start: boolean`
- `frequency: string`
- `price_slippage: number`
- `interval_seconds: number`
- `cron_expression: string | null`
- `timezone: string`
- `restore_persisted_state: boolean`

### `PortfolioSpec`

核心字段：

- `enabled: boolean`
- `optimizer: string`
- `objective: string`
- `risk_measure: string`
- `model: string`
- `covariance_method: string`
- `historical_lookback_days: number`
- `max_assets: number | null`
- `min_weight: number`
- `max_weight: number`
- `weight_epsilon: number`
- `cash_reserve_ratio: number`
- `lot_size: number`
- `allow_partial_rebalance: boolean`
- `rebalance_policy: RebalancePolicySpec`
- `analysis: PortfolioAnalysisSpec`

### `RebalancePolicySpec`

字段：

- `mode: "disabled" | "initial_only" | "every_cycle" | "drift_threshold" | "schedule" | "manual_only"`
- `drift_threshold: number | null`
- `min_rebalance_interval_seconds: number | null`
- `schedule_cron: string | null`
- `on_selection_change: boolean`
- `on_strategy_change: boolean`

### `PortfolioAnalysisSpec`

字段：

- `enabled: boolean`
- `benchmark_symbol: string | null`
- `risk_free_rate: number`
- `rolling_window: number`
