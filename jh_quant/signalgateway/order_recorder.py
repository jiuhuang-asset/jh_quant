"""
Persistence adapters for trades, performance snapshots, and session state.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

import pandas as pd

from .models import DailyPerformance, PositionSnapshot, Trade

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional dependency at runtime
    psycopg = None
    dict_row = None


class OrderRecorder:
    """Abstract recorder for trading artifacts."""

    def create_schema(self):
        raise NotImplementedError

    def save_trade(self, trade: Trade):
        raise NotImplementedError

    def save_daily_performance(self, perf: DailyPerformance):
        raise NotImplementedError

    def save_position_snapshot(self, snapshot: PositionSnapshot):
        raise NotImplementedError

    def save_session_state(self, state: Dict[str, Any]):
        """保存 OMS 会话状态（含持仓、交易记录等）"""
        raise NotImplementedError

    def load_latest_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """加载最新 OMS 会话状态"""
        raise NotImplementedError

    def save_service_state(self, state: Dict[str, Any]):
        """保存 Service 运行时状态（配置、策略、结果等）"""
        raise NotImplementedError

    def load_latest_service_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """加载最新 Service 运行时状态"""
        raise NotImplementedError

    def query_trades(self, session_id: str) -> pd.DataFrame:
        raise NotImplementedError

    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        raise NotImplementedError

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        raise NotImplementedError

    def close(self):
        return None


def _ensure_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _ensure_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ensure_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    # 不可序列化的对象（如 FamaMacBethValidationResult）转为字符串或跳过
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class SQLiteOrderRecorder(OrderRecorder):
    """SQLite-backed recorder for local paper trading."""

    def __init__(self, db_path: str = "order_records.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_schema()

    def create_schema(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                trade_date TIMESTAMP NOT NULL,
                symbol TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                amount REAL NOT NULL,
                commission REAL DEFAULT 0,
                slippage REAL DEFAULT 0,
                total_cost REAL NOT NULL,
                signal_reason TEXT,
                order_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_performances (
                performance_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                trade_date DATE NOT NULL,
                portfolio_value REAL NOT NULL,
                cash_balance REAL NOT NULL,
                position_value REAL NOT NULL,
                daily_return REAL,
                cumulative_return REAL,
                daily_pnl REAL,
                num_positions INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS positions_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                trade_date TIMESTAMP NOT NULL,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                avg_cost REAL NOT NULL,
                current_price REAL NOT NULL,
                market_value REAL NOT NULL,
                pnl REAL,
                pnl_pct REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session_states (
                session_id TEXT NOT NULL,
                state_data TEXT NOT NULL,
                export_time TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, export_time)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session_service_states (
                session_id TEXT PRIMARY KEY,
                state_data TEXT NOT NULL,
                export_time TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_perf_session ON daily_performances(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_position_session ON positions_snapshot(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_states_session ON session_states(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_service_states_session ON session_service_states(session_id)"
        )
        self.conn.commit()

    def save_trade(self, trade: Trade):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO trades
            (trade_id, session_id, trade_date, symbol, trade_type, price, quantity,
             amount, commission, slippage, total_cost, signal_reason, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                trade.trade_id,
                trade.session_id,
                trade.trade_date.isoformat(),
                trade.symbol,
                trade.trade_type,
                trade.price,
                trade.quantity,
                trade.amount,
                trade.commission,
                trade.slippage,
                trade.total_cost,
                trade.signal_reason,
                trade.order_id,
            ],
        )
        self.conn.commit()

    def save_daily_performance(self, perf: DailyPerformance):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO daily_performances
            (performance_id, session_id, trade_date, portfolio_value, cash_balance,
             position_value, daily_return, cumulative_return, daily_pnl, num_positions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                perf.performance_id,
                perf.session_id,
                perf.trade_date.date() if hasattr(perf.trade_date, "date") else perf.trade_date,
                perf.portfolio_value,
                perf.cash_balance,
                perf.position_value,
                perf.daily_return,
                perf.cumulative_return,
                perf.daily_pnl,
                perf.num_positions,
            ],
        )
        self.conn.commit()

    def save_position_snapshot(self, snapshot: PositionSnapshot):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO positions_snapshot
            (snapshot_id, session_id, trade_date, symbol, quantity, avg_cost,
             current_price, market_value, pnl, pnl_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                snapshot.snapshot_id,
                snapshot.session_id,
                snapshot.trade_date.isoformat(),
                snapshot.symbol,
                snapshot.quantity,
                snapshot.avg_cost,
                snapshot.current_price,
                snapshot.market_value,
                snapshot.pnl,
                snapshot.pnl_pct,
            ],
        )
        self.conn.commit()

    def save_session_state(self, state: Dict[str, Any]):
        state_json = json.dumps(_ensure_jsonable(state), ensure_ascii=False)
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO session_states (session_id, state_data, export_time)
            VALUES (?, ?, ?)
            """,
            [
                state.get("session_id"),
                state_json,
                _ensure_jsonable(state.get("export_time")),
            ],
        )
        self.conn.commit()

    def load_latest_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT state_data FROM session_states
            WHERE session_id = ?
            ORDER BY export_time DESC
            LIMIT 1
            """,
            [session_id],
        )
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None

    def save_service_state(self, state: Dict[str, Any]):
        """保存 Service 运行时状态（REPLACE 保证同一 session 只有一条）"""
        state_json = json.dumps(_ensure_jsonable(state), ensure_ascii=False)
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO session_service_states (session_id, state_data, export_time)
            VALUES (?, ?, ?)
            """,
            [
                state.get("session_id"),
                state_json,
                _ensure_jsonable(state.get("export_time")),
            ],
        )
        self.conn.commit()

    def load_latest_service_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT state_data FROM session_service_states
            WHERE session_id = ?
            """,
            [session_id],
        )
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None

    def query_trades(self, session_id: str) -> pd.DataFrame:
        return pd.read_sql(
            "SELECT * FROM trades WHERE session_id = ? ORDER BY trade_date",
            self.conn,
            params=[session_id],
        )

    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        return pd.read_sql(
            "SELECT * FROM daily_performances WHERE session_id = ? ORDER BY trade_date",
            self.conn,
            params=[session_id],
        )

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        return pd.read_sql(
            "SELECT * FROM positions_snapshot WHERE session_id = ? ORDER BY trade_date",
            self.conn,
            params=[session_id],
        )

    def close(self):
        self.conn.close()


class PostgresOrderRecorder(OrderRecorder):
    """Postgres-backed recorder for hosted databases such as MemFire Cloud."""

    def __init__(self, conninfo: str):
        if psycopg is None:
            raise ImportError("psycopg is required to use PostgresOrderRecorder")
        self.conninfo = conninfo
        self.conn = psycopg.connect(conninfo, row_factory=dict_row)
        self.conn.autocommit = True
        self.create_schema()

    def create_schema(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    trade_date TIMESTAMPTZ NOT NULL,
                    symbol TEXT NOT NULL,
                    trade_type TEXT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    quantity INTEGER NOT NULL,
                    amount DOUBLE PRECISION NOT NULL,
                    commission DOUBLE PRECISION DEFAULT 0,
                    slippage DOUBLE PRECISION DEFAULT 0,
                    total_cost DOUBLE PRECISION NOT NULL,
                    signal_reason TEXT,
                    order_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_performances (
                    performance_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    trade_date DATE NOT NULL,
                    portfolio_value DOUBLE PRECISION NOT NULL,
                    cash_balance DOUBLE PRECISION NOT NULL,
                    position_value DOUBLE PRECISION NOT NULL,
                    daily_return DOUBLE PRECISION,
                    cumulative_return DOUBLE PRECISION,
                    daily_pnl DOUBLE PRECISION,
                    num_positions INTEGER,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS positions_snapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    trade_date TIMESTAMPTZ NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    avg_cost DOUBLE PRECISION NOT NULL,
                    current_price DOUBLE PRECISION NOT NULL,
                    market_value DOUBLE PRECISION NOT NULL,
                    pnl DOUBLE PRECISION,
                    pnl_pct DOUBLE PRECISION,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_states (
                    session_id TEXT NOT NULL,
                    state_data JSONB NOT NULL,
                    export_time TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (session_id, export_time)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_service_states (
                    session_id TEXT PRIMARY KEY,
                    state_data JSONB NOT NULL,
                    export_time TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_perf_session ON daily_performances(session_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_position_session ON positions_snapshot(session_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_states_session ON session_states(session_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_service_states_session ON session_service_states(session_id)"
            )

    def save_trade(self, trade: Trade):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trades
                (trade_id, session_id, trade_date, symbol, trade_type, price, quantity,
                 amount, commission, slippage, total_cost, signal_reason, order_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    trade_date = EXCLUDED.trade_date,
                    symbol = EXCLUDED.symbol,
                    trade_type = EXCLUDED.trade_type,
                    price = EXCLUDED.price,
                    quantity = EXCLUDED.quantity,
                    amount = EXCLUDED.amount,
                    commission = EXCLUDED.commission,
                    slippage = EXCLUDED.slippage,
                    total_cost = EXCLUDED.total_cost,
                    signal_reason = EXCLUDED.signal_reason,
                    order_id = EXCLUDED.order_id
                """,
                [
                    trade.trade_id,
                    trade.session_id,
                    trade.trade_date.to_pydatetime()
                    if hasattr(trade.trade_date, "to_pydatetime")
                    else trade.trade_date,
                    trade.symbol,
                    trade.trade_type,
                    trade.price,
                    trade.quantity,
                    trade.amount,
                    trade.commission,
                    trade.slippage,
                    trade.total_cost,
                    trade.signal_reason,
                    trade.order_id,
                ],
            )

    def save_daily_performance(self, perf: DailyPerformance):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_performances
                (performance_id, session_id, trade_date, portfolio_value, cash_balance,
                 position_value, daily_return, cumulative_return, daily_pnl, num_positions)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (performance_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    trade_date = EXCLUDED.trade_date,
                    portfolio_value = EXCLUDED.portfolio_value,
                    cash_balance = EXCLUDED.cash_balance,
                    position_value = EXCLUDED.position_value,
                    daily_return = EXCLUDED.daily_return,
                    cumulative_return = EXCLUDED.cumulative_return,
                    daily_pnl = EXCLUDED.daily_pnl,
                    num_positions = EXCLUDED.num_positions
                """,
                [
                    perf.performance_id,
                    perf.session_id,
                    perf.trade_date.date() if hasattr(perf.trade_date, "date") else perf.trade_date,
                    perf.portfolio_value,
                    perf.cash_balance,
                    perf.position_value,
                    perf.daily_return,
                    perf.cumulative_return,
                    perf.daily_pnl,
                    perf.num_positions,
                ],
            )

    def save_position_snapshot(self, snapshot: PositionSnapshot):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO positions_snapshot
                (snapshot_id, session_id, trade_date, symbol, quantity, avg_cost,
                 current_price, market_value, pnl, pnl_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    trade_date = EXCLUDED.trade_date,
                    symbol = EXCLUDED.symbol,
                    quantity = EXCLUDED.quantity,
                    avg_cost = EXCLUDED.avg_cost,
                    current_price = EXCLUDED.current_price,
                    market_value = EXCLUDED.market_value,
                    pnl = EXCLUDED.pnl,
                    pnl_pct = EXCLUDED.pnl_pct
                """,
                [
                    snapshot.snapshot_id,
                    snapshot.session_id,
                    snapshot.trade_date.to_pydatetime()
                    if hasattr(snapshot.trade_date, "to_pydatetime")
                    else snapshot.trade_date,
                    snapshot.symbol,
                    snapshot.quantity,
                    snapshot.avg_cost,
                    snapshot.current_price,
                    snapshot.market_value,
                    snapshot.pnl,
                    snapshot.pnl_pct,
                ],
            )

    def save_session_state(self, state: Dict[str, Any]):
        normalized = _ensure_jsonable(state)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_states (session_id, state_data, export_time)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (session_id, export_time) DO UPDATE SET
                    state_data = EXCLUDED.state_data
                """,
                [
                    normalized.get("session_id"),
                    json.dumps(normalized, ensure_ascii=False),
                    normalized.get("export_time"),
                ],
            )

    def load_latest_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT state_data
                FROM session_states
                WHERE session_id = %s
                ORDER BY export_time DESC
                LIMIT 1
                """,
                [session_id],
            )
            row = cur.fetchone()
        return row["state_data"] if row else None

    def save_service_state(self, state: Dict[str, Any]):
        normalized = _ensure_jsonable(state)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_service_states (session_id, state_data, export_time)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    state_data = EXCLUDED.state_data,
                    export_time = EXCLUDED.export_time
                """,
                [
                    normalized.get("session_id"),
                    json.dumps(normalized, ensure_ascii=False),
                    normalized.get("export_time"),
                ],
            )

    def load_latest_service_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT state_data
                FROM session_service_states
                WHERE session_id = %s
                """,
                [session_id],
            )
            row = cur.fetchone()
        return row["state_data"] if row else None

    def _query_dataframe(self, query: str, params: list[Any]) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return pd.DataFrame(rows)

    def query_trades(self, session_id: str) -> pd.DataFrame:
        return self._query_dataframe(
            "SELECT * FROM trades WHERE session_id = %s ORDER BY trade_date",
            [session_id],
        )

    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        return self._query_dataframe(
            "SELECT * FROM daily_performances WHERE session_id = %s ORDER BY trade_date",
            [session_id],
        )

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        return self._query_dataframe(
            "SELECT * FROM positions_snapshot WHERE session_id = %s ORDER BY trade_date",
            [session_id],
        )

    def close(self):
        self.conn.close()


class MemFireCloudRecorder(PostgresOrderRecorder):
    """User-facing alias for a MemFire Cloud backed recorder."""

    def __init__(self, conninfo: str):
        super().__init__(conninfo=conninfo)
