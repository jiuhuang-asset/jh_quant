from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Union

import pandas as pd

from ..broker import Broker
from ..config import Frequency
from ..position_sizer import PositionSizer
from ..utils import rprint


class SignalCandidateSelector:
    """Build long/short order candidates from signals and broker state."""

    def __init__(
        self,
        broker: Broker,
        position_sizer: PositionSizer,
        get_price_data: Callable[..., pd.DataFrame],
        validate_price_freshness: Callable[..., bool],
        aggregate_buy_signals: Callable[..., pd.DataFrame],
        aggregate_sell_signals: Callable[..., pd.DataFrame],
        get_latest_prices: Callable[..., pd.Series],
        evaluate_risk_exit: Callable[..., str | None],
        market_data_enabled: Callable[[], bool],
    ):
        self.broker = broker
        self.position_sizer = position_sizer
        self._get_price_data = get_price_data
        self._validate_price_freshness = validate_price_freshness
        self._aggregate_buy_signals = aggregate_buy_signals
        self._aggregate_sell_signals = aggregate_sell_signals
        self._get_latest_prices = get_latest_prices
        self._evaluate_risk_exit = evaluate_risk_exit
        self._market_data_enabled = market_data_enabled

    def _calculate_position_size(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series | None = None,
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
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        max_candidates: int = 5,
        price: pd.DataFrame | None = None,
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
    ) -> pd.DataFrame:
        positions = self.broker.get_positions()
        rprint(
            label="Info:",
            content=f"总权益: {positions.total:.2f}, 可用资金: {positions.available_balance:.2f}",
        )

        if price is None:
            price = self._get_price_data(
                start_date=start_date,
                end_date=end_date,
            )

        if price.empty:
            rprint(label="Warning:", content="无法获取价格数据")
            return pd.DataFrame()

        if not self._validate_price_freshness(
            price=price,
            frequency=frequency,
            reference_time=reference_time or end_date,
        ):
            return pd.DataFrame()

        raw_signals = self._aggregate_buy_signals(price=price, frequency=frequency)
        if raw_signals.empty:
            rprint(label="Info:", content="没有买入信号")
            return pd.DataFrame()

        final_list = raw_signals.sort_values(by="score", ascending=False).head(
            max_candidates
        )
        final_list["reason"] = "strategy"

        current_hold_symbols = {h.symbol for h in self.broker.get_positions().holds}
        if current_hold_symbols:
            final_list = final_list[~final_list["symbol"].isin(current_hold_symbols)]

        if final_list.empty:
            rprint(label="Info:", content="所有买入候选已在持仓中，跳过买入")
            return pd.DataFrame()

        if self._market_data_enabled():
            latest_prices = self._get_latest_prices(final_list["symbol"].tolist())
        else:
            latest_prices = (
                price[price["symbol"].isin(final_list["symbol"])]
                .sort_values(["symbol", "date"])
                .groupby("symbol")["close"]
                .last()
            )

        return self._calculate_position_size(final_list, price, latest_prices)

    def get_short_candidates(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        price: pd.DataFrame | None = None,
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
    ) -> pd.DataFrame:
        positions = self.broker.get_positions()
        rprint(
            label="Info:",
            content=f"总权益: {positions.total:.2f}, 持仓数: {len(positions.holds)}",
        )

        if not self.broker.executable_holds:
            rprint(label="Info:", content="没有[可卖]持仓，无法执行卖出")
            return pd.DataFrame()

        hold_symbols = [h.symbol for h in self.broker.executable_holds]

        if price is None:
            price = self._get_price_data(
                symbols=hold_symbols,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            price = price[price["symbol"].isin(hold_symbols)].copy()

        if price.empty:
            return pd.DataFrame()

        if not self._validate_price_freshness(
            price=price,
            frequency=frequency,
            reference_time=reference_time or end_date,
        ):
            return pd.DataFrame()

        sell_signals = self._aggregate_sell_signals(price=price, frequency=frequency)
        holdings_map = {h.symbol: h for h in self.broker.executable_holds}
        strategy_sell_symbols: set[str] = set()
        sell_candidate_rows: list[dict] = []

        if not sell_signals.empty:
            strategy_sells = sell_signals[
                (sell_signals["symbol"].isin(holdings_map.keys()))
                & (sell_signals["score"] > 1)
            ]
            if not strategy_sells.empty:
                strategy_sell_symbols = set(strategy_sells["symbol"].tolist())
                sell_candidate_rows.extend(
                    {
                        "symbol": row["symbol"],
                        "score": row["score"],
                        "reason": "strategy",
                    }
                    for _, row in strategy_sells.iterrows()
                )

        for symbol, hold in holdings_map.items():
            if symbol in strategy_sell_symbols:
                continue
            risk_reason = self._evaluate_risk_exit(symbol, hold, price)
            if risk_reason is not None:
                sell_candidate_rows.append(
                    {"symbol": symbol, "score": float("inf"), "reason": risk_reason}
                )

        if not sell_candidate_rows:
            return pd.DataFrame()

        sell_candidates = pd.DataFrame(sell_candidate_rows)
        sell_orders = []
        for _, row in sell_candidates.iterrows():
            symbol = row["symbol"]
            qty = holdings_map[symbol].volume
            sell_orders.append(
                {
                    "symbol": symbol,
                    "target_qty": qty,
                    "reason": row.get("reason", "strategy"),
                }
            )

        return pd.DataFrame(sell_orders)
