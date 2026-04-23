"""
Market data abstractions for historical and real-time trading flows.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional
from enum import Enum
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

    @property
    def price(self) -> float:
        """Alias used by real-time style consumers."""
        return float(self.close)


class Frequency(Enum):
    DAILY = "1d"
    MINUTE_1 = "1min"
    MINUTE_5 = "5min"
    MINUTE_15 = "15min"
    MINUTE_30 = "30min"
    MINUTE_60 = "60min"
    HOUR_1 = "1hour"

    @classmethod
    def from_value(cls, value: "Frequency | str | None") -> "Frequency":
        if isinstance(value, cls):
            return value

        mapping = {
            None: cls.DAILY,
            "daily": cls.DAILY,
            "day": cls.DAILY,
            "1day": cls.DAILY,
            "1d": cls.DAILY,
            "1min": cls.MINUTE_1,
            "1m": cls.MINUTE_1,
            "5min": cls.MINUTE_5,
            "5m": cls.MINUTE_5,
            "15min": cls.MINUTE_15,
            "15m": cls.MINUTE_15,
            "30min": cls.MINUTE_30,
            "30m": cls.MINUTE_30,
            "60min": cls.MINUTE_60,
            "60m": cls.MINUTE_60,
            "1hour": cls.HOUR_1,
            "1h": cls.HOUR_1,
        }
        normalized = mapping.get(str(value).lower() if value is not None else None)
        if normalized is None:
            raise ValueError(f"Unsupported frequency: {value}")
        return normalized

class MarketDataProvider(ABC):
    @abstractmethod
    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        "方便交易策略获取最新价格"
        pass

    @abstractmethod
    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
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
        frequency: Frequency = Frequency.DAILY,
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
        frequency: Frequency = Frequency.DAILY,
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
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
    ):
        self.jhd = jhd or JHData()
        if frequency  != Frequency.DAILY:
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

        code_col, date_col = data.code_dt_col 
        
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

    def _row_to_bar(self, row: pd.Series) -> BarData:
        close_price = float(row.get("close", row.get("price", 0.0)))
        open_price = float(row.get("open", close_price))
        high_price = float(row.get("high", max(open_price, close_price)))
        low_price = float(row.get("low", min(open_price, close_price)))
        volume = int(row.get("volume", 0) or 0)
        amount = float(row.get("amount", close_price * volume))
        return BarData(
            symbol=row["symbol"],
            datetime=pd.to_datetime(row["date"]),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            amount=amount,
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
        frequency: Frequency = Frequency.DAILY,
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
            result[symbol] = [self._row_to_bar(row) for _, row in symbol_data.iterrows()]
        return result

    def subscribe(self, symbols: List[str]) -> None:
        raise NotImplementedError("JHMarketData doesn't support real-time subscription")

    def unsubscribe(self, symbols: List[str]) -> None:
        return None

    def register_callback(self, callback: Callable[[RealtimeQuote], None]) -> None:
        self._callbacks.append(callback)
