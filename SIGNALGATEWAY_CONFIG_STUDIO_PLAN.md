# SignalGateway Config Studio Plan

## Goals

- Align `signalgateway-dashboard` with the current SignalGateway service API instead of the older scheduler-only integration.
- Rebuild settings around separation of concerns so service, selection, strategy, and portfolio concerns can be managed independently.
- Expose registry-backed configuration choices to users, including selectable implementations and editable parameter schemas.
- Resolve startup conflicts between bootstrap `service_config` and user-managed persisted config with an explicit loading policy.
- Keep runtime snapshots, user config state, and UI editing flows understandable and auditable.

## Current Findings

### Backend

- `SignalGatewayService` already exposes rich config metadata through:
  - `GET /service/strategy-config`
  - `GET /service/selection-config`
  - `GET /service/portfolio/config`
  - `GET /service/scheduler-config`
- The config layer already provides registries and parameter schemas:
  - `STRATEGY_REGISTRY`
  - `SELECTION_PROVIDER_REGISTRY`
  - `PORTFOLIO_OPTIMIZER_REGISTRY`
  - `list_strategy_definitions()`
  - `list_selection_definitions()`
  - `list_portfolio_optimizer_definitions()`
- `SignalGatewayService._persist_runtime_state()` stores a full `config_bundle` inside runtime service state snapshots/events.
- Startup restore currently depends on `service.restore_persisted_state`, but `run_signalgateway.py` explicitly sets `restore_persisted_state=False`.
- Persistence currently stores runtime state and service state, but does not distinguish:
  - bootstrap config from code
  - user-managed saved config
  - active config source / precedence

### Frontend

- The dashboard currently only consumes a narrow slice of the service:
  - health
  - status
  - runtime
  - performance
  - analytics
  - `/service/config`
  - scheduler update
- Settings currently only manage:
  - API base URL
  - refresh interval
  - scheduler
- The current config page is behind the backend:
  - it does not fetch strategy/selection/portfolio config endpoints
  - it does not render registry-backed available options
  - it does not support editing selection, strategy, or portfolio config
- The current `App.vue` also shows obvious encoding damage and tightly couples too much page logic into one file.

## Product Decisions

### 1. Config Precedence

Adopt an explicit precedence model:

1. Runtime bootstrap config from `run_signalgateway.py`
2. Persisted user config from DB for the same `session_id`
3. In-memory edits made through the API after startup

Rule:

- When `restore_persisted_state` is enabled and a persisted user config exists, the service should start from the persisted user config bundle.
- Bootstrap config still provides:
  - the default shape
  - the `session_id`
  - the restore policy
- The API should expose whether active config came from:
  - `bootstrap`
  - `persisted_user_config`
  - `runtime_update`

### 2. Persistence Separation

Separate user-managed config persistence from runtime snapshots:

- Keep runtime/service state snapshots for observability and replay.
- Add dedicated persisted config storage for the latest user-editable config bundle.
- Save user config whenever these API mutations occur:
  - replace service config
  - update scheduler config
  - update selection config
  - update strategy config
  - update portfolio config

### 3. Frontend Settings Information Architecture

Use a dedicated settings workspace with second-level navigation:

- Connection
- Service Runtime
- Selection
- Strategies
- Portfolio

This keeps selection-specific logic away from general settings and makes registry-driven editing easier to reason about.

## Implementation Plan

### Phase 1. Backend persistence and config source cleanup

- Add a dedicated persistence model/table for user config bundles.
- Add recorder/coordinator methods for:
  - saving latest user config
  - loading latest user config
- Introduce config source metadata in the service layer.
- On service init:
  - load bootstrap config
  - if restore is enabled, load persisted user config
  - apply persisted user config before selection/strategy initialization
- Preserve `session_id` and restore policy semantics during restore.
- Persist user config after config-changing API operations.

### Phase 2. Backend API contract improvements

- Extend service config responses with:
  - active config source
  - persisted config availability
  - config last updated time if available
- Add a consolidated config catalog endpoint or enrich existing responses so the frontend can load:
  - service config
  - scheduler config
  - selection config plus available selections
  - strategy config plus available strategies
  - portfolio config plus available optimizers
- Keep existing endpoints compatible where practical.

### Phase 3. Frontend API/state refactor

- Refactor `src/lib/api.js` into a broader config-aware client.
- Fetch and store:
  - service config snapshot
  - scheduler config snapshot
  - selection config snapshot
  - strategy config snapshot
  - portfolio config snapshot
- Add mutation helpers for:
  - scheduler updates
  - selection updates
  - strategy replacement
  - portfolio updates
  - full config replace if still needed

### Phase 4. Frontend settings redesign

- Split settings into secondary sections.
- Build registry-driven forms from backend schemas.
- Selection section:
  - choose selection provider
  - render provider params dynamically
  - show active resolved config
  - surface runtime dependencies read-only
- Strategy section:
  - list current strategy stack
  - add/remove/reorder strategy items
  - choose strategy type from registry
  - edit alias, weight, and params per strategy
- Portfolio section:
  - edit optimizer and portfolio constraints
  - separate rebalance policy and analysis subsections
  - expose enum-like options cleanly where possible
- Service Runtime section:
  - scheduling
  - frequency
  - price lookback
  - slippage
  - candidate cap
  - auto start

### Phase 5. UI/UX cleanup

- Repair damaged text/encoding in the current Vue app.
- Reduce `App.vue` sprawl by extracting settings/config subcomponents where useful.
- Keep overview/performance/diagnostics intact while making config inspection clearer.
- Show active config provenance so users know whether current config came from:
  - startup defaults
  - DB-restored user config
  - current runtime edits

### Phase 6. Validation

- Verify backend endpoints against the running local service.
- Run targeted backend tests for config persistence/restore precedence.
- Build the frontend and validate the new settings flows.
- Smoke test end-to-end:
  - open dashboard
  - edit selection
  - edit strategy stack
  - edit portfolio policy
  - restart service with restore enabled
  - confirm DB config wins over bootstrap defaults for that session

## Risks

- The frontend project is outside the current writable root, so editing it may require escalation.
- Existing local modifications already exist in backend files; edits must avoid clobbering them.
- Dynamic schema-to-form rendering can get noisy unless we normalize labels and field ordering.
- Some portfolio options are free-form strings today; if we want strict dropdowns, backend may need stronger enumerations.

## Deliverables

- Backend config persistence/source changes
- Updated API contract for config-aware frontend editing
- Refactored dashboard settings workspace
- Registry-driven selection/strategy/portfolio editors
- Verification notes covering precedence and end-to-end behavior
