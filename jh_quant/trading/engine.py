from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Union

import pandas as pd

from jh_quant.backtest.rules import (
    ATRTrailingStopRule,
    PositionState,
    RiskRule,
    maybe_compute_atr,
)
from jh_quant.backtest.strategy import Strategy

from .broker import Broker
from .config import Frequency
from .execution import OrderExecutor, PositionValuator
from .market_data import (
    HistoricalBarProvider,
    InstrumentProvider,
    LatestQuoteProvider,
    MarketDataService,
    MarketStatusProvider,
    RealtimeQuoteProvider,
    TradingCalendarProvider,
)
from .market_data.models import QuoteSnapshot
from .models import Trade
from .position_sizer import ATRPositionSizer, PositionSizer
from .signal import SignalAggregator, SignalCandidateSelector
from .utils import rprint


class TradingEngine:
    """Coordinate market data, signals, sizing, valuation, and execution."""

    def __init__(
        self,
        broker: Broker,
        market_data_provider: MarketDataService = None,
        historical_data_provider: HistoricalBarProvider | None = None,
        realtime_quote_provider: RealtimeQuoteProvider | None = None,
        calendar_provider: TradingCalendarProvider | None = None,
        instrument_provider: InstrumentProvider | None = None,
        market_status_provider: MarketStatusProvider | None = None,
        position_sizer: PositionSizer = None,
        strict_mode: bool = True,
        risk_rules: List[RiskRule] | None = None,
    ):
        if broker is None:
            raise ValueError("TradingEngine requires a broker instance")

        self.broker = broker
        self.market_data_provider = market_data_provider
        self.historical_data_provider = historical_data_provider or getattr(
            market_data_provider, "historical_data", None
        )
        self.realtime_quote_provider = realtime_quote_provider or getattr(
            market_data_provider, "realtime_quote_provider", None
        )
        self.calendar_provider = calendar_provider or getattr(
            market_data_provider, "calendar_provider", None
        )
        self.instrument_provider = instrument_provider or getattr(
            market_data_provider, "instrument_provider", None
        )
        self.market_status_provider = market_status_provider or getattr(
            market_data_provider, "market_status_provider", None
        )
        self.position_sizer = position_sizer or ATRPositionSizer()
        self.strict_mode = strict_mode
        self.strategy_pool: List[dict] = []
        self.risk_rules: List[RiskRule] = list(risk_rules or [])
        self._reference_time: Optional[pd.Timestamp] = None

        self.position_valuator = PositionValuator(
            broker=self.broker,
            quote_loader=lambda symbols=None: self.get_latest_quotes(symbols),
        )
        self.order_executor = OrderExecutor(
            broker=self.broker,
            quote_loader=lambda symbols=None: self.get_latest_quotes(symbols),
            volume_normalizer=self._normalize_order_volume,
        )
        self.signal_aggregator = SignalAggregator(
            strategy_pool_getter=lambda: list(self.strategy_pool),
            frequency_max_age=self._frequency_max_age,
        )
        self.signal_candidate_selector = SignalCandidateSelector(
            broker=self.broker,
            position_sizer=self.position_sizer,
            get_price_data=self.get_price_data,
            validate_price_freshness=self.validate_price_freshness,
            aggregate_buy_signals=self.signal_aggregator.aggregate_buy_signals,
            aggregate_sell_signals=self.signal_aggregator.aggregate_sell_signals,
            get_latest_prices=self.get_latest_prices,
            evaluate_risk_exit=self._evaluate_risk_exit,
            market_data_enabled=lambda: self.market_data_provider is not None,
        )

    def set_reference_time(
        self,
        value: Optional[Union[str, datetime, pd.Timestamp]],
    ) -> None:
        self._reference_time = (
            None if value is None else self._normalize_reference_time(value)
        )
        if hasattr(self.market_data_provider, "set_reference_time"):
            self.market_data_provider.set_reference_time(self._reference_time)

    def clear_reference_time(self) -> None:
        self.set_reference_time(None)

    def add_strategy(self, strategy: Strategy, name: str, weight: float = 1.0):
        self.strategy_pool.append(
            {
                "name": name,
                "strategy": strategy,
                "weight": weight,
            }
        )

    def replace_strategies(self, strategies: List[dict]):
        self.strategy_pool = []
        for item in strategies:
            self.add_strategy(
                strategy=item["strategy"],
                name=item["name"],
                weight=item.get("weight", 1.0),
            )

    def configure_risk_rules(
        self,
        risk_rules: List[RiskRule] | None = None,
    ) -> None:
        self.risk_rules = list(risk_rules or [])

    def configure_position_sizer(self, sizer: PositionSizer) -> None:
        self.position_sizer = sizer
        self.signal_candidate_selector.position_sizer = sizer

    def get_price_data(
        self,
        symbols: List[str] = None,
        start_date: str = None,
        end_date: str = None,
        frequency: Frequency | str = Frequency.DAILY,
    ) -> pd.DataFrame:
        if self.market_data_provider is None:
            raise ValueError("MarketDataService not configured")

        if symbols is None:
            positions = self.broker.get_positions()
            symbols = [h.symbol for h in positions.holds] or None

        price_df = self.market_data_provider.get_price_data(
            symbols=symbols,
            start_date=start_date or "1900-01-01",
            end_date=end_date or "2099-12-31",
            frequency=frequency,
        )
        if price_df is None or price_df.empty:
            return pd.DataFrame()
        return price_df.sort_values(["symbol", "date"]).reset_index(drop=True)

    def build_price_matrix(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency | str = Frequency.DAILY,
        price: pd.DataFrame = None,
    ) -> pd.DataFrame:
        source = price
        if source is None:
            source = self.get_price_data(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
            )
        if source is None or source.empty:
            return pd.DataFrame()

        matrix = (
            source.copy()
            .assign(date=lambda frame: pd.to_datetime(frame["date"], errors="coerce"))
            .dropna(subset=["date", "symbol", "close"])
            .pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
            .sort_index()
        )
        if symbols:
            existing = [symbol for symbol in symbols if symbol in matrix.columns]
            matrix = matrix[existing]
        return matrix

    def build_return_matrix(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: Frequency | str = Frequency.DAILY,
        price: pd.DataFrame = None,
    ) -> pd.DataFrame:
        price_matrix = self.build_price_matrix(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            price=price,
        )
        if price_matrix.empty:
            return pd.DataFrame()
        returns = price_matrix.pct_change(fill_method=None).dropna(how="all")
        return returns.dropna(axis=1, how="all")

    def _normalize_frequency(self, frequency: Frequency | str | None) -> Frequency:
        return Frequency.from_value(frequency)

    def _frequency_max_age(self, frequency: Frequency | str) -> timedelta:
        frequency = self._normalize_frequency(frequency)
        mapping = {
            Frequency.DAILY: timedelta(hours=24),
            Frequency.HOUR_1: timedelta(hours=1),
            Frequency.MINUTE_60: timedelta(hours=1),
            Frequency.MINUTE_30: timedelta(minutes=30),
            Frequency.MINUTE_15: timedelta(minutes=15),
            Frequency.MINUTE_5: timedelta(minutes=5),
            Frequency.MINUTE_1: timedelta(minutes=1),
        }
        return mapping.get(frequency, timedelta(hours=24))

    def _normalize_reference_time(
        self,
        value: Optional[Union[str, datetime, pd.Timestamp]],
    ) -> pd.Timestamp:
        if value is None:
            return pd.Timestamp(datetime.now())
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return timestamp

    def validate_price_freshness(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
        strict_mode: Optional[bool] = None,
    ) -> bool:
        should_check = self.strict_mode if strict_mode is None else strict_mode
        if not should_check:
            return True
        if price.empty or "date" not in price.columns:
            rprint(
                label="Warning:",
                content="Price freshness check failed because no valid date column is available",
            )
            return False

        latest_timeindex = pd.Timestamp(price["date"].max())
        if latest_timeindex.tzinfo is not None:
            latest_timeindex = latest_timeindex.tz_localize(None)

        reference_ts = self._normalize_reference_time(reference_time)
        max_age = self._frequency_max_age(frequency)
        if reference_ts - latest_timeindex > max_age:
            rprint(
                label="Warning:",
                content=(
                    f"Latest market data is stale for frequency={Frequency.from_value(frequency).value}. "
                    f"latest={latest_timeindex}, reference={reference_ts}, max_age={max_age}. "
                    "Skip current execution."
                ),
            )
            return False
        return True

    def _filter_to_symbol_latest_window(
        self,
        signal_df: pd.DataFrame,
        frequency: Frequency | str,
    ) -> pd.DataFrame:
        return self.signal_aggregator.filter_to_symbol_latest_window(
            signal_df, frequency
        )

    def _evaluate_risk_exit(
        self,
        symbol: str,
        hold,
        price_df: pd.DataFrame,
    ) -> str | None:
        if not self.risk_rules:
            return None

        symbol_price = price_df[price_df["symbol"] == symbol].copy()
        if symbol_price.empty:
            return None

        symbol_price["date"] = pd.to_datetime(symbol_price["date"])
        symbol_price = symbol_price.sort_values("date")

        buy_date = pd.Timestamp(hold.entry_time)
        symbol_price = symbol_price[symbol_price["date"] >= buy_date]
        if symbol_price.empty or len(symbol_price) < 2:
            return None

        state = PositionState()
        state.enter(hold.avg_cost)
        for rule in self.risk_rules:
            rule.on_enter(state, hold.avg_cost)

        atr_series = maybe_compute_atr(symbol_price, self.risk_rules)
        if atr_series is not None:
            first_idx = symbol_price.index[0]
            atr_val = float(atr_series.loc[first_idx])
            for rule in self.risk_rules:
                if isinstance(rule, ATRTrailingStopRule):
                    rule.update_stop(atr_val, hold.avg_cost)

        all_indices = symbol_price.index.tolist()
        prev_price: Optional[float] = float(symbol_price.loc[all_indices[0], "close"])

        for idx in all_indices[1:]:
            current_price = float(symbol_price.loc[idx, "close"])
            state.holding_bars += 1
            state.highest_price = max(
                state.highest_price or current_price,
                current_price,
            )

            if atr_series is not None:
                atr_val = float(atr_series.loc[idx])
                for rule in self.risk_rules:
                    if isinstance(rule, ATRTrailingStopRule):
                        rule.update_stop(atr_val, state.highest_price)

            for rule in self.risk_rules:
                rule.on_tick(state, current_price, prev_price)

            if idx == all_indices[-1]:
                triggered_rules = [
                    type(rule).__name__
                    for rule in self.risk_rules
                    if rule.should_sell(state, current_price, prev_price)
                ]
                if triggered_rules:
                    rprint(
                        label="RiskRule:",
                        content=(
                            f"{symbol} triggered risk exits: {', '.join(triggered_rules)} "
                            f"(cost={hold.avg_cost:.2f}, price={current_price:.2f})"
                        ),
                    )
                    return "risk_rule:" + ",".join(triggered_rules)

            prev_price = current_price

        return None

    def aggregate_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
        signal_type: str = "buy",
    ) -> pd.DataFrame:
        return self.signal_aggregator.aggregate_signals(price, frequency, signal_type)

    def aggregate_buy_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
    ) -> pd.DataFrame:
        return self.signal_aggregator.aggregate_buy_signals(price, frequency)

    def aggregate_sell_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
    ) -> pd.DataFrame:
        return self.signal_aggregator.aggregate_sell_signals(price, frequency)

    def get_latest_quotes(self, symbols: List[str] = None) -> dict[str, QuoteSnapshot]:
        if symbols is None:
            positions = self.broker.get_positions()
            symbols = [h.symbol for h in positions.holds]

        if not symbols or self.market_data_provider is None:
            return {}

        if isinstance(self.market_data_provider, LatestQuoteProvider):
            return self.market_data_provider.get_latest_quotes(
                symbols,
                as_of_date=self._reference_time,
            )

        prices = self.market_data_provider.get_latest_prices(
            symbols,
            as_of_date=self._reference_time,
        )
        timestamp = (
            self._reference_time.to_pydatetime()
            if isinstance(self._reference_time, pd.Timestamp)
            else datetime.now()
        )
        return {
            symbol: QuoteSnapshot(
                symbol=symbol,
                last_price=float(price),
                timestamp=timestamp,
            )
            for symbol, price in prices.items()
        }

    def get_latest_prices(self, symbols: List[str] = None) -> pd.Series:
        quotes = self.get_latest_quotes(symbols)
        if not quotes:
            return pd.Series(dtype=float)
        return pd.Series(
            {symbol: quote.last_price for symbol, quote in quotes.items()},
            dtype=float,
        )

    def get_market_status(self):
        if self.market_status_provider is None:
            return None
        reference_time = (
            self._reference_time.to_pydatetime()
            if isinstance(self._reference_time, pd.Timestamp)
            else None
        )
        return self.market_status_provider.get_market_status(now=reference_time)

    def refresh_position_market_value(
        self,
        symbols: Optional[List[str]] = None,
    ) -> dict[str, float]:
        return self.position_valuator.refresh(symbols)

    def _normalize_order_volume(self, symbol: str, volume: int) -> int:
        if volume <= 0:
            return 0
        if self.instrument_provider is None:
            return int(volume)
        normalize = getattr(self.instrument_provider, "normalize_order_volume", None)
        if callable(normalize):
            return int(normalize(symbol, int(volume)))
        instruments = self.instrument_provider.get_instruments([symbol])
        meta = instruments.get(symbol)
        lot_size = getattr(meta, "lot_size", 1) if meta is not None else 1
        lot_size = max(1, int(lot_size))
        return max(0, int(volume) // lot_size * lot_size)

    def calculate_position_size(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series = None,
    ) -> pd.DataFrame:
        positions = self.broker.get_positions()
        total_equity = positions.total
        available_balance = positions.available_balance
        if latest_prices is None:
            latest_prices = price_df.groupby("symbol")["close"].last()
        return self.position_sizer.calculate(
            candidates=candidates,
            price_df=price_df,
            latest_prices=latest_prices,
            available_balance=available_balance,
            total_equity=total_equity,
        )

    def get_long_candidates(
        self,
        start_date: str = None,
        end_date: str = None,
        max_candidates: int = 5,
        price: pd.DataFrame = None,
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
    ) -> pd.DataFrame:
        return self.signal_candidate_selector.get_long_candidates(
            start_date=start_date,
            end_date=end_date,
            max_candidates=max_candidates,
            price=price,
            frequency=frequency,
            reference_time=reference_time,
        )

    def get_short_candidates(
        self,
        start_date: str = None,
        end_date: str = None,
        price: pd.DataFrame = None,
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
    ) -> pd.DataFrame:
        return self.signal_candidate_selector.get_short_candidates(
            start_date=start_date,
            end_date=end_date,
            price=price,
            frequency=frequency,
            reference_time=reference_time,
        )

    def execute_long(
        self,
        orders: pd.DataFrame,
        slippage: float = 0.0,
    ) -> List[Trade]:
        return self.order_executor.execute_buy_orders(orders, slippage)

    def execute_short(
        self,
        orders: pd.DataFrame,
        slippage: float = 0.0,
    ) -> List[Trade]:
        return self.order_executor.execute_sell_orders(orders, slippage)

    def close_all_positions(
        self,
        slippage: float = 0.0,
    ) -> List[Trade]:
        return self.order_executor.close_all_positions(slippage)

    def execute_cycle(
        self,
        top_selections: List[str],
        price_start: str,
        cycle_date: str,
        frequency: Frequency | str = Frequency.DAILY,
        max_candidates: int = 10,
        price_slippage: float = 0.0,
    ) -> tuple[List[Trade], List[Trade], pd.DataFrame, pd.DataFrame]:
        price = self.get_price_data(
            symbols=top_selections or None,
            start_date=price_start,
            end_date=cycle_date,
            frequency=frequency,
        )

        self.refresh_position_market_value(symbols=top_selections)

        short_candidates = self.get_short_candidates(
            start_date=price_start,
            end_date=cycle_date,
            price=price,
            frequency=frequency,
            reference_time=cycle_date,
        )
        executed_sells: List[Trade] = []
        if not short_candidates.empty:
            executed_sells = self.execute_short(short_candidates, price_slippage)

        long_candidates = self.get_long_candidates(
            start_date=price_start,
            end_date=cycle_date,
            max_candidates=max_candidates,
            price=price,
            frequency=frequency,
            reference_time=cycle_date,
        )
        executed_buys: List[Trade] = []
        if not long_candidates.empty:
            executed_buys = self.execute_long(long_candidates, price_slippage)

        return executed_buys, executed_sells, long_candidates, short_candidates
