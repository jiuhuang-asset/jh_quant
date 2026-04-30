# SignalGateway Service API Changelog

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
