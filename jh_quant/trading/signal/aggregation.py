from __future__ import annotations

from datetime import timedelta
from typing import Callable, List

import pandas as pd

from ..config import Frequency
from ..utils import rprint


class SignalAggregator:
    """Aggregate weighted buy/sell signals from registered strategies."""

    def __init__(
        self,
        strategy_pool_getter: Callable[[], List[dict]],
        frequency_max_age: Callable[[Frequency | str], timedelta],
    ):
        self._strategy_pool_getter = strategy_pool_getter
        self._frequency_max_age = frequency_max_age

    def filter_to_symbol_latest_window(
        self,
        signal_df: pd.DataFrame,
        frequency: Frequency | str,
    ) -> pd.DataFrame:
        if (
            signal_df.empty
            or "symbol" not in signal_df.columns
            or "date" not in signal_df.columns
        ):
            return signal_df

        normalized = signal_df.copy()
        normalized["date"] = pd.to_datetime(normalized["date"])
        latest_by_symbol = normalized.groupby("symbol")["date"].transform("max")
        max_age = self._frequency_max_age(frequency)
        return normalized.loc[
            normalized["date"] >= (latest_by_symbol - max_age)
        ].copy()

    def aggregate_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
        signal_type: str = "buy",
    ) -> pd.DataFrame:
        strategy_pool = self._strategy_pool_getter()
        if not strategy_pool:
            rprint(
                label="Warning:",
                content="No strategies registered in the trading module",
            )
            return pd.DataFrame()

        signal_column = f"{signal_type}_signal"
        weighted_column = f"{signal_type}_signal_w"

        all_signals = []
        for strat in strategy_pool:
            signal_df = strat["strategy"](price)
            signal_df = self.filter_to_symbol_latest_window(signal_df, frequency)
            signal_df[weighted_column] = signal_df[signal_column] * strat["weight"]
            signal_df["_strategy_name"] = strat["name"]
            all_signals.append(
                signal_df[["symbol", weighted_column, "_strategy_name"]]
            )

        if not all_signals:
            return pd.DataFrame(columns=["symbol", "score"])

        concat_all = pd.concat(all_signals)
        combined = concat_all.groupby("symbol")[weighted_column].sum().reset_index()
        combined.rename(columns={weighted_column: "score"}, inplace=True)
        return combined

    def aggregate_buy_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
    ) -> pd.DataFrame:
        return self.aggregate_signals(price, frequency, "buy")

    def aggregate_sell_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
    ) -> pd.DataFrame:
        return self.aggregate_signals(price, frequency, "sell")
