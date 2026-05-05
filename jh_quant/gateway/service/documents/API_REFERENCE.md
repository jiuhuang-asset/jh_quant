# SignalGateway Service API Reference (v7)

Quick endpoint reference. For full details see [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

## App-Level Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/sessions` | List all sessions with performance overview |
| `POST` | `/sessions` | Create a new session |
| `DELETE` | `/sessions/{session_id}` | Stop and remove a session |
| `GET` | `/sessions/trends` | Multi-session trend data (equity curves, drawdown, PnL) |

### Data Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/data/index/{symbol}` | Get OHLCV data for a single index |
| `GET` | `/data/stock` | Get OHLCV data for one or more stocks |

## Session-Scoped Endpoints

All under `/sessions/{session_id}/*`.

### Status & Monitoring

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/{session_id}/status` | Session status and scheduler state |
| `GET` | `/sessions/{session_id}/runtime` | Runtime snapshot (positions, OMS state) |
| `GET` | `/sessions/{session_id}/performance` | Performance metrics and equity curve |
| `GET` | `/sessions/{session_id}/analytics` | Aggregated snapshot (status + runtime + performance + config) |
| `GET` | `/sessions/{session_id}/events` | Session event history |

### Config

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/{session_id}/config` | Get full config snapshot |
| `PUT` | `/sessions/{session_id}/config` | Replace full config |
| `POST` | `/sessions/{session_id}/config/import` | Import config from uploaded JSON file |
| `GET` | `/sessions/{session_id}/config/export` | Export config as downloadable JSON |

### Scheduler

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/{session_id}/scheduler-config` | Get scheduler configuration |
| `POST` | `/sessions/{session_id}/scheduler-config` | Update scheduler configuration |
| `POST` | `/sessions/{session_id}/scheduler/start` | Start scheduler |
| `POST` | `/sessions/{session_id}/scheduler/stop` | Stop scheduler |
| `POST` | `/sessions/{session_id}/run-once` | Execute one trading cycle immediately |

### Selection

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/{session_id}/selection-config` | Get selection config and available selectors |
| `POST` | `/sessions/{session_id}/selection-config` | Update selection config |

### Strategy

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/{session_id}/strategy-config` | Get strategy config and available strategies |
| `POST` | `/sessions/{session_id}/strategy-config` | Replace all strategy configs |

### Portfolio

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/{session_id}/portfolio/config` | Get portfolio config and available optimizers |
| `POST` | `/sessions/{session_id}/portfolio/config` | Update portfolio config |
| `POST` | `/sessions/{session_id}/portfolio/optimize` | Run portfolio optimization preview |
| `GET` | `/sessions/{session_id}/portfolio/analysis` | Portfolio analysis snapshot |
| `GET` | `/sessions/{session_id}/portfolio/history` | Portfolio weight and value history |
| `POST` | `/sessions/{session_id}/portfolio/rebalance` | Preview or execute rebalance |

### Trading

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions/{session_id}/close-all-positions` | Close all positions |
| `POST` | `/sessions/{session_id}/signal-buy` | Submit single-symbol buy signal |
| `POST` | `/sessions/{session_id}/signal-sell` | Submit single-symbol sell signal |
| `GET` | `/sessions/{session_id}/trades` | Historical trade records |
| `GET` | `/sessions/{session_id}/positions` | Current position details |
| `GET` | `/sessions/{session_id}/positions/history` | Historical position snapshots |

## Key Response Models

| Model | Key Fields |
|-------|------------|
| `HealthResponse` | `status: str` |
| `DataListResponse` | `data: List[Dict]`, `count: int` |
| `OHLCVRecord` | `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`, `amount`, `chg` |
| `SessionStatusResponse` | `session_id`, `mode`, `running`, `scheduler`, `last_error`, `last_result` |
| `RuntimeSnapshotResponse` | `positions`, `oms_state` |
| `PerformanceSnapshotResponse` | `summary`, `holding_returns`, `turnover`, `equity_curve`, `trade_activity`, `position_exposure`, `latest_portfolio` |
| `AnalyticsSnapshotResponse` | `session_id`, `generated_at`, `status`, `runtime`, `performance`, `config` |
| `SessionConfigResponse` | `session_id`, `config_bundle`, `config_source`, `persisted_user_config_available` |
| `TradingCycleResultResponse` | `session_id`, `cycle_time`, `selection_count`, `status`, `error` |
| `StrategyConfigSnapshotResponse` | `strategy_specs`, `available_strategies` |
| `SelectionConfigSnapshotResponse` | `selection_spec`, `active_selection_config`, `available_selections` |
| `PortfolioConfigSnapshotResponse` | `portfolio_spec`, `available_optimizers` |
| `PortfolioOptimizeResponse` | `status`, `optimizer`, `as_of_date`, `symbols`, `weights`, `diagnostics`, `preview_only` |
| `PortfolioRebalanceResponse` | `should_rebalance`, `reason`, `execution_path`, `target_allocations`, `buy_orders`, `sell_orders` |
| `PortfolioAnalysisResponse` | `portfolio_spec`, `current_portfolio`, `drift`, `latest_optimization`, `latest_rebalance` |
| `PortfolioHistoryResponse` | `weight_history`, `portfolio_value_history` |
| `SchedulerConfigSnapshotResponse` | `running`, `auto_start`, `scheduler` |
| `SessionListResponse` | `sessions: SessionInfoResponse[]`, `count`, `max_sessions` |
| `SessionInfoResponse` | `session_id`, `mode`, `running`, `strategy_count`, `strategy_names`, `selection_name`, `portfolio_enabled`, `initial_capital`, `current_value`, `total_return`, `daily_pnl`, `position_count`, `max_drawdown`, `win_rate`, `total_trades`, `total_pnl`, `last_error`, `last_result` |
| `SessionTrendsResponse` | `generated_at`, `count`, `sessions: SessionTrendItem[]`, `note` |
| `SessionTrendItem` | `session_id`, `mode`, `initial_capital`, `strategy_names`, `selection_name`, `trends: SessionTrendPoint[]` |
| `SessionTrendPoint` | `trade_date`, `portfolio_value`, `total_return`, `drawdown`, `daily_pnl`, `num_positions` |
| `TradeRecordItem` | `trade_id`, `session_id`, `trade_date`, `symbol`, `trade_type`, `price`, `quantity`, `amount`, `commission`, `slippage`, `total_cost`, `signal_reason`, `order_id` |
| `TradeHistoryResponse` | `session_id`, `symbol`, `count`, `trades: TradeRecordItem[]` |
| `PositionDetail` | `symbol`, `quantity`, `avg_cost`, `market_value`, `entry_time` |
| `PositionsResponse` | `session_id`, `portfolio_value`, `cash_balance`, `num_positions`, `positions: PositionDetail[]` |
| `PositionSnapshotItem` | `trade_date`, `symbol`, `quantity`, `avg_cost`, `current_price`, `market_value`, `pnl`, `pnl_pct` |
| `PositionHistoryResponse` | `session_id`, `symbol`, `count`, `snapshots: PositionSnapshotItem[]` |

## Query Parameters

| Endpoint | Parameter | Type | Description |
|----------|-----------|------|-------------|
| `/sessions/trends` | `session_ids` | string | Comma-separated session IDs (optional) |
| `/sessions/trends` | `limit` | int | Max sessions to return (default 8) |
| `/sessions/trends` | `days` | int | Limit trend history to last N days (optional) |
| `/data/index/{symbol}` | `start_date` | string | Start date YYYY-MM-DD (default 2020-01-01) |
| `/data/index/{symbol}` | `end_date` | string | End date YYYY-MM-DD (default today) |
| `/data/stock` | `symbols` | string | Comma-separated stock symbols (required) |
| `/data/stock` | `start_date` | string | Start date YYYY-MM-DD (default 2020-01-01) |
| `/data/stock` | `end_date` | string | End date YYYY-MM-DD (default today) |
| `/data/stock` | `frequency` | string | Data frequency: `daily` (default) or `spot` |
| `/sessions/{session_id}/trades` | `symbol` | string | Filter by ticker symbol (optional) |
| `/sessions/{session_id}/trades` | `limit` | int | Max records to return (optional) |
| `/sessions/{session_id}/positions/history` | `symbol` | string | Filter by ticker symbol (optional) |
