# SignalGateway Refactor Plan

## Goal

Refactor `jh_quant.signalgateway` around a model-centric persistence design.
The first priority is replacing the hard-coded DDL and duplicated SQL in
`order_recorder.py` with ORM-backed persistence while keeping the current
synchronous service and OMS interfaces usable.

## Principles

- Keep domain models and persistence models aligned.
- Reduce duplicated schema definitions across SQLite and PostgreSQL.
- Preserve the existing external recorder API where possible.
- Make the package cheaper to import by avoiding unnecessary heavy imports.
- Refactor incrementally so the module remains runnable during the transition.

## Current Status

### Completed

- Added persistence-oriented model helpers in `jh_quant/signalgateway/models.py`.
- Introduced Tortoise ORM table models for trades, daily performance, position
  snapshots, session state, and service state.
- Replaced recorder-side hard-coded DDL with ORM schema generation in
  `jh_quant/signalgateway/order_recorder.py`.
- Added a synchronous `TortoiseOrderRecorder` facade so existing callers do not
  need to become async immediately.
- Kept `SQLiteOrderRecorder` and `PostgresOrderRecorder` as user-facing entry
  points with a shared persistence core.
- Switched `jh_quant/signalgateway/__init__.py` to lazy exports to avoid
  unrelated dependency chains during lightweight imports.
- Added `tortoise-orm` to `pyproject.toml`.
- Added a focused recorder roundtrip test in
  `test_signalgateway_order_recorder.py`.

### Verified

- Python compilation passes for the updated files.
- The new recorder test is discoverable and runs.
- In the current environment the recorder test is skipped because
  `tortoise-orm` is not installed yet.

### Known Gaps

- The new ORM path has not been fully exercised end-to-end because the runtime
  environment does not currently have `tortoise-orm` installed.
- `OMS` and `service` still persist some state as ad hoc dictionaries rather
  than explicit persistence models.
- Persistence concerns are improved, but the broader module layering is still
  mixed across domain logic, orchestration, and storage.
- Connection lifecycle is currently suitable for the common single-recorder
  process model, but may need refinement if multiple databases are used in the
  same process.

## Next Work Items

### Phase 1: Stabilize the ORM Recorder

- Install `tortoise-orm` in the working environment and run the new recorder
  test for real instead of skip-only validation.
- Add a PostgreSQL-focused smoke test or integration test for upsert and query
  behavior.
- Review field definitions and indexes against realistic query patterns.
- Confirm DSN expectations for PostgreSQL and MemFire usage.

### Phase 2: Make Models the Real Center

- Introduce explicit persistence/state models for OMS session snapshots and
  service runtime snapshots instead of raw dict payloads.
- Add conversion boundaries between domain DTOs, state snapshots, and ORM
  records.
- Reduce serialization logic duplicated across `oms.py` and `service.py`.

### Phase 3: Clarify Module Boundaries

- Separate domain models, persistence models, repositories, and application
  services more explicitly.
- Keep `order_recorder.py` thin and focused on repository-style operations.
- Evaluate whether `service.py` should depend on a higher-level repository
  abstraction instead of the recorder directly.

### Phase 4: Backward Compatibility and Migration

- Decide whether historical SQLite/PostgreSQL databases require migration
  scripts.
- If schema compatibility is not exact, document the migration path clearly.
- Add compatibility notes for existing users who instantiate
  `SQLiteOrderRecorder` or `PostgresOrderRecorder`.

## Proposed Tracking Checklist

- [x] Replace hard-coded recorder DDL with ORM-backed schema generation
- [x] Align recorder persistence with model definitions
- [x] Preserve synchronous recorder API for existing callers
- [x] Reduce package import coupling
- [ ] Install and validate `tortoise-orm` in the local environment
- [ ] Add integration coverage for PostgreSQL
- [ ] Model OMS and service persisted state explicitly
- [ ] Clarify repository/service boundaries across the module
- [ ] Document migration and compatibility expectations

## Notes

- This plan is intentionally incremental. The current recorder refactor is a
  foundation, not the final architecture.
- If we decide Tortoise ORM is not the best long-term fit, the new
  model-centered structure should still make it easier to switch to another ORM
  later.
