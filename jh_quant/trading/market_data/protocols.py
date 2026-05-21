from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Protocol, Set, runtime_checkable

import pandas as pd

from ..config import Frequency
from .models import InstrumentMeta, MarketStatus, QuoteSnapshot


@runtime_checkable
class HistoricalBarProvider(Protocol):
    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        raise NotImplementedError


@runtime_checkable
class RealtimeQuoteProvider(Protocol):
    def get_quote_snapshots(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        raise NotImplementedError


@runtime_checkable
class LatestQuoteProvider(Protocol):
    def get_latest_quotes(
        self,
        symbols: List[str],
        as_of_date: Optional[str | datetime | pd.Timestamp] = None,
    ) -> Dict[str, QuoteSnapshot]:
        raise NotImplementedError


@runtime_checkable
class TradingCalendarProvider(Protocol):
    def get_trade_calendar(
        self,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ) -> Set[str]:
        raise NotImplementedError

    def is_trading_day(self, date: str) -> bool:
        raise NotImplementedError


@runtime_checkable
class InstrumentProvider(Protocol):
    def get_instruments(self, symbols: List[str]) -> Dict[str, InstrumentMeta]:
        raise NotImplementedError


@runtime_checkable
class MarketStatusProvider(Protocol):
    def get_market_status(self, now: Optional[datetime] = None) -> MarketStatus:
        raise NotImplementedError


@runtime_checkable
class ReferenceTimeAware(Protocol):
    def set_reference_time(
        self,
        value: Optional[str | datetime | pd.Timestamp],
    ) -> None:
        raise NotImplementedError


@runtime_checkable
class MarketDataService(Protocol):
    def get_price_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        raise NotImplementedError

    def get_latest_prices(
        self,
        symbols: List[str],
        as_of_date: Optional[str] = None,
    ) -> Dict[str, float]:
        raise NotImplementedError

    def get_trade_calendar(
        self,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ) -> Set[str]:
        raise NotImplementedError


__all__ = [
    "HistoricalBarProvider",
    "InstrumentProvider",
    "LatestQuoteProvider",
    "MarketDataService",
    "MarketStatusProvider",
    "ReferenceTimeAware",
    "RealtimeQuoteProvider",
    "TradingCalendarProvider",
]
