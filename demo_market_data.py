from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, Optional

import pandas as pd
from jh_quant.trading.market_data.models import QuoteSnapshot


class DemoSyntheticMarketDataProvider:
    """Synthetic fallback data provider for demo entrypoints.

    It keeps run_paper.py / run_live.py runnable even when external market-data
    dependencies such as JHData service or xtquant are not available.
    """

    def __init__(self, default_symbols: Optional[Iterable[str]] = None):
        self.default_symbols = list(default_symbols or [])
        self._reference_time: Optional[pd.Timestamp] = None

    def _resolve_symbols(self, symbols):
        resolved = symbols or self.default_symbols
        return list(dict.fromkeys(str(symbol) for symbol in resolved))

    def _resolve_now(self, as_of_date=None) -> pd.Timestamp:
        if as_of_date is not None:
            ts = pd.Timestamp(as_of_date)
        elif self._reference_time is not None:
            ts = self._reference_time
        else:
            ts = pd.Timestamp(datetime.now())
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts

    def set_reference_time(self, value) -> None:
        self._reference_time = None if value is None else self._resolve_now(value)

    def _price_for(self, symbol: str, trade_date: pd.Timestamp) -> float:
        symbol_seed = sum(ord(ch) for ch in symbol) % 97
        day_seed = trade_date.toordinal() % 31
        return round(8.0 + symbol_seed * 0.07 + day_seed * 0.11, 2)

    def get_price_data(
        self,
        symbols,
        start_date: str,
        end_date: str,
        frequency=None,
    ) -> pd.DataFrame:
        resolved = self._resolve_symbols(symbols)
        if not resolved:
            return pd.DataFrame()

        start_ts = pd.Timestamp(start_date).normalize()
        end_ts = pd.Timestamp(end_date).normalize()
        if end_ts < start_ts:
            return pd.DataFrame()

        dates = pd.bdate_range(start_ts, end_ts)
        rows: list[dict] = []
        for symbol in resolved:
            for trade_date in dates:
                close = self._price_for(symbol, trade_date)
                rows.append(
                    {
                        "symbol": symbol,
                        "date": trade_date,
                        "open": round(close * 0.995, 2),
                        "high": round(close * 1.01, 2),
                        "low": round(close * 0.99, 2),
                        "close": close,
                        "volume": 1500.0,
                        "amount": round(close * 150000.0, 2),
                        "price": close,
                    }
                )
        return pd.DataFrame(rows)

    def get_latest_prices(self, symbols, as_of_date=None) -> Dict[str, float]:
        resolved = self._resolve_symbols(symbols)
        now = self._resolve_now(as_of_date).normalize()
        return {symbol: self._price_for(symbol, now) for symbol in resolved}

    def get_latest_quotes(self, symbols, as_of_date=None) -> Dict[str, QuoteSnapshot]:
        resolved = self._resolve_symbols(symbols)
        now = self._resolve_now(as_of_date)
        return {
            symbol: QuoteSnapshot(
                symbol=symbol,
                last_price=self._price_for(symbol, now.normalize()),
                timestamp=now.to_pydatetime(),
            )
            for symbol in resolved
        }

    def get_trade_calendar(
        self,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ):
        start_ts = pd.Timestamp(start_date).normalize()
        end_ts = self._resolve_now(end_date).normalize() if end_date else pd.Timestamp.now().normalize()
        return {trade_date.strftime("%Y-%m-%d") for trade_date in pd.bdate_range(start_ts, end_ts)}
