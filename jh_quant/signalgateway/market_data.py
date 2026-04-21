"""
Market data abstractions for historical and real-time trading flows.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

import pandas as pd

from jh_quant.data import DataTypes, JHData


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


class MarketDataProvider(ABC):
    @abstractmethod
    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        pass

    @abstractmethod
    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
    ) -> Dict[str, List[BarData]]:
        pass

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

    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
    ) -> Dict[str, List[BarData]]:
        raise NotImplementedError(
            "WebSocket provider doesn't support historical bars. "
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

    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
    ) -> Dict[str, List[BarData]]:
        if self.data_getter is None:
            return {}

        price_data = self.data_getter.get_data(
            start_date=start_date,
            end_date=end_date,
        )
        if price_data is None or price_data.empty:
            return {}

        price_data = price_data[price_data["symbol"].isin(symbols)]
        result: Dict[str, List[BarData]] = {}
        for symbol in symbols:
            symbol_data = price_data[price_data["symbol"] == symbol].sort_values("date")
            result[symbol] = [
                BarData(
                    symbol=row["symbol"],
                    datetime=pd.to_datetime(row["date"]),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    amount=row["amount"],
                )
                for _, row in symbol_data.iterrows()
            ]
        return result

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


class JHMarketData(MarketDataProvider):
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        data_type: DataTypes = DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
        default_symbols: Optional[List[str]] = None,
    ):
        self.jhd = jhd or JHData()
        self.data_type = data_type
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
        frequency: str = "1d",
    ) -> pd.DataFrame:
        if frequency != "1d":
            raise NotImplementedError("JHMarketData currently supports daily bars only")

        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return pd.DataFrame()

        return self.jhd.get_data(
            self.data_type,
            symbol=",".join(resolved_symbols),
            start=start_date,
            end=end_date,
        )

    def get_price_df(
        self,
        symbols: Optional[List[str]],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
    ) -> pd.DataFrame:
        return self._get_price_df(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
        )

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        price_df = self._get_price_df(
            symbols=symbols,
            start_date="1900-01-01",
            end_date="2099-12-31",
        )
        if price_df is None or price_df.empty:
            return {}

        return (
            price_df.sort_values(["symbol", "date"])
            .groupby("symbol")["close"]
            .last()
            .to_dict()
        )

    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
    ) -> Dict[str, List[BarData]]:
        price_df = self._get_price_df(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
        )
        if price_df is None or price_df.empty:
            return {}

        result: Dict[str, List[BarData]] = {}
        ordered_symbols = self._resolve_symbols(symbols)
        for symbol in ordered_symbols:
            symbol_data = price_df[price_df["symbol"] == symbol].sort_values("date")
            result[symbol] = [
                BarData(
                    symbol=row["symbol"],
                    datetime=pd.to_datetime(row["date"]),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    amount=row["amount"],
                )
                for _, row in symbol_data.iterrows()
            ]
        return result

    def subscribe(self, symbols: List[str]) -> None:
        raise NotImplementedError("JHMarketData doesn't support real-time subscription")

    def unsubscribe(self, symbols: List[str]) -> None:
        return None

    def register_callback(self, callback: Callable[[RealtimeQuote], None]) -> None:
        self._callbacks.append(callback)
