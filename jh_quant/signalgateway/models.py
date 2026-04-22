"""
Core domain and persistence models for the signalgateway trading system.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from tortoise import fields
    from tortoise.models import Model as TortoiseModel

    TORTOISE_ORM_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency at runtime
    fields = None
    TortoiseModel = object
    TORTOISE_ORM_AVAILABLE = False


def require_tortoise_orm() -> None:
    if not TORTOISE_ORM_AVAILABLE:
        raise ImportError(
            "tortoise-orm is required to use signalgateway persistence recorders"
        )


def normalize_persistence_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_persistence_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_persistence_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime()
        except TypeError:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return value


def normalize_jsonable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_jsonable_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_jsonable_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class PersistenceModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_record_payload(self) -> dict[str, Any]:
        return {
            key: normalize_persistence_value(value)
            for key, value in self.model_dump().items()
        }


class StockHoldRecord(BaseModel):
    """Holding record kept in memory."""

    symbol: str
    volume: int
    avg_cost: float = 0.0
    market_value: float = 0.0
    buy_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


class Positions(BaseModel):
    """Portfolio snapshot."""

    total: float
    available_balance: float
    total_profit: Optional[float] = None
    daily_profit: Optional[float] = None
    holds: List[StockHoldRecord]


class Order(BaseModel):
    """Order request."""

    symbol: str
    price: float
    volume: int
    trade_type: str = "BUY"


class Trade(PersistenceModel):
    """Executed trade."""

    trade_id: str
    session_id: str
    trade_date: pd.Timestamp | str
    symbol: str
    trade_type: str
    price: float
    quantity: int
    amount: float
    commission: float = 0.0
    slippage: float = 0.0
    total_cost: float
    signal_reason: Optional[str] = None
    order_id: Optional[str] = None

    @field_validator("trade_date", mode="before")
    @classmethod
    def _coerce_trade_date(cls, value):
        if isinstance(value, str):
            return pd.Timestamp(value)
        return value


class DailyPerformance(PersistenceModel):
    """Daily portfolio performance snapshot."""

    performance_id: str
    session_id: str
    trade_date: pd.Timestamp
    portfolio_value: float
    cash_balance: float
    position_value: float
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    daily_pnl: Optional[float] = None
    num_positions: int = 0


class PositionSnapshot(PersistenceModel):
    """Persisted position snapshot."""

    snapshot_id: str
    session_id: str
    trade_date: pd.Timestamp
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None


if TORTOISE_ORM_AVAILABLE:

    class TradeRecord(TortoiseModel):
        trade_id = fields.CharField(max_length=128, pk=True)
        session_id = fields.CharField(max_length=128, index=True)
        trade_date = fields.DatetimeField()
        symbol = fields.CharField(max_length=32)
        trade_type = fields.CharField(max_length=16)
        price = fields.FloatField()
        quantity = fields.IntField()
        amount = fields.FloatField()
        commission = fields.FloatField(default=0.0)
        slippage = fields.FloatField(default=0.0)
        total_cost = fields.FloatField()
        signal_reason = fields.TextField(null=True)
        order_id = fields.CharField(max_length=128, null=True)
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "trades"
            ordering = ["trade_date"]
            indexes = [("session_id", "trade_date")]


    class DailyPerformanceRecord(TortoiseModel):
        performance_id = fields.CharField(max_length=128, pk=True)
        session_id = fields.CharField(max_length=128, index=True)
        trade_date = fields.DateField()
        portfolio_value = fields.FloatField()
        cash_balance = fields.FloatField()
        position_value = fields.FloatField()
        daily_return = fields.FloatField(null=True)
        cumulative_return = fields.FloatField(null=True)
        daily_pnl = fields.FloatField(null=True)
        num_positions = fields.IntField(default=0)
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "daily_performances"
            ordering = ["trade_date"]
            indexes = [("session_id", "trade_date")]


    class PositionSnapshotRecord(TortoiseModel):
        snapshot_id = fields.CharField(max_length=128, pk=True)
        session_id = fields.CharField(max_length=128, index=True)
        trade_date = fields.DatetimeField()
        symbol = fields.CharField(max_length=32)
        quantity = fields.IntField()
        avg_cost = fields.FloatField()
        current_price = fields.FloatField()
        market_value = fields.FloatField()
        pnl = fields.FloatField(null=True)
        pnl_pct = fields.FloatField(null=True)
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "positions_snapshot"
            ordering = ["trade_date"]
            indexes = [("session_id", "trade_date")]


    class SessionStateRecord(TortoiseModel):
        id = fields.IntField(pk=True)
        session_id = fields.CharField(max_length=128, index=True)
        state_data = fields.JSONField()
        export_time = fields.DatetimeField()
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "session_states"
            ordering = ["-export_time"]
            unique_together = (("session_id", "export_time"),)
            indexes = [("session_id", "export_time")]


    class ServiceStateRecord(TortoiseModel):
        session_id = fields.CharField(max_length=128, pk=True)
        state_data = fields.JSONField()
        export_time = fields.DatetimeField()
        created_at = fields.DatetimeField(auto_now_add=True)

        class Meta:
            table = "session_service_states"
            indexes = [("session_id", "export_time")]

else:

    class TradeRecord:  # pragma: no cover - import fallback
        pass


    class DailyPerformanceRecord:  # pragma: no cover - import fallback
        pass


    class PositionSnapshotRecord:  # pragma: no cover - import fallback
        pass


    class SessionStateRecord:  # pragma: no cover - import fallback
        pass


    class ServiceStateRecord:  # pragma: no cover - import fallback
        pass
