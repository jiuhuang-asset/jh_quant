from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from ..config import Frequency
from .historical import JHHistoricalBarProvider
from .instruments import AkShareInstrumentProvider
from .models import InstrumentMeta, MarketStatus, QuoteSnapshot
from .protocols import (
    HistoricalBarProvider,
    InstrumentProvider,
    MarketStatusProvider,
    RealtimeQuoteProvider,
    TradingCalendarProvider,
)
from .realtime import AkShareRealtimeQuoteProvider, XtQuantRealtimeQuoteProvider
from .status import AkShareMarketStatusProvider


class AkShareMarketDataService:
    def __init__(
        self,
        historical_data: HistoricalBarProvider,
        *,
        realtime_quote_provider: Optional[RealtimeQuoteProvider] = None,
        calendar_provider: Optional[TradingCalendarProvider] = None,
        instrument_provider: Optional[InstrumentProvider] = None,
        market_status_provider: Optional[MarketStatusProvider] = None,
        default_symbols: Optional[List[str]] = None,
    ):
        self.historical_data = historical_data
        self.realtime_quote_provider = realtime_quote_provider
        self.calendar_provider = calendar_provider or historical_data
        self.instrument_provider = instrument_provider or AkShareInstrumentProvider()
        self.market_status_provider = (
            market_status_provider or AkShareMarketStatusProvider()
        )
        self.default_symbols = default_symbols or []
        self._reference_time: Optional[pd.Timestamp] = None

    def _resolve_symbols(self, symbols: Optional[List[str]]) -> List[str]:
        resolved = symbols or self.default_symbols
        return list(dict.fromkeys(resolved))

    def set_reference_time(
        self, value: Optional[str | datetime | pd.Timestamp]
    ) -> None:
        if value is None:
            self._reference_time = None
            return
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        self._reference_time = ts

    def _get_today_spot_fresh_after(self) -> pd.Timestamp:
        today = pd.Timestamp.now().normalize()
        return today + pd.Timedelta(hours=14, minutes=50)

    def _resolve_reference_time(
        self, as_of_date: Optional[str | datetime | pd.Timestamp] = None
    ) -> pd.Timestamp:
        if as_of_date is not None:
            ts = pd.Timestamp(as_of_date)
        elif self._reference_time is not None:
            ts = self._reference_time
        else:
            ts = pd.Timestamp(datetime.now())
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts

    def _should_merge_realtime(
        self,
        end_date: str,
        *,
        as_of_date: Optional[str | datetime | pd.Timestamp] = None,
    ) -> bool:
        if self.realtime_quote_provider is None:
            return False
        reference_ts = self._resolve_reference_time(as_of_date)
        end_ts = pd.Timestamp(end_date)
        if end_ts.tzinfo is not None:
            end_ts = end_ts.tz_localize(None)
        return end_ts.normalize() == reference_ts.normalize() == pd.Timestamp.now().normalize()

    def _quote_to_row(self, quote: QuoteSnapshot) -> dict:
        chg = None
        pct_chg = None
        amplitude = None
        if quote.prev_close not in (None, 0):
            chg = float(quote.last_price) - float(quote.prev_close)
            pct_chg = chg / float(quote.prev_close) * 100
            if quote.high is not None and quote.low is not None:
                amplitude = (
                    (float(quote.high) - float(quote.low))
                    / float(quote.prev_close)
                    * 100
                )
        return {
            "date": pd.Timestamp(quote.timestamp).normalize(),
            "symbol": quote.symbol,
            "open": quote.open,
            "close": quote.last_price,
            "high": quote.high,
            "low": quote.low,
            "volume": quote.volume,
            "amount": quote.amount,
            "amplitude": amplitude,
            "pct_chg": pct_chg,
            "chg": chg,
            "turnover_rate": quote.turnover_rate,
            "price": quote.last_price,
        }

    def _fetch_today_spot_df(self, symbols: List[str]) -> pd.DataFrame:
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols or self.realtime_quote_provider is None:
            return pd.DataFrame()

        fresh_after = self._get_today_spot_fresh_after()
        get_spot_dataframe = getattr(
            self.realtime_quote_provider, "get_spot_dataframe", None
        )
        if callable(get_spot_dataframe):
            spot_df = get_spot_dataframe(
                resolved_symbols,
                fresh_after=fresh_after,
            )
            if spot_df is None or spot_df.empty:
                return pd.DataFrame()
            return spot_df.copy()

        quotes = self.realtime_quote_provider.get_quote_snapshots(resolved_symbols)
        rows = [
            self._quote_to_row(quote)
            for quote in quotes.values()
            if pd.Timestamp(quote.timestamp) >= fresh_after
        ]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values(["symbol", "date"]).reset_index(drop=True)

    def get_latest_quotes(
        self,
        symbols: List[str],
        as_of_date: Optional[str | datetime | pd.Timestamp] = None,
    ) -> Dict[str, QuoteSnapshot]:
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return {}
        reference_ts = self._resolve_reference_time(as_of_date)
        if (
            self.realtime_quote_provider is not None
            and reference_ts.normalize() == pd.Timestamp.now().normalize()
        ):
            return self.realtime_quote_provider.get_quote_snapshots(resolved_symbols)

        hist = self.historical_data.get_bars(
            resolved_symbols,
            start_date="1900-01-01",
            end_date=reference_ts.strftime("%Y-%m-%d"),
        )
        if hist is None or hist.empty:
            return {}
        quotes: Dict[str, QuoteSnapshot] = {}
        latest_rows = (
            hist.sort_values(["symbol", "date"]).groupby("symbol").tail(1).copy()
        )
        latest_rows["date"] = pd.to_datetime(latest_rows["date"], errors="coerce")
        for _, row in latest_rows.iterrows():
            if pd.isna(row["date"]):
                continue
            quotes[row["symbol"]] = QuoteSnapshot(
                symbol=row["symbol"],
                last_price=float(row["close"]),
                timestamp=pd.Timestamp(row["date"]).to_pydatetime(),
                open=(
                    float(row["open"])
                    if pd.notna(row.get("open"))
                    else None
                ),
                high=(
                    float(row["high"])
                    if pd.notna(row.get("high"))
                    else None
                ),
                low=(
                    float(row["low"])
                    if pd.notna(row.get("low"))
                    else None
                ),
                volume=(
                    int(row["volume"])
                    if pd.notna(row.get("volume"))
                    else None
                ),
                amount=(
                    float(row["amount"])
                    if pd.notna(row.get("amount"))
                    else None
                ),
            )
        return quotes

    def get_latest_prices(
        self,
        symbols: List[str],
        as_of_date: Optional[str | datetime | pd.Timestamp] = None,
    ) -> Dict[str, float]:
        return {
            symbol: quote.last_price
            for symbol, quote in self.get_latest_quotes(
                symbols,
                as_of_date=as_of_date,
            ).items()
        }

    def get_price_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency = Frequency.DAILY,
    ) -> pd.DataFrame:
        resolved_symbols = self._resolve_symbols(symbols)
        if not resolved_symbols:
            return pd.DataFrame()

        hist_df = self.historical_data.get_bars(
            resolved_symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
        )
        if not self._should_merge_realtime(end_date):
            if hist_df is None or hist_df.empty:
                return pd.DataFrame()
            return hist_df.sort_values(["symbol", "date"]).copy()

        spot_df = self._fetch_today_spot_df(resolved_symbols)
        if spot_df.empty:
            if hist_df is None or hist_df.empty:
                return pd.DataFrame()
            return hist_df.sort_values(["symbol", "date"]).copy()
        if hist_df is None or hist_df.empty:
            return spot_df.sort_values(["symbol", "date"]).copy()

        combined = pd.concat([hist_df, spot_df], ignore_index=True, sort=False)
        combined["_date_key"] = pd.to_datetime(
            combined["date"], errors="coerce"
        ).dt.normalize()
        combined = combined.sort_values(["symbol", "_date_key"])
        combined = combined.drop_duplicates(subset=["symbol", "_date_key"], keep="last")
        combined = combined.drop(columns=["_date_key"], errors="ignore")
        return combined.sort_values(["symbol", "date"]).copy()

    def get_trade_calendar(
        self,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ):
        return self.calendar_provider.get_trade_calendar(
            start_date=start_date,
            end_date=end_date,
        )

    def get_instruments(self, symbols: List[str]) -> Dict[str, InstrumentMeta]:
        return self.instrument_provider.get_instruments(self._resolve_symbols(symbols))

    def get_market_status(self, now: Optional[datetime] = None) -> MarketStatus:
        return self.market_status_provider.get_market_status(now=now)


class AkShareJHMarketDataService(AkShareMarketDataService):
    def __init__(
        self,
        jhd=None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
    ):
        historical_data = JHHistoricalBarProvider(
            jhd=jhd,
            frequency=frequency,
            default_symbols=default_symbols,
        )
        super().__init__(
            historical_data=historical_data,
            realtime_quote_provider=AkShareRealtimeQuoteProvider(jhd=historical_data.jhd),
            calendar_provider=historical_data,
            default_symbols=default_symbols,
        )
        self.jhd = historical_data.jhd


class XtQuantAkShareMarketDataService(AkShareMarketDataService):
    def __init__(
        self,
        jhd=None,
        frequency: Frequency = Frequency.DAILY,
        default_symbols: Optional[List[str]] = None,
        *,
        xtdata_module=None,
        auto_connect: bool = True,
    ):
        historical_data = JHHistoricalBarProvider(
            jhd=jhd,
            frequency=frequency,
            default_symbols=default_symbols,
        )
        super().__init__(
            historical_data=historical_data,
            realtime_quote_provider=XtQuantRealtimeQuoteProvider(
                xtdata_module=xtdata_module,
                auto_connect=auto_connect,
            ),
            calendar_provider=historical_data,
            instrument_provider=AkShareInstrumentProvider(),
            market_status_provider=AkShareMarketStatusProvider(),
            default_symbols=default_symbols,
        )
        self.jhd = historical_data.jhd


__all__ = [
    "AkShareMarketDataService",
    "AkShareJHMarketDataService",
    "XtQuantAkShareMarketDataService",
]
