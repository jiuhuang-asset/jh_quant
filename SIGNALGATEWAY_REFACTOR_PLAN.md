# SignalGateway Refactor Plan

## Background

`jh_quant.signalgateway` is evolving from a local signal-and-execution helper into a reusable trading service layer.
The next stage needs to support:

1. Paper trading and live trading under a unified architecture.
2. User-owned persistence using MemFire Cloud.
3. A long-running service process that keeps selecting stocks, generating signals, and executing trades.
4. HTTP APIs that mobile or other clients can call to monitor and control the service.
5. A future-friendly extension point for natural-language / LLM-driven operations.

MemFire Cloud uses a PostgreSQL-compatible connection flow, so the recorder implementation should target a user-supplied Postgres connection URI.

## Refactor Goals

### Core architecture goals

- Separate signal generation from trade execution.
- Separate market data access from selection and execution logic.
- Keep `OMS` focused on portfolio/account state management.
- Allow a service runner to orchestrate periodic selection, signal generation, and execution.
- Preserve backward compatibility for existing local scripts where practical.

### Product goals

- Users can configure a MemFire Cloud connection string and store their own trading records.
- Users can launch a persistent SignalGateway service for paper trading or live trading.
- The service exposes HTTP APIs for status, config updates, manual execution, and future LLM integration.
- Mobile apps can later connect to the service and to the same database for tracking and control.

## Target Architecture

### 1. Signal Engine layer

Responsibility:

- Aggregate strategy buy/sell signals.
- Produce long/short candidates from historical price data.
- Calculate target positions with pluggable sizing logic.

Key properties:

- Must support direct `price_df` input for offline / batch workflows.
- May optionally use a `MarketDataProvider` when price data is not preloaded.

### 2. Selection layer

Responsibility:

- Produce a target symbol universe for the current cycle.
- Encapsulate factor-based or custom stock selection logic.

Examples:

- Factor selection using `JhSelector`.
- Fixed symbol list selection.
- Future custom or LLM-assisted selection strategies.

### 3. Execution / portfolio layer

Responsibility:

- Hold account state, positions, and balances.
- Execute or simulate orders via OMS-compatible interfaces.
- Persist trades, performance snapshots, and session state.

Design direction:

- `MockOMS` remains the default paper-trading implementation.
- Real broker OMS implementations can be added later without changing the signal engine.

### 4. Service orchestration layer

Responsibility:

- Run recurring trading cycles.
- Fetch selection universe.
- Fetch price data.
- Generate short candidates then long candidates.
- Execute trades.
- Persist state and expose service status.

Design direction:

- One service instance manages one trading session / strategy session.
- Service supports start, stop, run-once, and status inspection.

### 5. API layer

Responsibility:

- Expose operational control endpoints.
- Surface service status and latest execution results.
- Accept strategy and selection config updates.
- Reserve an LLM command endpoint for future natural-language control.

## Planned Deliverables

### Deliverable A: Persistence

- Add a PostgreSQL-backed order recorder for MemFire Cloud.
- Accept user-supplied connection URI.
- Persist:
  - trades
  - daily performance
  - position snapshots
  - session state

### Deliverable B: Service runner

- Add a long-running `SignalGatewayService`.
- Support recurring trading cycles with configurable interval.
- Support manual `run_once`.
- Support paper mode immediately.
- Keep interface open for live mode with a user-provided OMS / broker adapter.

### Deliverable C: HTTP service

- Add an API app for running the service.
- Add endpoints such as:
  - `GET /health`
  - `GET /service/status`
  - `GET /service/config`
  - `POST /service/start`
  - `POST /service/stop`
  - `POST /service/run-once`
  - `POST /service/selection-config`
  - `POST /service/strategy-config`
  - `POST /service/llm/command`

### Deliverable D: Configurable runtime

- Strategy pool can be updated without rewriting the service entry script.
- Selection config can be updated through API.
- Session mode can distinguish paper vs live.
- Existing local script entrypoints are simplified to service-aware setup.

## Final Feature Checklist

### Persistence

- [ ] MemFire Cloud recorder based on Postgres connection string
- [ ] Schema auto-creation
- [ ] Session state persistence
- [ ] Query helpers for downstream app consumption

### Engine and execution

- [ ] Clear separation between signal generation and execution
- [ ] Direct `price_df` path for offline / backtest-like workflows
- [ ] Provider-based data path for service / live workflows
- [ ] Backward-compatible script usage for local tests

### Service

- [ ] Background scheduler loop
- [ ] Start / stop / run-once controls
- [ ] Service status model
- [ ] Last run summary
- [ ] Session-level config persistence

### APIs

- [ ] Status endpoints
- [ ] Strategy update endpoint
- [ ] Selection update endpoint
- [ ] Manual trading cycle endpoint
- [ ] LLM hook endpoint placeholder

### Extensibility

- [ ] Easy to plug in real broker OMS later
- [ ] Easy to plug in alternative selectors later
- [ ] Easy for mobile app to read records from MemFire Cloud

## Implementation Strategy

### Phase 1

- Introduce the refactored service architecture while preserving `SignalGateway` facade behavior.
- Add selection abstraction and service orchestration.

### Phase 2

- Add MemFire Cloud / Postgres recorder.
- Wire recorder into paper trading and service sessions.

### Phase 3

- Add HTTP API layer.
- Add config update endpoints and service controls.

### Phase 4

- Simplify `test_signalgateway.py` to use the new service-oriented entry flow.
- Validate the end-to-end paper-trading path.

## Notes for Future Development

- Real live trading will likely require a broker-specific OMS plus order status lifecycle support.
- The current refactor should avoid overfitting to paper-trading-only semantics.
- The LLM endpoint in this phase should remain a controlled extension point, not a full autonomous trading implementation.
