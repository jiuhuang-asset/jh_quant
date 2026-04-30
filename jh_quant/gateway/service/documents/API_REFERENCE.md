# SignalGateway Service API Reference (v3)

Quick endpoint reference. For full details see [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

## App-Level Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/services` | List all managed services |
| `POST` | `/services` | Create a new service |
| `DELETE` | `/services/{session_id}` | Stop and remove a service |
| `GET` | `/services/compare` | Side-by-side status comparison |
| `GET` | `/services/performance/compare` | Historical performance comparison with equity curves |
| `POST` | `/data/count` | Count records for a data type |
| `POST` | `/data/query` | Query data with filters |
| `GET` | `/data/types` | List available data types |
| `GET` | `/data/schema/{data_type}` | Get schema for a data type |

## Session-Scoped Endpoints

All under `/services/{session_id}/*`.

### Status & Monitoring

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/status` | Service status and scheduler state |
| `GET` | `/services/{session_id}/runtime` | Runtime snapshot (positions, OMS state) |
| `GET` | `/services/{session_id}/performance` | Performance metrics and equity curve |
| `GET` | `/services/{session_id}/analytics` | Aggregated snapshot (status + runtime + performance + config) |
| `GET` | `/services/{session_id}/events` | Service event history |

### Config

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/config` | Get full config snapshot |
| `PUT` | `/services/{session_id}/config` | Replace full config |
| `POST` | `/services/{session_id}/config/import` | Import config from uploaded JSON file |
| `GET` | `/services/{session_id}/config/export` | Export config as downloadable JSON |

### Scheduler

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/scheduler-config` | Get scheduler configuration |
| `POST` | `/services/{session_id}/scheduler-config` | Update scheduler configuration |
| `POST` | `/services/{session_id}/scheduler/start` | Start scheduler |
| `POST` | `/services/{session_id}/scheduler/stop` | Stop scheduler |
| `POST` | `/services/{session_id}/run-once` | Execute one trading cycle immediately |

### Selection

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/selection-config` | Get selection config and available selectors |
| `POST` | `/services/{session_id}/selection-config` | Update selection config |

### Strategy

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/strategy-config` | Get strategy config and available strategies |
| `POST` | `/services/{session_id}/strategy-config` | Replace all strategy configs |
| `POST` | `/services/{session_id}/strategy-evaluate` | Evaluate strategies against historical data |

### Portfolio

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/portfolio/config` | Get portfolio config and available optimizers |
| `POST` | `/services/{session_id}/portfolio/config` | Update portfolio config |
| `POST` | `/services/{session_id}/portfolio/optimize` | Run portfolio optimization preview |
| `GET` | `/services/{session_id}/portfolio/analysis` | Portfolio analysis snapshot |
| `GET` | `/services/{session_id}/portfolio/history` | Portfolio weight and value history |
| `POST` | `/services/{session_id}/portfolio/rebalance` | Preview or execute rebalance |

### Trading

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/services/{session_id}/close-all-positions` | Close all positions |
| `POST` | `/services/{session_id}/signal-buy` | Submit single-symbol buy signal |
| `POST` | `/services/{session_id}/signal-sell` | Submit single-symbol sell signal |

### Risk Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services/{session_id}/risk-management` | Get risk management config |
| `PUT` | `/services/{session_id}/risk-management` | Update risk management config |

## Key Response Models

| Model | Key Fields |
|-------|------------|
| `HealthResponse` | `status: str` |
| `ServiceStatusResponse` | `session_id`, `mode`, `running`, `scheduler`, `last_error`, `last_result` |
| `RuntimeSnapshotResponse` | `positions`, `oms_state` |
| `PerformanceSnapshotResponse` | `summary`, `holding_returns`, `turnover`, `equity_curve`, `trade_activity`, `position_exposure`, `latest_portfolio` |
| `AnalyticsSnapshotResponse` | `session_id`, `generated_at`, `status`, `runtime`, `performance`, `config` |
| `ServiceConfigResponse` | `session_id`, `config_bundle`, `config_source`, `persisted_user_config_available` |
| `TradingCycleResultResponse` | `session_id`, `cycle_time`, `selection_count`, `status`, `error` |
| `StrategyConfigSnapshotResponse` | `strategy_specs`, `available_strategies` |
| `SelectionConfigSnapshotResponse` | `selection_spec`, `active_selection_config`, `available_selections` |
| `PortfolioConfigSnapshotResponse` | `portfolio_spec`, `available_optimizers` |
| `PortfolioOptimizeResponse` | `status`, `optimizer`, `as_of_date`, `symbols`, `weights`, `diagnostics`, `preview_only` |
| `PortfolioRebalanceResponse` | `should_rebalance`, `reason`, `execution_path`, `target_allocations`, `buy_orders`, `sell_orders` |
| `PortfolioAnalysisResponse` | `portfolio_spec`, `current_portfolio`, `drift`, `latest_optimization`, `latest_rebalance` |
| `PortfolioHistoryResponse` | `weight_history`, `portfolio_value_history` |
| `SchedulerConfigSnapshotResponse` | `running`, `auto_start`, `scheduler` |
| `ServiceListResponse` | `services: ServiceInfoResponse[]`, `count`, `max_services` |
| `ServiceComparisonResponse` | `generated_at`, `count`, `services: ComparisonSummary[]` |
| `PerformanceComparisonResponse` | `generated_at`, `count`, `sessions: PerformanceComparisonItem[]` |

## Query Parameters

| Endpoint | Parameter | Type | Description |
|----------|-----------|------|-------------|
| `/services/performance/compare` | `session_ids` | string | Comma-separated session IDs (optional) |
| `/services/performance/compare` | `limit` | int | Max sessions to return (default 8) |
