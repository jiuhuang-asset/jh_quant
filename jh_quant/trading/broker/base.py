from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Order, Positions, StockHoldRecord, Trade


class Broker(ABC):
    """Broker gateway - execution and account query boundary.

    Persistence is handled by upper layers. A broker implementation is
    responsible for account/position reads and order execution only.
    """

    @property
    @abstractmethod
    def session_id(self) -> str:
        """Unique session identifier."""
        ...

    @abstractmethod
    def get_positions(self) -> Positions: ...

    @abstractmethod
    def get_available_balance(self) -> float: ...

    @abstractmethod
    def signal_buy(self, order: Order) -> Trade:
        """Execute buy order, return trade record."""
        ...

    @abstractmethod
    def signal_sell(self, order: Order) -> Trade:
        """Execute sell order, return trade record."""
        ...

    @abstractmethod
    def update_position_market_value(self, price_dict: dict) -> None:
        """Update in-memory hold market values from latest prices."""
        ...

    @property
    @abstractmethod
    def executable_holds(self) -> List[StockHoldRecord]: ...
