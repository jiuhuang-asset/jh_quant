"""
Persistence adapters for trades, performance snapshots, and session state.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from concurrent.futures import Future
from datetime import date, datetime
from pathlib import Path
from threading import Thread
from typing import Any, Awaitable, Dict, Optional

import pandas as pd

from .models import (
    DailyPerformance,
    DailyPerformanceRecord,
    PositionSnapshot,
    PositionSnapshotRecord,
    ServiceStateRecord,
    SessionStateRecord,
    Trade,
    TradeRecord,
    normalize_jsonable_value,
    require_tortoise_orm,
)
from .persistence_protocols import (
    PerformancePersistence,
    PositionPersistence,
    ServiceStatePersistence,
    SessionStatePersistence,
    TradePersistence,
)


def _module_path() -> str:
    return f"{__package__}.models" if __package__ else "jh_quant.signalgateway.models"


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return pd.Timestamp(value).to_pydatetime()


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return _as_datetime(value).date()


def _as_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _sqlite_db_url(db_path: str) -> str:
    resolved = Path(db_path).resolve().as_posix()
    return f"sqlite:///{resolved}"


class _AsyncLoopRunner:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Awaitable[Any]) -> Any:
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        self._loop.close()


class OrderRecorder(
    TradePersistence,
    PerformancePersistence,
    PositionPersistence,
    SessionStatePersistence,
    ServiceStatePersistence,
    ABC,
):
    """Abstract recorder for trading artifacts."""

    @abstractmethod
    def create_schema(self):
        raise NotImplementedError

    @abstractmethod
    def save_trade(self, trade: Trade):
        raise NotImplementedError

    @abstractmethod
    def save_daily_snapshot(self, perf: DailyPerformance):
        raise NotImplementedError

    @abstractmethod
    def save_position_snapshot(self, snapshot: PositionSnapshot):
        raise NotImplementedError

    @abstractmethod
    def save_session_state(self, state: Dict[str, Any]):
        raise NotImplementedError

    @abstractmethod
    def load_latest_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def save_service_state(self, state: Dict[str, Any]):
        raise NotImplementedError

    @abstractmethod
    def load_latest_service_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def query_trades(self, session_id: str) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        raise NotImplementedError

    def close(self):
        return None


class TortoiseOrderRecorder(OrderRecorder):
    """Synchronous facade over Tortoise ORM for recorder operations."""

    def __init__(self, db_url: str, *, app_label: str = "models"):
        require_tortoise_orm()
        self.db_url = db_url
        self.app_label = app_label
        self._runner = _AsyncLoopRunner()
        self._runner.run(self._init_orm())

    async def _init_orm(self):
        from tortoise import Tortoise

        await Tortoise.init(
            db_url=self.db_url,
            modules={self.app_label: [_module_path()]},
            _enable_global_fallback=True,
        )
        await Tortoise.generate_schemas(safe=True)

    async def _close_orm(self):
        from tortoise import Tortoise

        await Tortoise.close_connections()

    def create_schema(self):
        self._runner.run(self._create_schema())

    async def _create_schema(self):
        from tortoise import Tortoise

        await Tortoise.generate_schemas(safe=True)

    async def _upsert(self, model, identity_field: str, payload: dict[str, Any]):
        identity = payload[identity_field]
        defaults = dict(payload)
        defaults.pop(identity_field, None)
        await model.update_or_create(defaults=defaults, **{identity_field: identity})

    def save_trade(self, trade: Trade):
        self._runner.run(self._save_trade(trade))

    async def _save_trade(self, trade: Trade):
        await self._upsert(TradeRecord, "trade_id", trade.to_record_payload())

    def save_daily_snapshot(self, perf: DailyPerformance):
        self._runner.run(self._save_daily_snapshot(perf))

    async def _save_daily_snapshot(self, perf: DailyPerformance):
        payload = perf.to_record_payload()
        trade_date = _as_date(payload["trade_date"])
        session_id = payload["session_id"]

        # Upsert by (session_id, trade_date) - one record per day per session
        existing = await DailyPerformanceRecord.filter(
            session_id=session_id, trade_date=trade_date
        ).first()

        if existing:
            # Update existing record, keep the same performance_id
            update_payload = {
                "portfolio_value": payload["portfolio_value"],
                "cash_balance": payload["cash_balance"],
                "position_value": payload["position_value"],
                "daily_return": payload.get("daily_return"),
                "cumulative_return": payload.get("cumulative_return"),
                "daily_pnl": payload.get("daily_pnl"),
                "num_positions": payload["num_positions"],
            }
            await DailyPerformanceRecord.filter(
                session_id=session_id, trade_date=trade_date
            ).update(**update_payload)
        else:
            # Create new record
            payload["trade_date"] = trade_date
            await DailyPerformanceRecord.create(**payload)

    def save_position_snapshot(self, snapshot: PositionSnapshot):
        self._runner.run(self._save_position_snapshot(snapshot))

    async def _save_position_snapshot(self, snapshot: PositionSnapshot):
        await self._upsert(
            PositionSnapshotRecord, "snapshot_id", snapshot.to_record_payload()
        )

    def save_session_state(self, state: Dict[str, Any]):
        self._runner.run(self._save_session_state(state))

    async def _save_session_state(self, state: Dict[str, Any]):
        normalized = normalize_jsonable_value(state)
        payload = {
            "session_id": normalized.get("session_id"),
            "state_data": normalized,
            "export_time": _as_datetime(normalized.get("export_time", datetime.now())),
        }
        await SessionStateRecord.create(**payload)

    def load_latest_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._runner.run(self._load_latest_session_state(session_id))

    async def _load_latest_session_state(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        row = (
            await SessionStateRecord.filter(session_id=session_id)
            .order_by("-export_time")
            .first()
        )
        return row.state_data if row else None

    def save_service_state(self, state: Dict[str, Any]):
        self._runner.run(self._save_service_state(state))

    async def _save_service_state(self, state: Dict[str, Any]):
        normalized = normalize_jsonable_value(state)
        await ServiceStateRecord.update_or_create(
            session_id=normalized.get("session_id"),
            defaults={
                "state_data": normalized,
                "export_time": _as_datetime(
                    normalized.get("export_time", datetime.now())
                ),
            },
        )

    def load_latest_service_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._runner.run(self._load_latest_service_state(session_id))

    async def _load_latest_service_state(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        row = await ServiceStateRecord.filter(session_id=session_id).first()
        return row.state_data if row else None

    def query_trades(self, session_id: str) -> pd.DataFrame:
        return self._runner.run(self._query_trades(session_id))

    async def _query_trades(self, session_id: str) -> pd.DataFrame:
        rows = (
            await TradeRecord.filter(session_id=session_id)
            .order_by("trade_date")
            .values()
        )
        return _as_dataframe(rows)

    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        return self._runner.run(self._query_daily_performance(session_id))

    async def _query_daily_performance(self, session_id: str) -> pd.DataFrame:
        rows = (
            await DailyPerformanceRecord.filter(session_id=session_id)
            .order_by("trade_date")
            .values()
        )
        return _as_dataframe(rows)

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        return self._runner.run(self._query_position_snapshots(session_id))

    async def _query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        rows = (
            await PositionSnapshotRecord.filter(session_id=session_id)
            .order_by("trade_date")
            .values()
        )
        return _as_dataframe(rows)

    def close(self):
        try:
            self._runner.run(self._close_orm())
        finally:
            self._runner.close()


class SQLiteOrderRecorder(TortoiseOrderRecorder):
    """SQLite-backed recorder for local paper trading."""

    def __init__(self, db_path: str = "order_records.db"):
        self.db_path = db_path
        super().__init__(db_url=_sqlite_db_url(db_path))


class PostgresOrderRecorder(TortoiseOrderRecorder):
    """Postgres-backed recorder for hosted databases such as MemFire Cloud."""

    def __init__(self, conninfo: str):
        self.conninfo = conninfo
        super().__init__(db_url=conninfo)


class MemFireCloudRecorder(PostgresOrderRecorder):
    """User-facing alias for a MemFire Cloud backed recorder."""

    def __init__(self, conninfo: str):
        super().__init__(conninfo=conninfo)
