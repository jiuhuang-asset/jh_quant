from __future__ import annotations

from typing import List, Optional, Set

import pandas as pd

from jh_quant.data import DataTypes, JHData

from ..config import Frequency


class JHHistoricalBarProvider:
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
    ):
        # Prefer JHData auto mode so local direct cache works first and only
        # falls back to the sidecar service when the database is actually locked.
        self.jhd = jhd or JHData()
        self.frequency = Frequency.from_value(frequency)
        self.data_type = DataTypes.AK_STOCK_ZH_A_HIST
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
        data = self.jhd.get_data(
            self.data_type,
            symbol=",".join(resolved_symbols),
            start=api_start,
            end=api_end,
        )
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
        code_col, date_col = data.code_date_col
        if to_df:
            data = data.to_df()
        data = data.copy()
        if data.empty and len(data.columns) == 0:
            return data
        if "symbol" not in data.columns and code_col in data.columns:
            data["symbol"] = data[code_col]
        if "date" not in data.columns and date_col in data.columns:
            data["date"] = data[date_col]
        if "price" not in data.columns and "close" in data.columns:
            data["price"] = data["close"]
        return data

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


__all__ = ["JHHistoricalBarProvider"]
