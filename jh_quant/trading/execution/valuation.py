from __future__ import annotations

from typing import Callable, List, Optional

from ..broker import Broker
from ..market_data.models import QuoteSnapshot


class PositionValuator:
    """Apply latest quotes to in-memory broker holdings."""

    def __init__(
        self,
        broker: Broker,
        quote_loader: Callable[[Optional[List[str]]], dict[str, QuoteSnapshot]],
    ):
        self.broker = broker
        self._quote_loader = quote_loader

    def refresh(self, symbols: Optional[List[str]] = None) -> dict[str, float]:
        quotes = self._quote_loader(symbols)
        if not quotes:
            return {}
        prices = {symbol: float(quote.last_price) for symbol, quote in quotes.items()}
        if hasattr(self.broker, "update_position_market_value"):
            self.broker.update_position_market_value(prices)
        return prices
