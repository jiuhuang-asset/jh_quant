# CHANGELOG

## [Unreleased]

### Added
- **Session config history API**: New endpoint `GET /sessions/{session_id}/config/history` returns the full config change history for a session, with field-level diffs between consecutive versions.
  - New response models: `ConfigChangeItem`, `SessionConfigHistoryEntry`, `SessionConfigHistoryResponse`
  - `SessionService.get_session_config_history()` computes recursive diffs between config snapshots
  - `PersistenceCoordinator.query_session_configs()` and `TortoiseOrderRecorder.query_session_configs()` fetch all config records ordered by `export_time`
