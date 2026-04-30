"""Market data abstractions for historical/offline trading flows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from jh_quant.data import DataTypes, JHData

from .config import Frequency


@dataclass
class RealtimeQuote:
    symbol: str
    name: str
    price: float
    volume: int
    amount: float
    bid_prices: List[float]
    bid_volumes: List[int]
    ask_prices: List[float]
    ask_volumes: List[int]
    timestamp: datetime


@dataclass
class BarData:
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float

    @property
    def price(self) -> float:
        return float(self.close)


class MarketDataProvider(ABC):
    @abstractmethod
    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Return the latest known price for each requested symbol."""
        raise NotImplementedError

    @abstractmethod
    def get_price_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        """Return historical OHLCV-style data for the requested symbols/date range."""
        raise NotImplementedError
    
    @abstractmethod
    def get_index_trends(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Return historical index OHLCV-style data for the requested symbols/date range."""
        raise NotImplementedError

class JHMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
    ):
        self.jhd = jhd or JHData(as_service=True)
        self.frequency = Frequency.from_value(frequency)
        if self.frequency != Frequency.DAILY:
            self.data_type = DataTypes.AK_STOCK_ZH_A_SPOT
        else:
            self.data_type = DataTypes.AK_STOCK_ZH_A_HIST
        self.default_symbols = default_symbols or []

    def _resolve_symbols(self, symbols: Optional[List[str]]) -> List[str]:
        resolved = symbols or self.default_symbols
        return list(dict.fromkeys(resolved))

    def _get_price_df(
        self,
        symbols: Optional[List[str]],
        start_date: str,
        end_date: str,
        to_df: bool = True
    ) -> pd.DataFrame:
        """
        to_df: 是否转为DataFrame(JHData原生返回的是JHDataType而不是DataFrame)
        """
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return pd.DataFrame()

        api_start = self._normalize_api_datetime(start_date, is_end=False)
        api_end = self._normalize_api_datetime(end_date, is_end=True)

        data = self.jhd.get_data(
            self.data_type,
            symbol=",".join(resolved_symbols),
            start=api_start,
            end=api_end,
        )
        code_col, date_col = data.code_date_col
        if to_df:
            data = data.to_df()
        if "symbol" not in data.columns:
            data = data.rename(columns={code_col: "symbol"})
        if "date" not in data.columns:
            data = data.rename(columns={date_col: "date"})
        if "price" not in data.columns and "close" in data.columns:
            data["price"] = data["close"]
        return data

    def _normalize_api_datetime(self, value: str, *, is_end: bool) -> str:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)

        text = str(value)
        requires_time = self.data_type == DataTypes.AK_STOCK_ZH_A_SPOT

        if len(text.strip()) <= 10:
            timestamp = timestamp.normalize()
            if requires_time and is_end:
                timestamp += pd.Timedelta(hours=23, minutes=59, seconds=59)

        if requires_time:
            return timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return timestamp.strftime("%Y-%m-%d")

    def get_latest_prices(self, symbols: List[str], to_df=True) -> Dict[str, float]:
        price_df = self._get_price_df(
            symbols=symbols,
            start_date="1900-01-01",
            end_date="2099-12-31",
            to_df=to_df
        )
        if price_df is None or price_df.empty:
            return {}

        return (
            price_df.sort_values(["symbol", "date"])
            .groupby("symbol")["close"]
            .last()
            .to_dict()
        )

    def get_price_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
        to_df=True
    ) -> pd.DataFrame:
        price_df = self._get_price_df(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            to_df=to_df
        )
        if price_df is None or price_df.empty:
            return pd.DataFrame()
        return price_df.sort_values(["symbol", "date"]).copy()
    
    def get_index_trends(self, symbol, start_date, end_date):
        data = self.jhd.get_data(
            DataTypes.AK_STOCK_ZH_INDEX_DAILY_EM,
            symbol=symbol,
            start=start_date,
            end=end_date,
        ).to_df()
        if "chg" not in data.columns:
            data["chg"] = data["close"].pct_change() * 100
        return data.sort_values(["date"])


class WebSocketMarketDataProvider(MarketDataProvider):
    """Compatibility stub for quote-driven providers."""

    def __init__(self, ws_url: str, token: str):
        self.ws_url = ws_url
        self.token = token
        self._subscribed_symbols: List[str] = []
        self._latest_quotes: Dict[str, RealtimeQuote] = {}

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        return {
            symbol: quote.price
            for symbol, quote in self._latest_quotes.items()
            if symbol in symbols
        }

    def get_price_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        raise NotImplementedError(
            "WebSocket provider doesn't support historical price data. "
            "Use a historical data provider for backtesting."
        )

    def subscribe(self, symbols: List[str]) -> None:
        self._subscribed_symbols.extend(symbols)

    def unsubscribe(self, symbols: List[str]) -> None:
        self._subscribed_symbols = [
            symbol for symbol in self._subscribed_symbols if symbol not in symbols
        ]

    def on_quote_received(self, quote: RealtimeQuote) -> None:
        self._latest_quotes[quote.symbol] = quote