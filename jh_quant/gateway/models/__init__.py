"""
Core domain models for the signalgateway trading system.

Model overview
--------------
``SelectionSnapshot`` — dataclass, carries a universe of symbols selected for a cycle.
    Returned by ``SelectionProvider.select()``. Lightweight, no persistence.

``StockHoldRecord`` — in-memory holding kept inside OMS (Pydantic BaseModel).
    Tracks symbol / volume / avg_cost / market_value / entry_time for one position.
    ``entry_time`` is a ``datetime`` with second-level precision so that (a) T+1 gates
    can operate on the date component, and (b) risk-rule replay can use the full
    timestamp when filtering price bars.

``Positions`` — portfolio snapshot (BaseModel). Aggregates total equity, available
    balance, profit fields, and the current ``holds`` list. Built on-demand by OMS.

``Order`` — transient request sent to OMS (BaseModel). Contains symbol, price,
    volume, trade_type (BUY / SELL), and an optional signal_reason. Never persisted
    directly — the resulting ``Trade`` is the persisted artifact.

``Trade`` — persisted executed-trade record (PersistenceModel). ``trade_date`` is
    stored as ``pd.Timestamp`` (coerced from string if needed), giving second-level
    precision. Persisted to the ``trades`` table with a ``DatetimeField``.

``DailyPerformance`` — persisted daily portfolio snapshot (PersistenceModel).
    ``trade_date`` is ``pd.Timestamp`` but upserted by *date component only*
    (``DateField`` in the DB), so there is one row per calendar day.

``PositionSnapshot`` — persisted per-holding snapshot (PersistenceModel).
    ``trade_date`` is ``pd.Timestamp``, stored as ``DatetimeField``.

``PersistenceModel`` — mixin that adds ``to_record_payload()``, which normalizes
    ``pd.Timestamp`` → Python ``datetime`` before persistence.

Date / time conventions
-----------------------
- All *in-memory* date-time fields use ``datetime`` (``StockHoldRecord.entry_time``)
  or ``pd.Timestamp`` (``Trade.trade_date``, ``DailyPerformance.trade_date``,
  ``PositionSnapshot.trade_date``). Both carry second-level precision.
- Format conversions happen at system boundaries only:
  * Serialization (JSON / state export): ``.isoformat()``
  * Persistence payloads: ``normalize_persistence_value`` converts
    ``pd.Timestamp`` → ``datetime``; ``DatetimeField`` / ``DateField`` handle
    the rest.
  * API-facing date strings (``as_of_date``, ``start_date``, ``end_date``)
    remain ``"YYYY-MM-DD"`` because they represent calendar-day parameters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


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


@dataclass
class SelectionSnapshot:
    top_selections: List[str]
    bottom_selections: List[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class StockHoldRecord(BaseModel):
    """Holding record kept in memory.

    ``entry_time`` carries second-level precision so that T+1 gates can
    use the date component while risk-rule replay can filter price bars
    with the full timestamp.
    """

    symbol: str
    volume: int
    avg_cost: float = 0.0
    market_value: float = 0.0
    entry_time: datetime = Field(default_factory=datetime.now)


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
    signal_reason: Optional[str] = None


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


__all__ = [
    "DailyPerformance",
    "Order",
    "PersistenceModel",
    "PositionSnapshot",
    "Positions",
    "SelectionSnapshot",
    "StockHoldRecord",
    "Trade",
    "normalize_jsonable_value",
    "normalize_persistence_value",
]
