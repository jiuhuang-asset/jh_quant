"""
Market data abstractions for historical and real-time trading flows.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional
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
        """Alias used by real-time style consumers."""
        return float(self.close)




class MarketDataProvider(ABC):
    @abstractmethod
    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        "方便交易策略获取最新价格"
        pass

    @abstractmethod
    def get_price_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        data = self.get_price_data(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )
        if "symbol" not in data.columns or "date" not in data.columns:
            raise ValueError("Price data must contain 'symbol' and 'date' columns")
        return data


    @abstractmethod
    def subscribe(self, symbols: List[str]) -> None:
        pass

    @abstractmethod
    def unsubscribe(self, symbols: List[str]) -> None:
        pass

    @abstractmethod
    def register_callback(self, callback: Callable[[RealtimeQuote], None]) -> None:
        pass


class WebSocketMarketDataProvider(MarketDataProvider):
    def __init__(self, ws_url: str, token: str):
        self.ws_url = ws_url
        self.token = token
        self._subscribed_symbols: List[str] = []
        self._callbacks: List[Callable[[RealtimeQuote], None]] = []
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

    def register_callback(self, callback: Callable[[RealtimeQuote], None]) -> None:
        self._callbacks.append(callback)

    def _on_quote_received(self, quote: RealtimeQuote) -> None:
        self._latest_quotes[quote.symbol] = quote
        for callback in self._callbacks:
            callback(quote)


class HistoricalDataProvider(MarketDataProvider):
    def __init__(self, data_getter=None):
        self.data_getter = data_getter

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        if self.data_getter is None:
            return {}

        price_data = self.data_getter.get_data(
            start_date="1900-01-01",
            end_date="2099-12-31",
        )
        if price_data is None or price_data.empty:
            return {}

        return (
            price_data[price_data["symbol"].isin(symbols)]
            .sort_values(["symbol", "date"])
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
    ) -> pd.DataFrame:
        if self.data_getter is None:
            return pd.DataFrame()

        price_data = self.data_getter.get_data(
            start_date=start_date,
            end_date=end_date,
        )
        if price_data is None or price_data.empty:
            return pd.DataFrame()

        price_data = price_data[price_data["symbol"].isin(symbols)]
        return price_data.sort_values(["symbol", "date"]).copy()

    def subscribe(self, symbols: List[str]) -> None:
        raise NotImplementedError(
            "Historical data provider doesn't support real-time subscription."
        )

    def unsubscribe(self, symbols: List[str]) -> None:
        return None

    def register_callback(self, callback: Callable[[RealtimeQuote], None]) -> None:
        raise NotImplementedError(
            "Historical data provider doesn't support real-time subscription."
        )


class JHMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
    ):
        self.jhd = jhd or JHData()
        self.frequency = Frequency.from_value(frequency)
        if self.frequency != Frequency.DAILY:
            self.data_type = DataTypes.AK_STOCK_ZH_A_SPOT
        else:
            self.data_type = DataTypes.AK_STOCK_ZH_A_HIST
        self.default_symbols = default_symbols or []
        self._callbacks: List[Callable[[RealtimeQuote], None]] = []

    def _resolve_symbols(self, symbols: Optional[List[str]]) -> List[str]:
        resolved = symbols or self.default_symbols
        return list(dict.fromkeys(resolved))

    def _get_price_df(
        self,
        symbols: Optional[List[str]],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return pd.DataFrame()

        api_start = self._normalize_api_datetime(start_date, is_end=False)
        api_end = self._normalize_api_datetime(end_date, is_end=True)

        data =  self.jhd.get_data(
            self.data_type,
            symbol=",".join(resolved_symbols),
            start=api_start,
            end=api_end,
        )
        code_col, date_col = data.code_date_col 
        data = data.to_df()
        # symbol, date 是标准列名，适配不同数据源的列名差异
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

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        price_df = self._get_price_df(
            symbols=symbols,
            start_date="1900-01-01",
            end_date="2099-12-31",
            # frequency=self.frequency,
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
    ) -> pd.DataFrame:
        price_df = self._get_price_df(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )
        if price_df is None or price_df.empty:
            return pd.DataFrame()
        return price_df.sort_values(["symbol", "date"]).copy()

    def subscribe(self, symbols: List[str]) -> None:
        raise NotImplementedError("JHMarketDataProvider doesn't support real-time subscription")

    def unsubscribe(self, symbols: List[str]) -> None:
        return None

    def register_callback(self, callback: Callable[[RealtimeQuote], None]) -> None:
        self._callbacks.append(callback)
