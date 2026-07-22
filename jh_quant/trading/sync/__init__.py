"""Sync local trading SQLite → remote Neon/Postgres.

非侵入式增量同步工具。详细设计见
``specs/trading/plan__sync_local_trading_to_remote_v2.md``。

典型用法::

    REMOTE_DB_URL=postgresql://... jh-quant sync --from trade_paper.db
"""

from __future__ import annotations

from .source import SQLiteSource
from .syncer import SyncReport, TableResult, run_sync
from .tables import (
    DEFAULT_TABLE_SPECS,
    SyncMode,
    TableSyncSpec,
    get_spec,
    list_default_tables,
    resolve_specs,
)
from .target import (
    PostgresTarget,
    SQLiteTarget,
    generate_postgres_schema,
    generate_sqlite_schema,
)
from .watermark import (
    STATE_VERSION,
    SyncState,
    TableWatermark,
    default_state_path,
    load_state,
    save_state,
    source_fingerprint,
)

__all__ = [
    "DEFAULT_TABLE_SPECS",
    "PostgresTarget",
    "SQLiteSource",
    "SQLiteTarget",
    "STATE_VERSION",
    "SyncMode",
    "SyncReport",
    "SyncState",
    "TableSyncSpec",
    "TableResult",
    "TableWatermark",
    "default_state_path",
    "generate_postgres_schema",
    "generate_sqlite_schema",
    "get_spec",
    "list_default_tables",
    "load_state",
    "resolve_specs",
    "run_sync",
    "save_state",
    "source_fingerprint",
]
