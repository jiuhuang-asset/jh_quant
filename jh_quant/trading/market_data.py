"""Market data abstractions for historical/offline trading flows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import importlib
from typing import Dict, List, Optional, Set

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
    def __init__(self):
        self._backfill_from: Optional[str] = None

    def set_backfill_from(self, date: Optional[str]) -> None:
        """Set the backfill date to prevent look-ahead bias.

        When set, ``get_latest_prices()`` returns close prices as of this date
        instead of the most recent available prices.
        """
        self._backfill_from = date

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
    def get_trade_calendar(
        self,
    ) -> Set[str]:
        "交易日历"
        raise NotImplementedError


class JHMarketDataProvider(MarketDataProvider):
    """ 使用 aksahre 数据源"""
    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
    ):
        super().__init__()
        self.jhd = jhd or JHData(as_service=True)
        self.frequency = Frequency.from_value(frequency)
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
        to_df: bool = True,
    ) -> pd.DataFrame:
        """
        to_df: 是否转为DataFrame(JHData原生返回的是JHDataType而不是DataFrame)
        """
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return pd.DataFrame()

        data = self._fetch_hist_price_df(
            resolved_symbols=resolved_symbols,
            start_date=start_date,
            end_date=end_date,
            to_df=to_df,
        )
        if self._should_merge_spot(end_date):
            data = self._merge_today_spot_into_hist(
                hist_df=data,
                resolved_symbols=resolved_symbols,
            )
        return data

    def _fetch_hist_price_df(
        self,
        resolved_symbols: List[str],
        start_date: str,
        end_date: str,
        to_df: bool = True,
    ) -> pd.DataFrame:
        api_start = self._normalize_api_datetime(start_date, is_end=False)
        api_end = self._normalize_api_datetime(end_date, is_end=True)
        data = self.jhd.get_data(
            self.data_type,
            symbol=",".join(resolved_symbols),
            start=api_start,
            end=api_end,
        )
        return self._standardize_price_df(data, to_df=to_df)

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

    def _should_merge_spot(self, end_date: str) -> bool:
        if self.data_type != DataTypes.AK_STOCK_ZH_A_HIST:
            return False
        end_ts = pd.Timestamp(end_date)
        if end_ts.tzinfo is not None:
            end_ts = end_ts.tz_localize(None)
        return end_ts.normalize() == pd.Timestamp.now().normalize()

    def _merge_today_spot_into_hist(
        self,
        hist_df: pd.DataFrame,
        resolved_symbols: List[str],
    ) -> pd.DataFrame:
        spot_df = self._fetch_today_spot_df(resolved_symbols)
        if spot_df.empty:
            return hist_df
        if hist_df.empty:
            return spot_df

        combined = pd.concat([hist_df, spot_df], ignore_index=True, sort=False)
        combined["_date_key"] = pd.to_datetime(
            combined["date"], errors="coerce"
        ).dt.normalize()
        combined = combined.sort_values(["symbol", "_date_key"])
        combined = combined.drop_duplicates(subset=["symbol", "_date_key"], keep="last")
        combined = combined.drop(columns=["_date_key"], errors="ignore")
        return combined

    def _fetch_today_spot_df(self, resolved_symbols: List[str]) -> pd.DataFrame:
        fresh_after = self._get_today_spot_fresh_after()
        try:
            spot_data = self.jhd.get_data(
                DataTypes.AK_STOCK_ZH_A_SPOT,
                symbol=",".join(resolved_symbols),
                start=fresh_after.strftime("%Y-%m-%d %H:%M:%S"),
                bypass_cache=True,
            )
        except Exception:
            return pd.DataFrame()

        spot_df = self._standardize_price_df(spot_data)
        if spot_df.empty or "dt" not in spot_df.columns or "latest" not in spot_df.columns:
            return pd.DataFrame()

        spot_df = spot_df.copy()
        spot_df["dt"] = pd.to_datetime(spot_df["dt"], errors="coerce")
        if getattr(spot_df["dt"].dt, "tz", None) is not None:
            spot_df["dt"] = spot_df["dt"].dt.tz_localize(None)
        spot_df = spot_df.dropna(subset=["symbol", "dt"])
        spot_df = spot_df[spot_df["dt"] >= fresh_after]
        if spot_df.empty:
            return pd.DataFrame()

        spot_df = spot_df.sort_values(["symbol", "dt"]).drop_duplicates(
            subset=["symbol"], keep="last"
        )
        spot_df["date"] = spot_df["dt"].dt.normalize()
        spot_df["close"] = spot_df["latest"]
        spot_df["price"] = spot_df["close"]
        spot_df["volume"] = spot_df["volume"] / 100  # 股转化成手

        hist_columns = [
            "date",
            "symbol",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude",
            "pct_chg",
            "chg",
            "turnover_rate",
            "price",
        ]
        for column in hist_columns:
            if column not in spot_df.columns:
                spot_df[column] = pd.NA
        return spot_df[hist_columns].copy()

    def _get_today_spot_fresh_after(self) -> pd.Timestamp:
        now = pd.Timestamp.now()
        day = now.normalize()
        market_open = day + pd.Timedelta(hours=9, minutes=30)
        morning_close = day + pd.Timedelta(hours=11, minutes=30)
        afternoon_open = day + pd.Timedelta(hours=13)
        market_close = day + pd.Timedelta(hours=15)

        if now < market_open:
            fresh_after = market_open - pd.Timedelta(minutes=10)
        elif now <= morning_close:
            fresh_after = max(market_open, now - pd.Timedelta(minutes=10))
        elif now < afternoon_open:
            fresh_after = morning_close - pd.Timedelta(minutes=10)
        elif now <= market_close:
            fresh_after = max(afternoon_open, now - pd.Timedelta(minutes=10))
        else:
            fresh_after = market_close - pd.Timedelta(minutes=10)

        return fresh_after

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
        end_date = (
            self._backfill_from
            if self._backfill_from
            else pd.Timestamp.now().strftime("%Y-%m-%d")
        )
        price_df = self._get_price_df(
            symbols=symbols, start_date="1900-01-01", end_date=end_date, to_df=to_df
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
        to_df=True,
    ) -> pd.DataFrame:
        price_df = self._get_price_df(
            symbols=symbols, start_date=start_date, end_date=end_date, to_df=to_df
        )
        if price_df is None or price_df.empty:
            return pd.DataFrame()
        return price_df.sort_values(["symbol", "date"]).copy()

    def get_trade_calendar(self, start_date="2020-01-01"):
        "获取交易日历"
        data = self.jhd.get_data(
            DataTypes.AK_TOOL_TRADE_DATE_HIST_SINA,
            start=start_date,
        ).to_df()
        return set(data["trade_date"].tolist())


class XtQuantJHMarketDataProvider(JHMarketDataProvider):
    """JH historical data + xtquant full-tick spot overlay for today's prices."""

    def __init__(
        self,
        jhd: Optional[JHData] = None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
        *,
        xtdata_module=None,
        auto_connect: bool = True,
    ):
        super().__init__(
            jhd=jhd,
            frequency=frequency,
            default_symbols=default_symbols,
        )
        self._xtdata = xtdata_module or self._load_xtdata_module()
        self._xtdata_connected = False
        if auto_connect:
            self._ensure_xtdata_connected()

    @staticmethod
    def _load_xtdata_module():
        try:
            return importlib.import_module("xtquant.xtdata")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "xtquant.xtdata is not installed or not available in the current "
                "Python environment. Install xtquant and make sure MiniQMT is "
                "running before using XtQuantJHMarketDataProvider."
            ) from exc

    def _ensure_xtdata_connected(self) -> None:
        if self._xtdata_connected:
            return
        connect = getattr(self._xtdata, "connect", None)
        if callable(connect):
            connect()
        self._xtdata_connected = True

    @staticmethod
    def _normalize_symbol_for_xtquant(symbol: str) -> str:
        symbol = str(symbol).upper()
        if "." in symbol:
            return symbol
        if symbol.startswith(("5", "6", "9")):
            return f"{symbol}.SH"
        if symbol.startswith(("0", "1", "2", "3")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
        raise ValueError(
            f"Unable to infer exchange suffix for symbol '{symbol}'. "
            "Use a full xtquant code such as 600519.SH or 000001.SZ."
        )

    @staticmethod
    def _strip_market_suffix(stock_code: str) -> str:
        return str(stock_code).upper().split(".", 1)[0]

    @staticmethod
    def _parse_xtquant_timestamp(raw: dict) -> pd.Timestamp:
        if raw.get("time") is not None:
            return pd.to_datetime(raw["time"], unit="ms", errors="coerce")
        if raw.get("stime"):
            return pd.to_datetime(
                raw["stime"], format="%Y%m%d%H%M%S.%f", errors="coerce"
            )
        if raw.get("timetag"):
            return pd.to_datetime(raw["timetag"], errors="coerce")
        return pd.NaT

    def _fetch_today_spot_df(self, resolved_symbols: List[str]) -> pd.DataFrame:
        fresh_after = self._get_today_spot_fresh_after()
        try:
            self._ensure_xtdata_connected()
            xt_symbols = [
                self._normalize_symbol_for_xtquant(symbol)
                for symbol in resolved_symbols
            ]
            tick_map = self._xtdata.get_full_tick(xt_symbols) or {}
        except Exception:
            return pd.DataFrame()

        rows = []
        for xt_symbol, raw in tick_map.items():
            if not isinstance(raw, dict):
                continue
            dt = self._parse_xtquant_timestamp(raw)
            if pd.isna(dt):
                continue
            if getattr(dt, "tzinfo", None) is not None:
                dt = dt.tz_localize(None)

            last_price = raw.get("lastPrice")
            if last_price in (None, 0):
                continue

            last_close = raw.get("lastClose")
            high = raw.get("high")
            low = raw.get("low")
            chg = None
            pct_chg = None
            amplitude = None
            if last_close not in (None, 0):
                chg = float(last_price) - float(last_close)
                pct_chg = chg / float(last_close) * 100
                if high is not None and low is not None:
                    amplitude = (float(high) - float(low)) / float(last_close) * 100

            rows.append(
                {
                    "symbol": self._strip_market_suffix(xt_symbol),
                    "dt": dt,
                    "date": dt.normalize(),
                    "open": raw.get("open"),
                    "close": float(last_price),
                    "high": high,
                    "low": low,
                    # get_full_tick volume for QMT行情已是手, so do not divide by 100.
                    "volume": int(raw.get("volume", 0) or 0),
                    "amount": float(raw.get("amount", 0.0) or 0.0),
                    "amplitude": amplitude,
                    "pct_chg": pct_chg,
                    "chg": chg,
                    "turnover_rate": pd.NA,
                    "price": float(last_price),
                }
            )

        if not rows:
            return pd.DataFrame()

        spot_df = pd.DataFrame(rows)
        spot_df = spot_df.dropna(subset=["symbol", "dt"])
        spot_df = spot_df[spot_df["dt"] >= fresh_after]
        if spot_df.empty:
            return pd.DataFrame()

        spot_df = spot_df.sort_values(["symbol", "dt"]).drop_duplicates(
            subset=["symbol"], keep="last"
        )
        hist_columns = [
            "date",
            "symbol",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude",
            "pct_chg",
            "chg",
            "turnover_rate",
            "price",
        ]
        for column in hist_columns:
            if column not in spot_df.columns:
                spot_df[column] = pd.NA
        return spot_df[hist_columns].copy()
