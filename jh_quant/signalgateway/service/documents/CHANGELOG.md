# SignalGateway Service API Changelog

## v2 (2026-04-29)

### New Features

#### Multi-Service Manager
- Added `MultiServiceManager` class that orchestrates multiple `SignalGatewayService` instances in a single process.
- Each service gets its own `MockOMS` (isolated by `session_id`), scheduler thread, and config.
- Services share a single `PersistenceCoordinator` and `MarketDataProvider` for efficiency.
- Configurable max services limit (default 4).
- Entry point: set `SIGNALGATEWAY_MULTI_SERVICE=1` env var in `run_signalgateway.py`.

#### Multi-Service API Endpoints
All new endpoints are namespaced under `/services/`:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services` | List all managed service instances |
| `POST` | `/services` | Create a new service from config |
| `DELETE` | `/services/{session_id}` | Stop and remove a service |
| `GET` | `/services/{session_id}/status` | Service status for a specific session |
| `POST` | `/services/{session_id}/scheduler/start` | Start scheduler for a session |
| `POST` | `/services/{session_id}/scheduler/stop` | Stop scheduler for a session |
| `POST` | `/services/{session_id}/run-once` | Execute one cycle for a session |
| `GET` | `/services/{session_id}/performance` | Performance report for a session |
| `GET` | `/services/{session_id}/runtime` | Runtime snapshot for a session |
| `GET` | `/services/{session_id}/config` | Config snapshot for a session |
| `GET` | `/services/compare` | Side-by-side status comparison across sessions |
| `GET` | `/services/performance/compare` | Historical performance comparison with equity curves |

#### Performance Comparison Endpoint
- `GET /services/performance/compare?session_ids=A,B&limit=8`
- Returns per-session performance summaries + full equity curve time-series data for chart overlay.
- When `session_ids` is omitted and total sessions exceed `limit` (default 8), returns only the latest N sessions with an informative `note` field.
- Each session item includes: `equity_curve` (daily portfolio_value, cumulative_return, drawdown), `total_trades`, `win_rate`, `total_pnl`, `max_drawdown`, and current snapshot data.

#### New Response Models
- `ServiceInfoResponse` — per-service metadata
- `ServiceListResponse` — all services summary
- `ServiceCreateRequest` / `ServiceCreateResponse` — service creation
- `ServiceRemoveResponse` — service removal
- `ServiceComparisonResponse` / `ComparisonSummary` — live status comparison
- `PerformanceComparisonResponse` / `PerformanceComparisonItem` — historical performance comparison with equity curves

### Behavior Changes
- `SignalGatewayService.shutdown_service()` no longer closes the shared `PersistenceCoordinator`. Persistence lifecycle is managed by `MultiServiceManager.stop_all()`.
- `run_service_app()` now accepts an optional `manager` parameter for multi-service mode.

### Backward Compatibility
- All v1 single-service endpoints (`/health`, `/service/*`, `/data/*`) remain available and unchanged.
- `create_service_app(service)` and `run_service_app(service=...)` continue to work for single-service mode.
- `run_signalgateway.py` defaults to single-service mode unless `SIGNALGATEWAY_MULTI_SERVICE=1`.

### Migration Guide
**Single-service users**: No changes needed. Your existing code and API calls continue to work.

**To enable multi-service mode**:
```python
# Old (v1)
run_service_app(service=my_service, host=host, port=port)

# New (v2)
manager = MultiServiceManager(max_services=4, persistence=..., market_data_provider=...)
manager.create_service(config=config_a, initial_capital=100000)
manager.create_service(config=config_b, initial_capital=100000)
run_service_app(manager=manager, host=host, port=port)
```

---

## v1 (initial)

- Single-service `SignalGatewayService` with FastAPI HTTP control plane.
- Endpoints: health, status, runtime, performance, analytics, config, scheduler, selection, strategy, portfolio, trading operations.
- Schema-driven configuration for selection providers, strategies, and portfolio optimizers.
- Cron-based or interval-based scheduler.
- Persistence via SQLite/Postgres through Tortoise ORM.
