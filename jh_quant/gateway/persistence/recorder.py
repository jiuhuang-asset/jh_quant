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

from ..models import (
    DailyPerformance,
    PositionSnapshot,
    Trade,
    normalize_jsonable_value,
)
from .models import (
    DailyPerformanceRecord,
    PositionSnapshotRecord,
    RuntimeEventRecord,
    RuntimeStateRecord,
    SessionStateRecord,
    TradeRecord,
    UserConfigRecord,
    require_tortoise_orm,
)
from .protocols import (
    PerformancePersistence,
    PositionPersistence,
    ServiceStatePersistence,
    SessionStatePersistence,
    TradePersistence,
)


def _module_path() -> str:
    return (
        f"{__package__}.models"
        if __package__
        else "jh_quant.gateway.persistence.models"
    )


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


def _daily_performance_update_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "portfolio_value": payload["portfolio_value"],
        "cash_balance": payload["cash_balance"],
        "position_value": payload["position_value"],
        "daily_return": payload.get("daily_return"),
        "cumulative_return": payload.get("cumulative_return"),
        "daily_pnl": payload.get("daily_pnl"),
        "num_positions": payload["num_positions"],
    }


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
    def save_runtime_state(self, state: Dict[str, Any]):
        raise NotImplementedError

    @abstractmethod
    def load_latest_runtime_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def query_runtime_events(self, session_id: str) -> pd.DataFrame:
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

    @abstractmethod
    def save_user_config(
        self,
        session_id: str,
        config_bundle: Dict[str, Any],
        *,
        source: str = "runtime_update",
    ):
        raise NotImplementedError

    @abstractmethod
    def load_latest_user_config(self, session_id: str) -> Optional[Dict[str, Any]]:
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
        self._run(self._init_orm())

    def _run(self, coro: Awaitable[Any]) -> Any:
        return self._runner.run(coro)

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
        self._run(self._create_schema())

    async def _create_schema(self):
        from tortoise import Tortoise

        await Tortoise.generate_schemas(safe=True)

    async def _upsert(self, model, identity_field: str, payload: dict[str, Any]):
        identity = payload[identity_field]
        defaults = dict(payload)
        defaults.pop(identity_field, None)
        await model.update_or_create(defaults=defaults, **{identity_field: identity})

    async def _save_by_identity(
        self,
        model,
        identity_field: str,
        payload: dict[str, Any],
    ) -> None:
        await self._upsert(model, identity_field, payload)

    async def _query_session_records(
        self,
        model,
        session_id: str,
        *,
        order_by: str = "trade_date",
    ) -> pd.DataFrame:
        rows = await model.filter(session_id=session_id).order_by(order_by).values()
        return _as_dataframe(rows)

    async def _load_latest_state_record(
        self,
        model,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        row = await model.filter(session_id=session_id).order_by("-export_time").first()
        return row.state_data if row else None

    def save_trade(self, trade: Trade):
        self._run(self._save_trade(trade))

    async def _save_trade(self, trade: Trade):
        await self._save_by_identity(TradeRecord, "trade_id", trade.to_record_payload())

    def save_daily_snapshot(self, perf: DailyPerformance):
        self._run(self._save_daily_snapshot(perf))

    async def _save_daily_snapshot(self, perf: DailyPerformance):
        payload = perf.to_record_payload()
        trade_date = _as_date(payload["trade_date"])
        session_id = payload["session_id"]
        update_payload = _daily_performance_update_payload(payload)

        # Upsert by (session_id, trade_date) while preserving the original performance_id.
        existing = await DailyPerformanceRecord.filter(
            session_id=session_id, trade_date=trade_date
        ).first()

        if existing:
            await DailyPerformanceRecord.filter(
                session_id=session_id, trade_date=trade_date
            ).update(**update_payload)
        else:
            payload["trade_date"] = trade_date
            await DailyPerformanceRecord.create(**payload)

    def save_position_snapshot(self, snapshot: PositionSnapshot):
        self._run(self._save_position_snapshot(snapshot))

    async def _save_position_snapshot(self, snapshot: PositionSnapshot):
        await self._save_by_identity(
            PositionSnapshotRecord, "snapshot_id", snapshot.to_record_payload()
        )

    def save_session_state(self, state: Dict[str, Any]):
        self._run(self._save_session_state(state))

    async def _save_session_state(self, state: Dict[str, Any]):
        normalized = normalize_jsonable_value(state)
        payload = {
            "session_id": normalized.get("session_id"),
            "state_data": normalized,
            "export_time": _as_datetime(normalized.get("export_time", datetime.now())),
        }
        await SessionStateRecord.create(**payload)

    def load_latest_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._run(self._load_latest_session_state(session_id))

    async def _load_latest_session_state(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        return await self._load_latest_state_record(SessionStateRecord, session_id)

    def save_runtime_state(self, state: Dict[str, Any]):
        self._run(self._save_runtime_state(state))

    async def _save_runtime_state(self, state: Dict[str, Any]):
        normalized = normalize_jsonable_value(state)
        event_type = (
            normalized.get("service", {})
            .get("extra", {})
            .get("event", "service_state_snapshot")
        )
        export_time = _as_datetime(
            normalized.get("export_time", datetime.now())
        )
        await RuntimeStateRecord.update_or_create(
            session_id=normalized.get("session_id"),
            defaults={
                "state_data": normalized,
                "export_time": export_time,
            },
        )
        await RuntimeEventRecord.create(
            session_id=normalized.get("session_id"),
            event_type=event_type,
            state_data=normalized,
            event_time=export_time,
        )

    def load_latest_runtime_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._run(self._load_latest_runtime_state(session_id))

    async def _load_latest_runtime_state(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        return await self._load_latest_state_record(RuntimeStateRecord, session_id)

    def save_user_config(
        self,
        session_id: str,
        config_bundle: Dict[str, Any],
        *,
        source: str = "runtime_update",
    ):
        self._run(self._save_user_config(session_id, config_bundle, source=source))

    async def _save_user_config(
        self,
        session_id: str,
        config_bundle: Dict[str, Any],
        *,
        source: str = "runtime_update",
    ):
        normalized_bundle = normalize_jsonable_value(config_bundle)
        export_time = _as_datetime(
            normalized_bundle.get("export_time", datetime.now())
        )
        await UserConfigRecord.update_or_create(
            session_id=session_id,
            defaults={
                "config_bundle": normalized_bundle,
                "source": source,
                "export_time": export_time,
            },
        )

    def load_latest_user_config(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._run(self._load_latest_user_config(session_id))

    async def _load_latest_user_config(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        row = await UserConfigRecord.filter(session_id=session_id).order_by("-export_time").first()
        if row is None:
            return None
        return {
            "session_id": row.session_id,
            "config_bundle": row.config_bundle,
            "source": row.source,
            "export_time": row.export_time.isoformat(),
        }

    def query_runtime_events(self, session_id: str) -> pd.DataFrame:
        return self._run(self._query_runtime_events(session_id))

    async def _query_runtime_events(self, session_id: str) -> pd.DataFrame:
        return await self._query_session_records(
            RuntimeEventRecord,
            session_id,
            order_by="event_time",
        )

    def query_trades(self, session_id: str) -> pd.DataFrame:
        return self._run(self._query_trades(session_id))

    async def _query_trades(self, session_id: str) -> pd.DataFrame:
        return await self._query_session_records(TradeRecord, session_id)

    def query_daily_performance(self, session_id: str) -> pd.DataFrame:
        return self._run(self._query_daily_performance(session_id))

    async def _query_daily_performance(self, session_id: str) -> pd.DataFrame:
        return await self._query_session_records(DailyPerformanceRecord, session_id)

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        return self._run(self._query_position_snapshots(session_id))

    async def _query_position_snapshots(self, session_id: str) -> pd.DataFrame:
        return await self._query_session_records(PositionSnapshotRecord, session_id)

    def close(self):
        try:
            self._run(self._close_orm())
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
