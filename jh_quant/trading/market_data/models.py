from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TradingPhase(str, Enum):
    PRE_OPEN = "pre_open"
    CALL_AUCTION = "call_auction"
    CONTINUOUS = "continuous"
    LUNCH_BREAK = "lunch_break"
    CLOSED = "closed"
    AFTER_HOURS = "after_hours"


@dataclass
class QuoteSnapshot:
    symbol: str
    last_price: float
    timestamp: datetime
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    bid_prices: list[float] = field(default_factory=list)
    bid_volumes: list[int] = field(default_factory=list)
    ask_prices: list[float] = field(default_factory=list)
    ask_volumes: list[int] = field(default_factory=list)
    limit_up: Optional[float] = None
    limit_down: Optional[float] = None
    trading_phase: Optional[str] = None
    turnover_rate: Optional[float] = None
    name: Optional[str] = None


@dataclass
class InstrumentMeta:
    symbol: str
    exchange: str
    lot_size: int = 100
    price_tick: float = 0.01
    security_type: str = "stock"
    is_t0: bool = False
    allow_short: bool = False
    name: Optional[str] = None


@dataclass
class MarketStatus:
    trading_day: str
    is_open: bool
    phase: str
    timestamp: datetime


__all__ = [
    "InstrumentMeta",
    "MarketStatus",
    "QuoteSnapshot",
    "TradingPhase",
]
