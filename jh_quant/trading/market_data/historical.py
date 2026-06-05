from __future__ import annotations

from typing import List, Optional, Set

import pandas as pd

from jh_quant.data import DataTypes, JHData

from ..config import Frequency
from .adapters import to_trading_price_frame


def to_tushare_symbol(symbol: str) -> str:
    text = str(symbol).strip()
    if "." in text:
        return text.upper()
    if text.startswith(("6", "5", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "1", "2", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8")):
        return f"{text}.BJ"
    return text


class JHHistoricalBarProvider:
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
        data_type: DataTypes = DataTypes.AK_STOCK_ZH_A_HIST,
        source: str = "akshare",
    ):
        # Prefer JHData auto mode so local direct cache works first and only
        # falls back to the sidecar service when the database is actually locked.
        self.jhd = jhd or JHData()
        self.frequency = Frequency.from_value(frequency)
        self.data_type = data_type
        self.source = source
        self.default_symbols = default_symbols or []

    def _resolve_symbols(self, symbols: Optional[List[str]]) -> List[str]:
        resolved = symbols or self.default_symbols
        return list(dict.fromkeys(resolved))

    def get_bars(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return pd.DataFrame()

        api_start = self._normalize_api_datetime(start_date, is_end=False)
        api_end = self._normalize_api_datetime(end_date, is_end=True)
        kwargs = self._build_query_kwargs(resolved_symbols, api_start, api_end)
        data = self.jhd.get_data(self.data_type, **kwargs)
        return self._standardize_price_df(data)

    def get_trade_calendar(
        self,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ) -> Set[str]:
        data = self.jhd.get_data(
            DataTypes.AK_TOOL_TRADE_DATE_HIST_SINA,
            start=start_date,
            end=end_date,
        ).to_df()
        return set(data["trade_date"].tolist())

    def is_trading_day(self, date: str) -> bool:
        return date in self.get_trade_calendar(start_date=date, end_date=date)

    def _standardize_price_df(self, data, to_df: bool = True) -> pd.DataFrame:
        if to_df:
            code_col, date_col = data.code_date_col
            data = data.to_df()
        else:
            code_col, date_col = "symbol", "date"
        data = data.copy()
        if data.empty and len(data.columns) == 0:
            return data
        if "symbol" not in data.columns and code_col in data.columns:
            data["symbol"] = data[code_col]
        if "date" not in data.columns and date_col in data.columns:
            data["date"] = data[date_col]
        if "price" not in data.columns and "close" in data.columns:
            data["price"] = data["close"]
        return to_trading_price_frame(data)

    def _build_query_kwargs(
        self,
        symbols: List[str],
        api_start: str,
        api_end: str,
    ) -> dict:
        if self.source == "tushare":
            return {
                "ts_code": ",".join(to_tushare_symbol(symbol) for symbol in symbols),
                "start": api_start,
                "end": api_end,
            }
        return {
            "symbol": ",".join(symbols),
            "start": api_start,
            "end": api_end,
        }

    def _normalize_api_datetime(self, value: str, *, is_end: bool) -> str:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)

        text = str(value)
        if len(text.strip()) <= 10:
            timestamp = timestamp.normalize()
            if is_end:
                timestamp += pd.Timedelta(hours=23, minutes=59, seconds=59)

        return timestamp.strftime("%Y-%m-%d")


class AkShareHistoricalBarProvider(JHHistoricalBarProvider):
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
        data_type: DataTypes = DataTypes.AK_STOCK_ZH_A_HIST,
    ):
        super().__init__(
            jhd=jhd,
            frequency=frequency,
            default_symbols=default_symbols,
            data_type=data_type,
            source="akshare",
        )


class TuShareHistoricalBarProvider(JHHistoricalBarProvider):
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
        data_type: DataTypes = DataTypes.TS_DAILY,
    ):
        super().__init__(
            jhd=jhd,
            frequency=frequency,
            default_symbols=default_symbols,
            data_type=data_type,
            source="tushare",
        )


__all__ = [
    "AkShareHistoricalBarProvider",
    "JHHistoricalBarProvider",
    "TuShareHistoricalBarProvider",
    "to_tushare_symbol",
]
