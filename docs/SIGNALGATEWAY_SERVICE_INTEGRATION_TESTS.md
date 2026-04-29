# SignalGateway Service Integration Test Matrix

## Scope

This document tracks end-to-end integration coverage for `jh_quant.signalgateway.service`.

Focus areas:

- unified config lifecycle and hot reload
- persisted user config / service state / OMS state restore
- scheduler startup and hot reconfiguration
- latest market price usage for runtime PnL and snapshots
- portfolio optimization and rebalance branches
- selection + strategy + portfolio interaction under different settings

## Case Inventory

| ID | Area | Case | Status | Notes |
| --- | --- | --- | --- | --- |
| SG-INT-001 | Config | `replace_service_config` can hot-reload service/selection/strategy/portfolio config and persist the user override | Done | Implemented in `tests/test_signalgateway_service_integration.py` |
| SG-INT-002 | Config Restore | service restart prefers persisted user config over bootstrap config | Done | Covered together with SG-INT-001 |
| SG-INT-003 | Market Data / PnL | position snapshots and daily performance use `MarketDataProvider.get_latest_prices()` instead of stale in-memory / persisted price values | Done | Implemented |
| SG-INT-004 | Scheduler | `auto_start=True` starts the scheduler thread during service init | Done | Implemented with controlled scheduler stub |
| SG-INT-005 | Scheduler | hot scheduler update restarts the running scheduler and changes effective mode | Done | Implemented |
| SG-INT-006 | Scheduler Conflict | when both `interval_seconds` and `cron_expression` are set, cron mode wins while interval remains as fallback config | Done | Implemented |
| SG-INT-007 | Portfolio | portfolio rebalance respects A-share T+1 executable holdings constraint | Done | Implemented |
| SG-INT-008 | Portfolio | portfolio rebalance caps downstream buy orders when expected sell liquidity is blocked | Done | Implemented |
| SG-INT-009 | Portfolio + Strategy | optimization uses strategy-filtered positive-signal subset when available | Done | Implemented |
| SG-INT-010 | Portfolio + Strategy | optimization falls back to selection universe when no strategy is registered | Done | Implemented |
| SG-INT-011 | Portfolio + Strategy | optimization falls back to selection universe when strategies exist but produce no positive buy scores | TODO | Similar to SG-INT-010 but distinct fallback reason |
| SG-INT-012 | Portfolio Policy | `initial_only` rebalance triggers only before first allocation | TODO | Needs explicit holdings/no-holdings dual-case |
| SG-INT-013 | Portfolio Policy | `drift_threshold` obeys threshold and `min_rebalance_interval_seconds` | TODO | High value for regression coverage |
| SG-INT-014 | Portfolio Policy | `manual_only` does not auto-rebalance inside `run_once` | TODO | Should verify `run_once` skip path payload |
| SG-INT-015 | Runtime Restore | latest portfolio optimization / rebalance payload restores across restart | TODO | Would validate service-state continuity |
| SG-INT-016 | OMS Restore | OMS positions and cash restore from persisted session state on restart | TODO | Important for multi-run paper trading continuity |
| SG-INT-017 | Service Events | service events timeline contains expected event types for config changes / start / stop / cycle | TODO | Current tests only touch part of this indirectly |
| SG-INT-018 | Error Handling | scheduler cycle failure persists `last_error` and error result payload | TODO | Needs controlled failing selection/strategy |
| SG-INT-019 | Classic Branch | `run_once` classic signal branch executes sell-before-buy sequencing correctly | TODO | Separate from portfolio overlay |
| SG-INT-020 | Selection Config | invalid selection params fail fast during provider rebuild | TODO | Useful contract test for config studio |

## TODO

- Add dedicated restore tests for OMS state and latest portfolio state payloads.
- Add negative-path coverage for invalid `cron_expression`, invalid timezone, and invalid selection/strategy config.
- Add rebalance-policy coverage for `initial_only`, `drift_threshold`, and `manual_only`.
- Add scheduler error-path coverage to verify `last_error`, persisted `cycle_error`, and restart behavior.
- Add a classic branch scenario with real buy/sell execution and trade persistence assertions.
- Consider adding API-layer integration tests on top of these service-level cases once the service contract stabilizes.

## Current Resolution Notes

- Scheduler conflict policy is currently: if `cron_expression` is non-empty, cron mode is the effective schedule mode and `interval_seconds` is treated as retained fallback config.
- Runtime PnL snapshots should always be computed from latest market prices when available; persisted historical snapshot values must not be treated as live prices.
- Portfolio rebalance must honor `executable_holds` first, then recompute affordable buy capacity from remaining cash plus executable sells.
