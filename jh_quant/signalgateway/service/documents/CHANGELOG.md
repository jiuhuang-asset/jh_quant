# SignalGateway Service API Changelog

## v3 (2026-04-29)

### Breaking Changes

#### Unified API Architecture
- All service endpoints moved from `/service/*` to `/services/{session_id}/*`.
- Single-service mode now uses `MultiServiceManager` internally — every service is managed by session ID.
- `create_service_app(service)` wraps the service into a `MultiServiceManager(max_services=1)` and delegates to `create_unified_app(manager)`.
- `run_service_app()` always uses the unified app internally. The old dual-track routing is removed.

#### New Endpoints Added
- `PUT /services/{session_id}/config` — full config replacement (was missing from v2 multi-service routes)
- `POST /services/{session_id}/config/import` — import config from uploaded JSON file
- `GET /services/{session_id}/config/export` — export config as downloadable JSON file
- `POST /services/{session_id}/strategy-evaluate` — evaluate strategies against historical data
- `GET /services/{session_id}/risk-management` — get risk management config
- `PUT /services/{session_id}/risk-management` — update risk management config
- `GET /data/types` — list available data types
- `GET /data/schema/{data_type}` — get schema for a data type
- `POST /data/count` — count records for a data type
- `POST /data/query` — query data with filters

#### Removed Paths
All legacy `/service/*` paths are removed:
- `/service/status` → `/services/{session_id}/status`
- `/service/runtime` → `/services/{session_id}/runtime`
- `/service/performance` → `/services/{session_id}/performance`
- `/service/analytics` → `/services/{session_id}/analytics`
- `/service/config` → `/services/{session_id}/config`
- `/service/events` → `/services/{session_id}/events`
- `/service/scheduler/start` → `/services/{session_id}/scheduler/start`
- `/service/scheduler/stop` → `/services/{session_id}/scheduler/stop`
- `/service/run-once` → `/services/{session_id}/run-once`
- `/service/strategy-config` → `/services/{session_id}/strategy-config`
- `/service/selection-config` → `/services/{session_id}/selection-config`
- `/service/portfolio/config` → `/services/{session_id}/portfolio/config`
- `/service/portfolio/optimize` → `/services/{session_id}/portfolio/optimize`
- `/service/portfolio/analysis` → `/services/{session_id}/portfolio/analysis`
- `/service/portfolio/history` → `/services/{session_id}/portfolio/history`
- `/service/portfolio/rebalance` → `/services/{session_id}/portfolio/rebalance`
- `/service/scheduler-config` → `/services/{session_id}/scheduler-config`
- `/service/close-all-positions` → `/services/{session_id}/close-all-positions`
- `/service/signal-buy` → `/services/{session_id}/signal-buy`
- `/service/signal-sell` → `/services/{session_id}/signal-sell`

#### Config I/O Module
- New `jh_quant.signalgateway.config.io` module with `export_config_to_file()`, `export_config_to_json_string()`, `import_config_from_file()`, `import_config_from_dict()`.

### Migration Guide

**Old (v2):**
```python
from jh_quant.signalgateway.service import create_service_app, run_service_app

app = create_service_app(service)
run_service_app(service=service, host=host, port=port)
```

**Old API calls (v2):**
```
GET /service/status
POST /service/scheduler/start
```

**New (v3):**
```python
# Same Python API — no code changes needed
app = create_service_app(service)  # still works, uses manager internally
run_service_app(service=service, host=host, port=port)
```

**New API calls (v3):**
```
GET /services/{session_id}/status
POST /services/{session_id}/scheduler/start
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
