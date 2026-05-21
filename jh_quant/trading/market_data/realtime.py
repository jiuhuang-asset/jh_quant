from __future__ import annotations

import importlib
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from jh_quant.data import DataTypes, JHData

from .models import QuoteSnapshot


class AkShareRealtimeQuoteProvider:
    def __init__(self, jhd: Optional[JHData] = None):
        self.jhd = jhd or JHData(as_service=True)

    def _normalize_spot_df(self, data) -> pd.DataFrame:
        code_col, date_col = data.code_date_col
        df = data.to_df().copy()
        if df.empty:
            return df
        if "symbol" not in df.columns and code_col in df.columns:
            df["symbol"] = df[code_col]
        if "dt" not in df.columns and date_col in df.columns:
            df["dt"] = df[date_col]
        if "latest" in df.columns and "close" not in df.columns:
            df["close"] = df["latest"]
        if "price" not in df.columns and "close" in df.columns:
            df["price"] = df["close"]
        df["dt"] = pd.to_datetime(df.get("dt"), errors="coerce")
        if "date" not in df.columns:
            df["date"] = df["dt"].dt.normalize()
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce") / 100.0
        return df

    def get_spot_dataframe(
        self,
        symbols: List[str],
        *,
        fresh_after: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()

        data = self.jhd.get_data(
            DataTypes.AK_STOCK_ZH_A_SPOT,
            symbol=",".join(symbols),
            bypass_cache=True,
        )
        df = self._normalize_spot_df(data)
        if df.empty:
            return df
        if fresh_after is not None and "dt" in df.columns:
            df = df.loc[df["dt"] >= fresh_after].copy()
        return df.sort_values(["symbol", "dt"]).reset_index(drop=True)

    def get_quote_snapshots(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        df = self.get_spot_dataframe(symbols)
        if df.empty:
            return {}
        latest_rows = df.groupby("symbol", as_index=False).tail(1)
        quotes: Dict[str, QuoteSnapshot] = {}
        for _, row in latest_rows.iterrows():
            dt = pd.to_datetime(row.get("dt"), errors="coerce")
            if pd.isna(dt) or pd.isna(row.get("close")):
                continue
            quotes[str(row["symbol"])] = QuoteSnapshot(
                symbol=str(row["symbol"]),
                last_price=float(row["close"]),
                timestamp=dt.to_pydatetime(),
                open=float(row["open"]) if pd.notna(row.get("open")) else None,
                high=float(row["high"]) if pd.notna(row.get("high")) else None,
                low=float(row["low"]) if pd.notna(row.get("low")) else None,
                volume=float(row["volume"]) if pd.notna(row.get("volume")) else None,
                amount=float(row["amount"]) if pd.notna(row.get("amount")) else None,
            )
        return quotes


class XtQuantRealtimeQuoteProvider:
    def __init__(self, xtdata_module=None, auto_connect: bool = True):
        self._xtdata = xtdata_module or self._load_xtdata_module()
        self._connected = False
        if auto_connect:
            self.connect()

    @staticmethod
    def _load_xtdata_module():
        try:
            return importlib.import_module("xtquant.xtdata")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "xtquant.xtdata is not installed or not available in the current "
                "Python environment."
            ) from exc

    def connect(self) -> None:
        if self._connected:
            return
        connect = getattr(self._xtdata, "connect", None)
        if callable(connect):
            connect()
        self._connected = True

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
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
    def strip_market_suffix(stock_code: str) -> str:
        return str(stock_code).upper().split(".", 1)[0]

    @staticmethod
    def _parse_timestamp(raw: dict) -> pd.Timestamp:
        if raw.get("time") is not None:
            return pd.to_datetime(raw["time"], unit="ms", errors="coerce")
        if raw.get("stime"):
            return pd.to_datetime(
                raw["stime"], format="%Y%m%d%H%M%S.%f", errors="coerce"
            )
        if raw.get("timetag"):
            return pd.to_datetime(raw["timetag"], errors="coerce")
        return pd.NaT

    @staticmethod
    def _extract_price_levels(raw: dict, side: str) -> list[float]:
        key = f"{side}Price"
        value = raw.get(key)
        if isinstance(value, list):
            return [float(v) for v in value if v not in (None, 0)]
        prices: list[float] = []
        for idx in range(1, 6):
            level = raw.get(f"{key}{idx}")
            if level in (None, 0):
                continue
            prices.append(float(level))
        return prices

    @staticmethod
    def _extract_volume_levels(raw: dict, side: str) -> list[int]:
        key = f"{side}Vol"
        value = raw.get(key)
        if isinstance(value, list):
            return [int(v) for v in value if v not in (None, 0)]
        volumes: list[int] = []
        for idx in range(1, 6):
            level = raw.get(f"{key}{idx}")
            if level in (None, 0):
                continue
            volumes.append(int(level))
        return volumes

    def get_quote_snapshots(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        self.connect()
        normalized = [self.normalize_symbol(symbol) for symbol in symbols]
        tick_map = self._xtdata.get_full_tick(normalized) or {}
        snapshots: Dict[str, QuoteSnapshot] = {}
        for xt_symbol, raw in tick_map.items():
            if not isinstance(raw, dict):
                continue
            timestamp = self._parse_timestamp(raw)
            if pd.isna(timestamp):
                continue
            if getattr(timestamp, "tzinfo", None) is not None:
                timestamp = timestamp.tz_localize(None)
            last_price = raw.get("lastPrice")
            if last_price in (None, 0):
                continue
            snapshots[self.strip_market_suffix(xt_symbol)] = QuoteSnapshot(
                symbol=self.strip_market_suffix(xt_symbol),
                last_price=float(last_price),
                timestamp=timestamp.to_pydatetime()
                if isinstance(timestamp, pd.Timestamp)
                else datetime.now(),
                open=(
                    float(raw["open"])
                    if raw.get("open") not in (None, 0)
                    else None
                ),
                high=(
                    float(raw["high"])
                    if raw.get("high") not in (None, 0)
                    else None
                ),
                low=(
                    float(raw["low"])
                    if raw.get("low") not in (None, 0)
                    else None
                ),
                prev_close=(
                    float(raw["lastClose"])
                    if raw.get("lastClose") not in (None, 0)
                    else None
                ),
                volume=int(raw.get("volume", 0) or 0),
                amount=float(raw.get("amount", 0.0) or 0.0),
                bid_prices=self._extract_price_levels(raw, "bid"),
                bid_volumes=self._extract_volume_levels(raw, "bid"),
                ask_prices=self._extract_price_levels(raw, "ask"),
                ask_volumes=self._extract_volume_levels(raw, "ask"),
                limit_up=(
                    float(raw["highLimit"])
                    if raw.get("highLimit") not in (None, 0)
                    else (
                        float(raw["upperLimitPrice"])
                        if raw.get("upperLimitPrice") not in (None, 0)
                        else None
                    )
                ),
                limit_down=(
                    float(raw["lowLimit"])
                    if raw.get("lowLimit") not in (None, 0)
                    else (
                        float(raw["lowerLimitPrice"])
                        if raw.get("lowerLimitPrice") not in (None, 0)
                        else None
                    )
                ),
                turnover_rate=(
                    float(raw["turnover"])
                    if raw.get("turnover") not in (None, 0)
                    else None
                ),
            )
        return snapshots

__all__ = ["AkShareRealtimeQuoteProvider", "XtQuantRealtimeQuoteProvider"]
