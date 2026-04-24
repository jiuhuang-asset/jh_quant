# SignalGateway Analytics And Robustness Plan

## Goals

- Strengthen `SignalGatewayService` analytics output for future visualization tasks.
- Keep persistence responsibilities centralized behind `PersistenceCoordinator`.
- Validate simulated live-trading storage and analytics flows with test-driven development.
- Ignore backward compatibility and optimize for the cleanest current architecture.

## Desired Outcomes

- A service-level analytics snapshot that is easier for `service_api` and dashboards to consume.
- Aggregated views derived from persisted trading artifacts, not ad hoc logic in the API layer.
- Tests that exercise the end-to-end paper-trading cycle, persistence writes, state restore, and analytics calculations.

## Workstreams

1. Analytics surface review
   - Review current `SignalGatewayService`, `PersistenceCoordinator`, `performance.py`, and `service_api.py`.
   - Identify which analytics are missing for front-end visualization.

2. Analytics model enhancements
   - Add richer derived analytics on top of persisted trades, daily performance, and position snapshots.
   - Prefer stable, front-end-friendly structures such as time series, activity summaries, and exposure breakdowns.

3. Service integration
   - Expose the richer analytics through `SignalGatewayService`.
   - Keep `service_api` thin and delegate aggregation to the service layer.

4. TDD robustness pass
   - Replace outdated tests with current-architecture tests.
   - Cover normal flow, empty-data flow, state restore, and repeated persistence updates.
   - Verify analytics outputs stay stable for visualization consumers.

## Verification Strategy

- Write failing tests first for the new analytics/reporting contract.
- Run focused pytest coverage for signalgateway service, persistence, and analytics tests.
- Run lightweight syntax checks for touched modules.

## Notes

- Prefer deterministic tests with synthetic market data and synthetic selection providers.
- Use real persistence adapters when practical, but keep the test suite robust if optional runtime dependencies are unavailable.
