# SignalGateway Service API Changelog

## v7 (2026-05-05)

### Breaking Changes

#### Unified `total_return` field naming
- **`SessionInfoResponse.total_return_pct` → `total_return`**: The field is now a raw float ratio (e.g., `0.15` = 15%) instead of a pre-formatted percentage string. Frontend should handle formatting (multiply by 100 and append `%`).
- **`SessionTrendPoint.cumulative_return` → `total_return`**: Renamed for consistency with `SessionInfoResponse` and performance summary. Same raw float ratio format.
- **`PerformanceSnapshotResponse.summary.total_return`**: Unchanged (was already a raw float ratio).

#### Calculation logic consolidation
- `_build_session_info()` no longer calculates `total_return` independently from live OMS portfolio value. Instead, it reuses `summary["total_return"]` from the performance report (`get_performance_report()` → `build_performance_report()`), ensuring all endpoints report the same metric.
- Equity curve column `cumulative_return` renamed to `total_return` in `performance.py` for consistent naming across the entire stack.

### Migration Guide (v6 → v7)

**Frontend changes required:**
```ts
// Old (v6)
sessionInfo.total_return_pct  // pre-formatted, e.g. 12.5 (meaning 12.5%)
trendPoint.cumulative_return  // raw ratio

// New (v7)
sessionInfo.total_return      // raw ratio, e.g. 0.125
trendPoint.total_return       // raw ratio, e.g. 0.125

// Format for display:
const pct = (value * 100).toFixed(2) + '%'
```

---

## v6 (2026-05-03)

### New Features

#### Trade & Position Endpoints
- `GET /sessions/{session_id}/trades` — query historical trade records for a session. Optional query params: `symbol` (filter by ticker), `limit` (max records).
- `GET /sessions/{session_id}/positions` — current position details with `avg_cost`, `entry_time` (first establishment time).
- `GET /sessions/{session_id}/positions/history` — historical position snapshots, optionally filtered by `symbol`.

#### New Response Models
- `TradeRecordItem` — individual trade: `trade_id`, `session_id`, `trade_date`, `symbol`, `trade_type`, `price`, `quantity`, `amount`, `commission`, `slippage`, `total_cost`, `signal_reason`, `order_id`.
- `TradeHistoryResponse` — `session_id`, `symbol` (optional filter), `count`, `trades: TradeRecordItem[]`.
- `PositionDetail` — current holding: `symbol`, `quantity`, `avg_cost`, `market_value`, `entry_time`.
- `PositionsResponse` — `session_id`, `portfolio_value`, `cash_balance`, `num_positions`, `positions: PositionDetail[]`.
- `PositionSnapshotItem` — historical snapshot: `trade_date`, `symbol`, `quantity`, `avg_cost`, `current_price`, `market_value`, `pnl`, `pnl_pct`.
- `PositionHistoryResponse` — `session_id`, `symbol` (optional filter), `count`, `snapshots: PositionSnapshotItem[]`.

#### Bug Fixes
- `_records_from_frame()` now properly converts `NaN` float values to `null` for JSON serialization.

---

## v5 (2026-04-30)

### New Features

#### Data endpoints
- `GET /data/index/{symbol}` — get OHLCV time-series for a single market index. Query params: `start_date`, `end_date`.
- `GET /data/stock` — get OHLCV time-series for one or more stocks. Query params: `symbols` (comma-separated, required), `start_date`, `end_date`, `frequency` (daily/spot).

#### New response models
- `DataListResponse` — generic wrapper with `data: List[Dict]` and `count: int`.
- `OHLCVRecord` — fields: `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`, `amount`, `chg` (index only).

#### Market data improvements
- `JHMarketDataProvider.get_index_trends()` — automatically computes `chg` (change rate %) from `close` column via `pct_change` when the upstream data source omits this field.

---

## v4 (2026-04-30)

### Breaking Changes

#### Route prefix: `/services` → `/sessions`
All collection-prefix routes changed from `/services` to `/sessions`, aligning with the codebase naming convention.

#### Consolidated overview: compare merged into list
- `GET /sessions/compare` removed — its data (session status, return, PnL, position count) is now included in `GET /sessions`.
- `GET /sessions/performance/compare` removed — replaced by `GET /sessions/trends` with a cleaner time-series model.

#### Removed endpoints
- `GET /sessions/compare` — merged into `GET /sessions`
- `GET /sessions/performance/compare` — replaced by `GET /sessions/trends`
- `POST /sessions/{session_id}/strategy-evaluate` — removed
- `GET /sessions/{session_id}/risk-management` — removed
- `PUT /sessions/{session_id}/risk-management` — removed
- `POST /data/count` — removed (data endpoints extracted to separate service)
- `POST /data/query` — removed
- `GET /data/types` — removed
- `GET /data/schema/{data_type}` — removed

#### New endpoint
- `GET /sessions/trends` — multi-session time-series data for chart overlay. Query params: `session_ids` (comma-separated, optional), `limit` (default 8), `days` (optional, limit history to last N days). Returns `SessionTrendsResponse` with per-session `SessionTrendItem[]` each containing `trends: SessionTrendPoint[]` (trade_date, portfolio_value, cumulative_return, drawdown, daily_pnl, num_positions).

#### Model changes
- **Enhanced `SessionInfoResponse`** — added `strategy_names`, `total_return_pct`, `daily_pnl`, `position_count`, `max_drawdown`, `win_rate`, `total_trades`, `total_pnl`. One call now provides everything needed for dashboard overview cards.
- **New models**: `SessionTrendPoint`, `SessionTrendItem`, `SessionTrendsResponse`
- **Removed models**: `ComparisonSummary`, `SessionComparisonResponse`, `PerformanceComparisonItem`, `PerformanceComparisonResponse`, `PerformanceComparisonRequest`

### Migration Guide

**Old (v3):**
```
GET /services                           # basic session list
GET /services/compare                   # status comparison (separate call)
GET /services/performance/compare       # performance + equity curves (separate call)
GET /services/{session_id}/risk-management
```

**New (v4):**
```
GET /sessions                         # full overview with performance metrics (one call)
GET /sessions/trends                  # multi-session trend data
```

**Frontend migration (v3 → v4):**
```ts
// Old: two requests
const [list, compare] = await Promise.all([
  fetch('/services').then(r => r.json()),
  fetch('/services/compare').then(r => r.json()),
])

// New: single request
const { sessions, count, max_sessions } = await fetch('/sessions').then(r => r.json())
// sessions[0].total_return_pct, .max_drawdown, .win_rate, etc. are now directly available

// Old: performance compare chart
const { sessions } = await fetch('/services/performance/compare?limit=8').then(r => r.json())
chart(sessions.map(s => ({ name: s.session_id, data: s.equity_curve })))

// New: trends endpoint
const { sessions } = await fetch('/sessions/trends?limit=8&days=90').then(r => r.json())
chart(sessions.map(s => ({ name: s.session_id, data: s.trends })))
```

---

## v2 (2026-04-28)

### New Features

#### Multi-Service Manager
- Added `MultiServiceManager` class orchestrating multiple `SignalGatewayService` instances.
- Each service gets its own `MockOMS` (isolated by `session_id`), scheduler thread, and config.
- Services share a single `PersistenceCoordinator` and `MarketDataProvider`.
- Configurable max services limit (default 4).

#### Performance Comparison
- `GET /services/performance/compare?session_ids=A,B&limit=8`
- Returns per-session performance summaries + equity curve time-series for chart overlay.
- Auto-limits to latest N sessions when `session_ids` is omitted.

#### New Response Models
- `ServiceInfoResponse`, `ServiceListResponse`, `ServiceCreateRequest` / `ServiceCreateResponse`
- `ServiceRemoveResponse`, `ServiceComparisonResponse`, `ComparisonSummary`
- `PerformanceComparisonResponse`, `PerformanceComparisonItem`

---

## v1 (initial)

- Single-service `SignalGatewayService` with FastAPI HTTP control plane.
- Schema-driven configuration for selection providers, strategies, and portfolio optimizers.
- Cron-based or interval-based scheduler.
- Persistence via SQLite/Postgres through Tortoise ORM.
