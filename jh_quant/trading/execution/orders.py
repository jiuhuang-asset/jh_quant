from __future__ import annotations

from typing import Callable, List, Optional

import pandas as pd

from ..broker import Broker
from ..market_data.models import QuoteSnapshot
from ..models import Order, Trade
from ..utils import rprint


class OrderExecutor:
    """Execute buy/sell orders against a broker using latest quote snapshots."""

    def __init__(
        self,
        broker: Broker,
        quote_loader: Callable[[Optional[List[str]]], dict[str, QuoteSnapshot]],
        volume_normalizer: Callable[[str, int], int],
    ):
        self.broker = broker
        self._quote_loader = quote_loader
        self._volume_normalizer = volume_normalizer

    def _resolve_execution_price(
        self,
        quote: QuoteSnapshot,
        side: str,
        slippage: float,
    ) -> float:
        price = float(quote.last_price)
        if slippage <= 0:
            return price
        multiplier = 1 + slippage if side == "BUY" else 1 - slippage
        return price * multiplier

    def execute_buy_orders(
        self,
        orders: pd.DataFrame,
        slippage: float = 0.0,
    ) -> List[Trade]:
        symbols = orders["symbol"].tolist() if not orders.empty else []
        latest_quotes = self._quote_loader(symbols)

        executed_trades: List[Trade] = []
        for _, row in orders.iterrows():
            symbol = row["symbol"]
            target_qty = self._volume_normalizer(symbol, int(row["target_qty"]))
            if target_qty <= 0:
                rprint(
                    label="Warning:",
                    content=f"Skip BUY {symbol}: normalized volume is below minimum lot size.",
                )
                continue

            quote = latest_quotes.get(symbol)
            if quote is None:
                rprint(label="Warning:", content=f"Missing latest quote for BUY {symbol}")
                continue

            exec_price = self._resolve_execution_price(quote, "BUY", slippage)

            try:
                order = Order(
                    symbol=symbol,
                    price=exec_price,
                    volume=target_qty,
                    trade_type="BUY",
                    signal_reason=row.get("reason"),
                )
                trade = self.broker.signal_buy(order)
                executed_trades.append(trade)
            except Exception as exc:
                rprint(label="Error:", content=f"BUY {symbol} failed: {exc}")
                continue

        return executed_trades

    def execute_sell_orders(
        self,
        orders: pd.DataFrame,
        slippage: float = 0.0,
    ) -> List[Trade]:
        symbols = orders["symbol"].tolist() if not orders.empty else []
        latest_quotes = self._quote_loader(symbols)
        executable_holdings_map = {h.symbol: h for h in self.broker.executable_holds}

        executed_trades: List[Trade] = []
        for _, row in orders.iterrows():
            symbol = row["symbol"]
            target_qty = self._volume_normalizer(symbol, int(row["target_qty"]))
            if target_qty <= 0:
                rprint(
                    label="Warning:",
                    content=f"Skip SELL {symbol}: normalized volume is below minimum lot size.",
                )
                continue

            quote = latest_quotes.get(symbol)
            if quote is None:
                rprint(label="Warning:", content=f"Missing latest quote for SELL {symbol}")
                continue

            holding_info = executable_holdings_map.get(symbol)
            if holding_info is None:
                rprint(
                    label="Warning:",
                    content=f"Skip SELL {symbol}: not present in executable holdings.",
                )
                continue

            executable_qty = int(holding_info.volume)
            if executable_qty <= 0:
                rprint(label="Warning:", content=f"Skip SELL {symbol}: sellable quantity is 0.")
                continue
            if target_qty > executable_qty:
                rprint(
                    label="Warning:",
                    content=(
                        f"SELL {symbol} requested {target_qty}, but only "
                        f"{executable_qty} is executable. Capping to sellable quantity."
                    ),
                )
                target_qty = executable_qty

            exec_price = self._resolve_execution_price(quote, "SELL", slippage)

            try:
                order = Order(
                    symbol=symbol,
                    price=exec_price,
                    volume=target_qty,
                    trade_type="SELL",
                    signal_reason=row.get("reason"),
                )
                trade = self.broker.signal_sell(order)
                executed_trades.append(trade)
            except Exception as exc:
                rprint(label="Error:", content=f"SELL {symbol} failed: {exc}")
                continue

        return executed_trades

    def close_all_positions(
        self,
        slippage: float = 0.0,
    ) -> List[Trade]:
        holdings = list(self.broker.executable_holds)
        if not holdings:
            rprint(label="Info:", content="No executable holdings to close.")
            return []

        close_orders = pd.DataFrame(
            [
                {"symbol": h.symbol, "target_qty": h.volume, "reason": "manual_close"}
                for h in holdings
            ]
        )
        rprint(label="Info:", content=f"Closing {len(holdings)} executable holdings.")
        executed_trades = self.execute_sell_orders(close_orders, slippage)
        rprint(
            label="Info:",
            content=f"Closed {len(executed_trades)} executable holdings.",
        )
        return executed_trades
