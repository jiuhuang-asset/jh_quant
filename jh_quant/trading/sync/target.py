"""Neon / Postgres target — 用 psycopg 直写远端。

- ``upsert`` → ``INSERT ... ON CONFLICT DO UPDATE``
- ``insert_only`` → ``INSERT ... ON CONFLICT DO NOTHING``
- ``SQLiteTarget`` — 仅测试用，复用 Postgres SQL builder
- ``generate_sqlite_schema`` — 通过 Tortoise 在空 SQLite/Postgres 上建表
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import List, Sequence

from .tables import DEFAULT_TABLE_SPECS, TableSyncSpec


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class PostgresTarget:
    """生产用 Postgres / Neon 写端，底层 ``psycopg``。"""

    def __init__(self, conninfo: str):
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "psycopg is required for PostgresTarget; "
                "install via `pip install psycopg[binary]`"
            ) from exc
        import psycopg as _psycopg

        self._conn = _psycopg.connect(conninfo, autocommit=False)

    # ----- writes -----

    def upsert(self, spec: TableSyncSpec, rows: Sequence[dict]) -> int:
        if not rows:
            return 0
        self._check_open()
        columns = list(rows[0].keys())
        sql = self._build_upsert(spec, columns)
        values = [tuple(r[c] for c in columns) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(sql, values)
        self._conn.commit()
        return len(rows)

    def insert_only(self, spec: TableSyncSpec, rows: Sequence[dict]) -> int:
        if not rows:
            return 0
        self._check_open()
        columns = list(rows[0].keys())
        sql = self._build_insert(spec, columns)
        values = [tuple(r[c] for c in columns) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(sql, values)
        self._conn.commit()
        return len(rows)

    # ----- reads / DDL -----

    def count(self, spec: TableSyncSpec) -> int:
        self._check_open()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {_quote(spec.table)}")
            return int(cur.fetchone()[0])

    def truncate(self, spec: TableSyncSpec) -> None:
        self._check_open()
        with self._conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {_quote(spec.table)} CASCADE")
        self._conn.commit()

    def truncate_all(self) -> None:
        """按反序清空所有 7 张表（``--full-reset``）。"""
        for spec in reversed(list(DEFAULT_TABLE_SPECS.values())):
            self.truncate(spec)

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.close()

    def _check_open(self) -> None:
        if self._conn.closed:
            raise RuntimeError("PostgresTarget connection is closed")

    # ----- SQL builders -----

    def _build_upsert(self, spec: TableSyncSpec, columns: Sequence[str]) -> str:
        col_list = ", ".join(_quote(c) for c in columns)
        ph = ", ".join(["%s"] * len(columns))
        conflict_cols = spec.conflict_columns or (columns[0],)
        conflict_list = ", ".join(_quote(c) for c in conflict_cols)
        update_cols = [c for c in columns if c not in set(conflict_cols)]
        if update_cols:
            update_set = ", ".join(
                f"{_quote(c)} = EXCLUDED.{_quote(c)}" for c in update_cols
            )
            on_conflict = f"ON CONFLICT ({conflict_list}) DO UPDATE SET {update_set}"
        else:
            on_conflict = f"ON CONFLICT ({conflict_list}) DO NOTHING"
        return (
            f"INSERT INTO {_quote(spec.table)} ({col_list}) "
            f"VALUES ({ph}) {on_conflict}"
        )

    def _build_insert(self, spec: TableSyncSpec, columns: Sequence[str]) -> str:
        col_list = ", ".join(_quote(c) for c in columns)
        ph = ", ".join(["%s"] * len(columns))
        conflict_cols = spec.conflict_columns
        if conflict_cols:
            conflict_list = ", ".join(_quote(c) for c in conflict_cols)
            return (
                f"INSERT INTO {_quote(spec.table)} ({col_list}) "
                f"VALUES ({ph}) ON CONFLICT ({conflict_list}) DO NOTHING"
            )
        return f"INSERT INTO {_quote(spec.table)} ({col_list}) VALUES ({ph})"


__all__ = ["PostgresTarget", "SQLiteTarget", "generate_postgres_schema", "generate_sqlite_schema"]


# ---------------------------------------------------------------------------
# SQLite target — testing only
# ---------------------------------------------------------------------------

# 注册 datetime/date → ISO 字符串 adapter，让 SQLite 能存
sqlite3.register_adapter(datetime, lambda v: v.isoformat(" "))
sqlite3.register_adapter(date, lambda v: v.isoformat())


class SQLiteTarget:
    """**仅测试用** SQLite 写端。SQL 生成与 PostgresTarget 共用（``%s → ?``）。"""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)

    def upsert(self, spec: TableSyncSpec, rows: Sequence[dict]) -> int:
        if not rows:
            return 0
        columns = list(rows[0].keys())
        sql = PostgresTarget._build_upsert(None, spec, columns).replace("%s", "?")  # type: ignore[arg-type]
        values = [tuple(r[c] for c in columns) for r in rows]
        with self._conn:
            self._conn.executemany(sql, values)
        return len(rows)

    def insert_only(self, spec: TableSyncSpec, rows: Sequence[dict]) -> int:
        if not rows:
            return 0
        columns = list(rows[0].keys())
        sql = PostgresTarget._build_insert(None, spec, columns).replace("%s", "?")  # type: ignore[arg-type]
        values = [tuple(r[c] for c in columns) for r in rows]
        with self._conn:
            self._conn.executemany(sql, values)
        return len(rows)

    def count(self, spec: TableSyncSpec) -> int:
        cur = self._conn.execute(f'SELECT COUNT(*) FROM "{spec.table}"')
        return int(cur.fetchone()[0])

    def truncate(self, spec: TableSyncSpec) -> None:
        with self._conn:
            self._conn.execute(f'DELETE FROM "{spec.table}"')

    def truncate_all(self) -> None:
        for spec in reversed(list(DEFAULT_TABLE_SPECS.values())):
            self.truncate(spec)

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Schema bootstrap — 通过 Tortoise 一键建表（生产首次运行 / 测试用）
# ---------------------------------------------------------------------------


def generate_sqlite_schema(db_path: str) -> None:
    """在空 SQLite DB 上建 7 张表。"""
    import asyncio
    from pathlib import Path

    from tortoise import Tortoise

    url = f"sqlite:///{Path(db_path).resolve().as_posix()}"

    async def _setup():
        await Tortoise.init(
            db_url=url,
            modules={"models": ["jh_quant.trading.persistence.models"]},
            _enable_global_fallback=False,
        )
        await Tortoise.generate_schemas()
        await Tortoise.close_connections()

    asyncio.run(_setup())


def generate_postgres_schema(conninfo: str) -> None:
    """在目标 Postgres / Neon DB 上建 7 张表。

    不依赖 Tortoise/asyncpg，直接用 psycopg 发 CREATE TABLE IF NOT EXISTS。
    """
    import psycopg

    ddl = _POSTGRES_DDL
    conn = psycopg.connect(conninfo)
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    finally:
        conn.close()


# ---- DDL: 与 persistence/models.py 7 张表结构对齐 ----
_POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id        VARCHAR(128) PRIMARY KEY,
    session_id      VARCHAR(128) NOT NULL,
    trade_date      TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(32) NOT NULL,
    trade_type      VARCHAR(16) NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    quantity        INTEGER NOT NULL,
    amount          DOUBLE PRECISION NOT NULL,
    commission      DOUBLE PRECISION DEFAULT 0.0,
    slippage        DOUBLE PRECISION DEFAULT 0.0,
    total_cost      DOUBLE PRECISION NOT NULL,
    signal_reason   TEXT,
    order_id        VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trades_session_date ON trades(session_id, trade_date);

CREATE TABLE IF NOT EXISTS daily_performances (
    performance_id    VARCHAR(128) PRIMARY KEY,
    session_id        VARCHAR(128) NOT NULL,
    trade_date        DATE NOT NULL,
    portfolio_value   DOUBLE PRECISION NOT NULL,
    cash_balance      DOUBLE PRECISION NOT NULL,
    position_value    DOUBLE PRECISION NOT NULL,
    daily_return      DOUBLE PRECISION,
    cumulative_return DOUBLE PRECISION,
    daily_pnl         DOUBLE PRECISION,
    num_positions     INTEGER DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_perf_session_date ON daily_performances(session_id, trade_date);

CREATE TABLE IF NOT EXISTS positions_snapshot (
    snapshot_id   VARCHAR(128) PRIMARY KEY,
    session_id    VARCHAR(128) NOT NULL,
    trade_date    TIMESTAMPTZ NOT NULL,
    symbol        VARCHAR(32) NOT NULL,
    quantity      INTEGER NOT NULL,
    avg_cost      DOUBLE PRECISION NOT NULL,
    current_price DOUBLE PRECISION NOT NULL,
    market_value  DOUBLE PRECISION NOT NULL,
    pnl           DOUBLE PRECISION,
    pnl_pct       DOUBLE PRECISION,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pos_session_date ON positions_snapshot(session_id, trade_date);

CREATE TABLE IF NOT EXISTS session_states (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(128) NOT NULL,
    state_data  JSONB NOT NULL,
    export_time TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, export_time)
);
CREATE INDEX IF NOT EXISTS idx_ss_session_time ON session_states(session_id, export_time);

CREATE TABLE IF NOT EXISTS session_runtime_states (
    session_id  VARCHAR(128) PRIMARY KEY,
    state_data  JSONB NOT NULL,
    export_time TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_srs_session_time ON session_runtime_states(session_id, export_time);

CREATE TABLE IF NOT EXISTS session_config_records (
    id           SERIAL PRIMARY KEY,
    session_id   VARCHAR(128) NOT NULL,
    config_md5   VARCHAR(32) NOT NULL,
    config_bundle JSONB NOT NULL,
    source       VARCHAR(64) DEFAULT 'runtime_update',
    export_time  TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, config_md5)
);
CREATE INDEX IF NOT EXISTS idx_scr_session_time ON session_config_records(session_id, export_time);
CREATE INDEX IF NOT EXISTS idx_scr_session_src  ON session_config_records(session_id, source);

CREATE TABLE IF NOT EXISTS session_runtime_events (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(128) NOT NULL,
    event_type  VARCHAR(128) NOT NULL,
    state_data  JSONB NOT NULL,
    event_time  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sre_session_time ON session_runtime_events(session_id, event_time);
CREATE INDEX IF NOT EXISTS idx_sre_session_type ON session_runtime_events(session_id, event_type);
"""
