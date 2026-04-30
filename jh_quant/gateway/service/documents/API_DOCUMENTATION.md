# SignalGateway Service API Documentation v4

Document version: `v4` (changelog: [CHANGELOG.md](CHANGELOG.md))

This document describes the HTTP API exposed by `jh_quant.signalgateway.service.api`, the key data models, and recommended frontend integration patterns.

## 1. Basics

- Default base URL: `http://127.0.0.1:8000`
- Protocol: HTTP + JSON
- CORS: Enabled, allows any origin (`*`)
- Timestamps: ISO 8601 strings
- Code entry point: [api.py](../../../service/api.py)
- Response models: [schemas.py](../../../service/schemas.py)

## 2. Core Integration Principles

### 2.1 Schema-Driven Configuration

Do not hardcode `selection / strategy / portfolio` parameters in the frontend. The recommended flow:

1. Call the GET config endpoints:
   - `GET /sessions/{session_id}/selection-config`
   - `GET /sessions/{session_id}/strategy-config`
   - `GET /sessions/{session_id}/portfolio/config`
2. Extract configurable definitions from:
   - `available_selections[].params_schema`
   - `available_strategies[].params_schema`
   - `available_optimizers[].params_schema`
3. Dynamically render forms based on `params_schema`.

### 2.2 Config Precedence

The service supports both bootstrap config and persisted user config:

1. **Bootstrap config** — initial config passed when constructing `SignalGatewayService`.
2. **Persisted user config** — config persisted to database after API modifications.
3. **Current running config** — the actual effective config.

Use `GET /sessions/{session_id}/config` to inspect:
- `config_source`
- `persisted_user_config_available`
- `persisted_user_config_updated_at`

Always treat the API-returned current config as authoritative, not local defaults.

### 2.3 Recommended Initial Load Sequence

Parallel requests on frontend init:
1. `GET /health`
2. `GET /sessions/{session_id}/status`
3. `GET /sessions/{session_id}/runtime`
4. `GET /sessions/{session_id}/performance`
5. `GET /sessions/{session_id}/config`
6. `GET /sessions/{session_id}/selection-config`
7. `GET /sessions/{session_id}/strategy-config`
8. `GET /sessions/{session_id}/portfolio/config`

To reduce requests, use `GET /sessions/{session_id}/analytics` which bundles `status`, `runtime`, `performance`, and `config`. However it does not include `available_selections / available_strategies / available_optimizers`, so config pages still need requests 6/7/8.

## 3. Endpoint Overview

### App-Level

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/sessions` | List all sessions with performance overview |
| `POST` | `/sessions` | Create a new session |
| `GET` | `/sessions/trends` | Multi-session trend data for chart overlay |

### Data Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/data/index/{symbol}` | Get OHLCV data for a single index |
| `GET` | `/data/stock` | Get OHLCV data for one or more stocks |

### Session-Scoped

| Method | Path | Description |
|--------|------|-------------|
| `DELETE` | `/sessions/{session_id}` | Remove a session |
| `GET` | `/sessions/{session_id}/status` | Session status |
| `GET` | `/sessions/{session_id}/runtime` | Runtime snapshot |
| `GET` | `/sessions/{session_id}/performance` | Performance snapshot |
| `GET` | `/sessions/{session_id}/analytics` | Aggregated analytics snapshot |
| `GET` | `/sessions/{session_id}/config` | Full config snapshot |
| `PUT` | `/sessions/{session_id}/config` | Replace full config |
| `POST` | `/sessions/{session_id}/config/import` | Import config from uploaded file |
| `GET` | `/sessions/{session_id}/config/export` | Export config as downloadable file |
| `GET` | `/sessions/{session_id}/events` | Session event history |
| `POST` | `/sessions/{session_id}/scheduler/start` | Start scheduler |
| `POST` | `/sessions/{session_id}/scheduler/stop` | Stop scheduler |
| `POST` | `/sessions/{session_id}/run-once` | Execute one cycle immediately |
| `GET` | `/sessions/{session_id}/strategy-config` | Get strategy config and available strategies |
| `POST` | `/sessions/{session_id}/strategy-config` | Replace all strategy configs |
| `GET` | `/sessions/{session_id}/selection-config` | Get selection config and available selectors |
| `POST` | `/sessions/{session_id}/selection-config` | Update selection config |
| `GET` | `/sessions/{session_id}/portfolio/config` | Get portfolio config and available optimizers |
| `POST` | `/sessions/{session_id}/portfolio/config` | Update portfolio config |
| `POST` | `/sessions/{session_id}/portfolio/optimize` | Portfolio optimization preview |
| `GET` | `/sessions/{session_id}/portfolio/analysis` | Portfolio analysis snapshot |
| `GET` | `/sessions/{session_id}/portfolio/history` | Portfolio history |
| `POST` | `/sessions/{session_id}/portfolio/rebalance` | Preview or execute rebalance |
| `GET` | `/sessions/{session_id}/scheduler-config` | Get scheduler config |
| `POST` | `/sessions/{session_id}/scheduler-config` | Update scheduler config |
| `POST` | `/sessions/{session_id}/close-all-positions` | Close all positions |
| `POST` | `/sessions/{session_id}/signal-buy` | Single-symbol buy signal |
| `POST` | `/sessions/{session_id}/signal-sell` | Single-symbol sell signal |

## 4. Common Response and Error Handling

### 4.1 Success Responses

All endpoints return JSON.

### 4.2 Error Handling

The API does not use a unified custom error model. Errors manifest as non-2xx HTTP status with text error messages.

Recommended frontend wrapper:

```ts
async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(`${apiBase}${path}`, options)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  return response.json()
}
```

## 5. Status Endpoints

### 5.1 `GET /health`

Health check.

Response:
```json
{ "status": "ok" }
```

Use for: status indicator, connectivity check.

### 5.2 `GET /sessions/{session_id}/status`

Session status and scheduler state.

Key fields: `session_id`, `mode`, `running`, `scheduler`, `last_error`, `last_result`.

Response:
```json
{
  "session_id": "sg-paper-001",
  "mode": "paper",
  "running": true,
  "scheduler": {
    "interval_seconds": 300,
    "cron_expression": "0 15 * * 1-5",
    "timezone": "Asia/Shanghai",
    "schedule_type": "cron",
    "next_run_at": "2026-04-28T15:00:00+08:00",
    "next_run_in_seconds": 502.4,
    "next_runs": [
      "2026-04-28T15:00:00+08:00",
      "2026-04-29T15:00:00+08:00"
    ]
  },
  "last_error": null,
  "last_result": null
}
```

### 5.3 `GET /sessions/{session_id}/runtime`

Runtime snapshot.

Key fields: `positions`, `oms_state`.

- `positions` — holdings, pending orders, current state panel.
- `oms_state` — debugging and diagnostics.

### 5.4 `GET /sessions/{session_id}/performance`

Performance metrics, return curves, turnover, position exposure.

Key fields: `summary`, `holding_returns`, `turnover`, `equity_curve`, `trade_activity`, `position_exposure`, `latest_portfolio`.

Use for: performance charts, holding returns, exposure analysis.

### 5.5 `GET /sessions/{session_id}/analytics`

Aggregated snapshot (bundles status, runtime, performance, config).

Response structure:
```json
{
  "session_id": "sg-paper-001",
  "generated_at": "2026-04-28T13:00:00+08:00",
  "status": {},
  "runtime": {},
  "performance": {},
  "config": {}
}
```

Use for: overview page initial load, diagnostics panel.

## 6. Config Endpoints

### 6.1 `GET /sessions/{session_id}/config`

Get full config snapshot.

Key fields: `config_bundle`, `service`, `selection_spec`, `selection_provider`, `strategy_specs`, `portfolio_spec`, `config_source`, `persisted_user_config_available`, `persisted_user_config_updated_at`.

Response:
```json
{
  "session_id": "sg-paper-001",
  "config_bundle": {
    "service": {
      "session_id": "sg-paper-001",
      "mode": "paper",
      "price_lookback_days": 180,
      "max_candidates": 10,
      "auto_start": false,
      "frequency": "daily",
      "price_slippage": 0.0,
      "interval_seconds": 300,
      "cron_expression": null,
      "timezone": "Asia/Shanghai",
      "restore_persisted_state": true
    },
    "selection_spec": {
      "name": "factor_selector",
      "alias": "Monthly Factor Selection",
      "params": {
        "factor": "momentum",
        "start": "2020-01-01",
        "top_n": 100,
        "bottom_n": 100,
        "period": "M"
      }
    },
    "strategy_specs": [],
    "portfolio_spec": {
      "enabled": false,
      "optimizer": "riskfolio",
      "objective": "Sharpe",
      "risk_measure": "MV",
      "model": "Classic",
      "covariance_method": "ledoit"
    }
  },
  "service": {},
  "selection_spec": {},
  "selection_provider": {},
  "strategy_specs": [],
  "portfolio_spec": {},
  "config_source": "persisted_user_config",
  "persisted_user_config_available": true,
  "persisted_user_config_updated_at": "2026-04-28T12:31:00+08:00"
}
```

Frontend tips:
- Display `config_source` on overview page.
- Always initialize settings forms from this response.

### 6.2 `PUT /sessions/{session_id}/config`

Replace the entire config.

Request body:
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

Suitable for: "import full config", "advanced mode one-click replace". Not recommended for routine settings changes — use the individual endpoints below instead.

### 6.3 `POST /sessions/{session_id}/config/import`

Import config from an uploaded JSON file.

Request: `multipart/form-data` with file field `file`.

Response: `ServiceConfigUpdateResponse`.

### 6.4 `GET /sessions/{session_id}/config/export`

Export current config as a downloadable JSON file.

Response: `application/json` file download.

## 7. Scheduler Endpoints

### 7.1 `POST /sessions/{session_id}/scheduler/start`

Start the scheduler thread.

Response:
```json
{ "status": "started", "session_id": "sg-paper-001" }
```

### 7.2 `POST /sessions/{session_id}/scheduler/stop`

Stop the scheduler thread.

### 7.3 `POST /sessions/{session_id}/run-once`

Execute one trading cycle immediately.

Response:
```json
{
  "session_id": "sg-paper-001",
  "mode": "paper",
  "cycle_time": "2026-04-28T13:02:00+08:00",
  "selection_count": 100,
  "long_candidate_count": 12,
  "short_candidate_count": 5,
  "executed_buy_count": 3,
  "executed_sell_count": 1,
  "selected_symbols": ["000001", "600519"],
  "long_symbols": ["000001"],
  "short_symbols": ["600519"],
  "status": "success",
  "error": null
}
```

### 7.4 `GET /sessions/{session_id}/scheduler-config`

Get current scheduler configuration.

Response fields: `running`, `auto_start`, `scheduler`.

### 7.5 `POST /sessions/{session_id}/scheduler-config`

Update scheduler configuration.

Request body (all fields optional):
```json
{
  "interval_seconds": 300,
  "cron_expression": "0 15 * * 1-5",
  "timezone": "Asia/Shanghai",
  "auto_start": true
}
```

- `interval_seconds >= 1`
- `cron_expression` can be `null`

Frontend tip: keep scheduler settings as a separate section from selection/strategy/portfolio params.

## 8. Selection Endpoints

### 8.1 `GET /sessions/{session_id}/selection-config`

Get current selection config and all available selection providers.

Response fields: `selection_spec`, `active_selection_config`, `available_selections`.

Response:
```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "Monthly Momentum",
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
  },
  "active_selection_config": {
    "factor": "momentum",
    "start": "2020-01-01"
  },
  "available_selections": [
    {
      "name": "factor_selector",
      "params_schema": { "type": "object", "properties": {} },
      "runtime_dependencies": ["jh_data"]
    }
  ]
}
```

Frontend focus:
- Use `available_selections` to render available selection providers.
- Use `params_schema` to dynamically render parameter forms.
- `runtime_dependencies` is display-only.

### 8.2 `POST /sessions/{session_id}/selection-config`

Update selection config.

Request body:
```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "Monthly Momentum",
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

Built-in selectors: `factor_selector`.

Common `factor_selector` params: `factor`, `start`, `top_n`, `bottom_n`, `factor_alpha`, `default_weight`, `period`, `insignificant_weight_ratio`, `missing_data_threshold`, `test_window`, `verbose`.

## 9. Strategy Endpoints

### 9.1 `GET /sessions/{session_id}/strategy-config`

Get current strategy config and all available strategies.

Response fields: `strategy_specs`, `available_strategies`.

### 9.2 `POST /sessions/{session_id}/strategy-config`

Replace all strategy configs (not append).

Request body:
```json
{
  "strategy_specs": [
    {
      "name": "moving_average_crossover",
      "weight": 1,
      "alias": "MA Crossover",
      "params": { "short_window": 20, "long_window": 60 }
    },
    {
      "name": "rsi",
      "weight": 0.8,
      "alias": "RSI Strategy",
      "params": {
        "rsi_window": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "rsi_exit_oversold": 50,
        "rsi_exit_overbought": 50
      }
    }
  ]
}
```

Built-in strategies: `turtle`, `moving_average_crossover`, `buy_and_hold`, `volume_trend`, `volume_divergence`, `mean_reversion`, `rsi`, `bollinger_bands`, `momentum`, `breakout`, `dual_thrust`.

Always use `available_strategies[].params_schema` as the authoritative parameter structure.

## 10. Portfolio Endpoints

### 10.1 `GET /sessions/{session_id}/portfolio/config`

Get current portfolio config and available optimizers.

Response fields: `portfolio_spec`, `available_optimizers`.

Default optimizer: `riskfolio`.

### 10.2 `POST /sessions/{session_id}/portfolio/config`

Update portfolio config.

Request body:
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

Fields suitable for preset dropdowns: `objective`, `risk_measure`, `model`, `covariance_method`, `rebalance_policy.mode`. Always defer to schema and server validation.

### 10.3 `POST /sessions/{session_id}/portfolio/optimize`

Run portfolio optimization preview.

Request body:
```json
{
  "as_of_date": "2026-04-28",
  "preview_only": true,
  "symbols": ["000001", "600519"]
}
```

Response fields: `status`, `optimizer`, `as_of_date`, `symbols`, `weights`, `diagnostics`, `preview_only`.

### 10.4 `GET /sessions/{session_id}/portfolio/analysis`

Portfolio analysis snapshot.

Response fields: `portfolio_spec`, `current_portfolio`, `drift`, `latest_optimization`, `latest_rebalance`.

### 10.5 `GET /sessions/{session_id}/portfolio/history`

Portfolio history.

Response fields: `weight_history`, `portfolio_value_history`.

### 10.6 `POST /sessions/{session_id}/portfolio/rebalance`

Preview or execute portfolio rebalancing.

Request body:
```json
{
  "as_of_date": "2026-04-28",
  "preview_only": true,
  "symbols": ["000001", "600519"],
  "force": false
}
```

Key response fields: `should_rebalance`, `reason`, `execution_path`, `target_allocations`, `buy_orders`, `sell_orders`, `blocked_buy_orders`, `blocked_sell_orders`, `projected_buy_cost`, `projected_sell_value`, `projected_cash_after`, `drift`, `executed_buy_count`, `executed_sell_count`.

Frontend tip: default to `preview_only=true`, let users confirm before executing.

## 11. Trading Endpoints

### 11.1 `POST /sessions/{session_id}/close-all-positions`

Close all positions.

Request body:
```json
{ "slippage": 0.001 }
```

Response fields: `status`, `closed_count`, `executed_trades`.

### 11.2 `POST /sessions/{session_id}/signal-buy`

Submit single-symbol buy signal.

Request body:
```json
{ "symbol": "600519", "target_qty": 100, "slippage": 0.001 }
```

### 11.3 `POST /sessions/{session_id}/signal-sell`

Submit single-symbol sell signal. Same request format as buy.

Single-symbol trade response fields: `status`, `action`, `symbol`, `executed`, `trade`, `message`.

## 12. Event History

### 12.1 `GET /sessions/{session_id}/events`

Session event history.

Response fields: `session_id`, `count`, `events`.

Each event: `event_type`, `event_time`, `export_time`, `state_data`.

Use for: audit timeline, state recovery debugging, config change history.

## 13. Multi-Session Endpoints

### 13.1 `GET /sessions`

List all sessions with performance overview for dashboard cards.

Response fields: `sessions: SessionInfoResponse[]`, `count: number`, `max_sessions: number`.

`SessionInfoResponse`: `session_id`, `mode`, `running`, `strategy_count`, `strategy_names`, `selection_name`, `portfolio_enabled`, `initial_capital`, `current_value`, `total_return_pct`, `daily_pnl`, `position_count`, `max_drawdown`, `win_rate`, `total_trades`, `total_pnl`, `last_error`, `last_result`.

### 13.2 `POST /sessions`

Create a new session.

Request body:
```json
{
  "config_bundle": {
    "session": {},
    "selection_spec": null,
    "strategy_specs": [],
    "portfolio_spec": {}
  },
  "initial_capital": 100000
}
```

Response: `{ "status": "created", "session_id": "..." }`

### 13.3 `DELETE /sessions/{session_id}`

Remove a session. Response: `{ "status": "removed", "session_id": "..." }`

### 13.4 `GET /sessions/trends`

Multi-session trend data for chart overlay. Returns per-session time-series of equity, returns, drawdown, and positions.

Query params: `session_ids` (optional, comma-separated), `limit` (default 8), `days` (optional, limit history to last N days).

Response fields: `generated_at`, `count`, `note` (when auto-limited), `sessions: SessionTrendItem[]`.

`SessionTrendItem`: `session_id`, `mode`, `initial_capital`, `strategy_names`, `selection_name`, `trends: SessionTrendPoint[]`.

`SessionTrendPoint`: `trade_date`, `portfolio_value`, `cumulative_return`, `drawdown`, `daily_pnl`, `num_positions`.

When `session_ids` is omitted and total sessions exceed `limit`, only the latest N are returned with an informative `note`.

Chart overlay example:
```ts
const { sessions } = await fetch('/sessions/trends?limit=8').then(r => r.json())
const series = sessions.map(s => ({
  name: `${s.session_id} (${s.strategy_names.join(', ')})`,
  type: 'line',
  data: s.trends.map(p => [p.trade_date, p.cumulative_return]),
}))
```

## 14. Data Endpoints

### 14.1 `GET /data/index/{symbol}`

Get OHLCV time-series data for a single market index (e.g., `000001.SH` for Shanghai Composite).

Path parameters:
- `symbol` (string, required) — Index code, e.g. `000001.SH`, `399001.SZ`, `000300.SH`

Query parameters:
- `start_date` (string, optional) — Start date in `YYYY-MM-DD` format. Default: `2020-01-01`
- `end_date` (string, optional) — End date in `YYYY-MM-DD` format. Default: today

Response (`DataListResponse`):
```json
{
  "data": [
    {
      "symbol": "000001.SH",
      "date": "2026-04-29",
      "open": 3312.55,
      "high": 3341.78,
      "low": 3308.12,
      "close": 3336.94,
      "volume": 385412000,
      "amount": 412568000000,
      "chg": 0.52
    }
  ],
  "count": 1
}
```

Each record includes `chg` (change rate %) computed from `close` price change when the upstream data source omits it.

### 14.2 `GET /data/stock`

Get OHLCV time-series data for one or more stocks.

Query parameters:
- `symbols` (string, required) — Comma-separated stock symbols, e.g. `000001,600519`
- `start_date` (string, optional) — Start date in `YYYY-MM-DD` format. Default: `2020-01-01`
- `end_date` (string, optional) — End date in `YYYY-MM-DD` format. Default: today
- `frequency` (string, optional) — Data frequency: `daily` (default) or `spot`

Response (`DataListResponse`):
```json
{
  "data": [
    {
      "symbol": "000001",
      "date": "2026-04-29",
      "open": 12.35,
      "high": 12.68,
      "low": 12.28,
      "close": 12.55,
      "volume": 45230000,
      "amount": 567891000,
      "chg": null
    }
  ],
  "count": 1
}
```

Results are sorted by `symbol` then `date`. The `chg` field is always `null` for stock data.

## 15. Key Config Models

### 15.1 `ServiceConfig`

Fields: `session_id`, `mode` (`paper | live`), `price_lookback_days`, `max_candidates`, `auto_start`, `frequency`, `price_slippage`, `interval_seconds`, `cron_expression`, `timezone`, `restore_persisted_state`.

### 15.2 `SelectionSpec`

Fields: `name`, `params`, `alias`.

### 15.3 `StrategySpec`

Fields: `name`, `weight`, `params`, `alias`.

### 15.4 `PortfolioSpec`

Fields: `enabled`, `optimizer`, `objective`, `risk_measure`, `model`, `covariance_method`, `historical_lookback_days`, `max_assets`, `min_weight`, `max_weight`, `weight_epsilon`, `cash_reserve_ratio`, `lot_size`, `allow_partial_rebalance`, `rebalance_policy`, `analysis`.

### 15.5 `RebalancePolicySpec`

Fields: `mode` (`disabled`, `initial_only`, `every_cycle`, `drift_threshold`, `schedule`, `manual_only`), `drift_threshold`, `min_rebalance_interval_seconds`, `schedule_cron`, `on_selection_change`, `on_strategy_change`.

### 15.6 `PortfolioAnalysisSpec`

Fields: `enabled`, `benchmark_symbol`, `risk_free_rate`, `rolling_window`.

## 16. Recommended Frontend Page Structure

Split settings into five sections:

1. **Connection** — local frontend settings (`apiBase`, refresh interval).
2. **Service** — `GET/POST /sessions/{session_id}/scheduler-config`.
3. **Selection** — `GET/POST /sessions/{session_id}/selection-config`.
4. **Strategy** — `GET/POST /sessions/{session_id}/strategy-config`.
5. **Portfolio** — `GET/POST /sessions/{session_id}/portfolio/config` plus `optimize/rebalance/analysis/history`.

## 17. Recommended Frontend State Structure

```ts
type DashboardState = {
  health: any
  status: any
  runtime: any
  performance: any
  config: any
  selectionConfig: any
  strategyConfig: any
  portfolioConfig: any
}
```

Keep read-only snapshots, user edit forms, and dynamic schema definitions in separate state slices.

## 18. Recommended Integration Workflows

### 18.1 Initial Load

1. Check `GET /health`
2. Fetch `GET /sessions/{session_id}/analytics`
3. Fetch three config definition endpoints
4. Initialize forms from returned data

### 18.2 Save Selection Config

1. Find selected provider from `available_selections`
2. Render parameter form from `params_schema`
3. Assemble `selection_spec`
4. Submit `POST /sessions/{session_id}/selection-config`
5. On success, re-fetch `GET /sessions/{session_id}/config` and `GET /sessions/{session_id}/selection-config`

### 18.3 Save Strategy Config

1. Maintain complete `strategy_specs[]` array in frontend state
2. Submit `POST /sessions/{session_id}/strategy-config`
3. Re-fetch `GET /sessions/{session_id}/strategy-config`

### 18.4 Save Portfolio Config

1. Generate form from `available_optimizers[0].params_schema`
2. Submit `POST /sessions/{session_id}/portfolio/config`
3. For preview: `POST /sessions/{session_id}/portfolio/optimize`
4. For rebalance preview: `POST /sessions/{session_id}/portfolio/rebalance`

### 18.5 Multi-Session Initial Load

1. `GET /health`
2. `GET /sessions` — list all sessions with performance overview
3. `GET /sessions/trends` — multi-session trend data for charting

### 18.6 Multi-Session State

```ts
type MultiSessionState = {
  sessions: SessionInfoResponse[]
  trends: SessionTrendsResponse
}
```

## 19. Implementation Notes

### 19.1 `POST /sessions/{session_id}/strategy-config` is a replacement

It replaces the entire strategies list. Do not treat individual POSTs as appends. Maintain the full array in frontend state.

### 19.2 `params_schema` is authoritative

For selection params, strategy params, and portfolio params, always defer to `params_schema`. Frontend presets enhance UX but should not override schema-driven rendering.

### 19.3 `active_selection_config` vs `selection_spec.params`

- `selection_spec.params` — user input config.
- `active_selection_config` — runtime-resolved config.

Display both, but edit against `selection_spec.params`.

### 19.4 Full config replacement caution

`PUT /sessions/{session_id}/config` replaces everything. It's an advanced operation — do not expose as a frequent button to regular users.

## 20. Document Maintenance

Document path: [API_DOCUMENTATION.md](API_DOCUMENTATION.md)

Index: [index.md](index.md)

Update this document when:
- API routes are added or removed
- Request/response model fields change
- New configurable components are added to the registry
- Config precedence or persistence logic changes
- Multi-session management features change

## 21. Running the Service

Set environment variables in `run_signalgateway.py`:

```bash
# Launch HTTP server
export SIGNALGATEWAY_RUN_SERVER=1

# Enable multi-service mode
export SIGNALGATEWAY_MULTI_SERVICE=1

# Auto-start scheduler on launch
export SIGNALGATEWAY_AUTO_START=1

# Custom host/port
export SIGNALGATEWAY_HOST=127.0.0.1
export SIGNALGATEWAY_PORT=8000

python run_signalgateway.py
```

Python usage:

```python
from jh_quant.signalgateway import (
    JHMarketDataProvider,
    MockOMS,
    MultiServiceManager,
    PersistenceCoordinator,
    SignalGateway,
    SignalGatewayService,
    SQLiteOrderRecorder,
    run_service_app,
)

# Single service
recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
persistence = PersistenceCoordinator(recorder=recorder)
gateway = SignalGateway(oms=MockOMS(session_id="S1", initial_capital=100000),
                        market_data_provider=JHMarketDataProvider())
service = SignalGatewayService(gateway=gateway, config=config, persistence=persistence)
run_service_app(service=service, host="127.0.0.1", port=8000)

# Multi service
manager = MultiServiceManager(
    max_services=4,
    persistence=persistence,
    market_data_provider=JHMarketDataProvider(),
)
manager.create_service(config=config_a, initial_capital=100000)
manager.create_service(config=config_b, initial_capital=100000)
run_service_app(manager=manager, host="127.0.0.1", port=8000)
```
