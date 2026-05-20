from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..models import (
    DailyPerformance,
    Order,
    PositionSnapshot,
    Positions,
    StockHoldRecord,
    Trade,
)
from .base import Broker


class PaperBroker(Broker):
    """Paper broker for simulation and backfill workflows."""

    def __init__(
        self,
        initial_capital: float,
        session_id: Optional[str] = None,
        start_time: datetime = None,
        restore_from: Optional[str] = None,
        state_dict: Optional[Dict[str, Any]] = None,
    ):
        self.session_id = session_id or f"paper_broker_{uuid.uuid4().hex}"
        self.initial_capital = initial_capital
        self.total = initial_capital
        self.available_balance = initial_capital
        self.total_profit = 0.0
        self.daily_profit = 0.0
        self._prev_portfolio_value = initial_capital
        self.holds: List[StockHoldRecord] = []
        self.start_time = start_time or datetime.now()

        self.trades: List[Trade] = []
        self.trade_pnl: Dict[str, float] = {}
        self._simulation_date: Optional[datetime] = None

        if state_dict and restore_from in ("auto", "state"):
            try:
                self.import_state(state_dict)
            except Exception:
                pass

    def set_simulation_date(self, date: Optional[datetime]) -> None:
        self._simulation_date = date

    def _now(self) -> datetime:
        return self._simulation_date or datetime.now()

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        self._session_id = value

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{self.session_id}_{uuid.uuid4().hex[:8]}"

    def export_state(self) -> Dict[str, Any]:
        def convert_to_serializable(obj):
            if isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if isinstance(obj, (int, float, str, bool, type(None))):
                return obj
            return str(obj)

        holds_data = [h.model_dump() for h in self.holds]
        trades_data = [t.model_dump() for t in self.trades]

        return {
            "session_id": self.session_id,
            "initial_capital": self.initial_capital,
            "total": self.total,
            "available_balance": self.available_balance,
            "total_profit": self.total_profit,
            "daily_profit": self.daily_profit,
            "_prev_portfolio_value": self._prev_portfolio_value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "holds": convert_to_serializable(holds_data),
            "trades": convert_to_serializable(trades_data),
            "trade_pnl": self.trade_pnl,
            "export_time": datetime.now().isoformat(),
        }

    def import_state(self, state: Dict[str, Any]) -> None:
        self.session_id = state.get("session_id", self.session_id)
        self.initial_capital = state.get("initial_capital", self.initial_capital)
        self.total = state.get("total", self.initial_capital)
        self.available_balance = state.get("available_balance", self.initial_capital)
        self.total_profit = state.get("total_profit", 0.0)
        self.daily_profit = state.get("daily_profit", 0.0)
        self._prev_portfolio_value = state.get(
            "_prev_portfolio_value", self.initial_capital
        )

        start_time_str = state.get("start_time")
        if start_time_str:
            self.start_time = pd.Timestamp(start_time_str).to_pydatetime()

        self.holds = [StockHoldRecord(**h) for h in state.get("holds", [])]
        self.trades = [Trade(**t) for t in state.get("trades", [])]
        self.trade_pnl = state.get("trade_pnl", {})

    def get_positions(self) -> Positions:
        position_value = sum(h.market_value for h in self.holds)
        total_equity = self.available_balance + position_value
        return Positions(
            total=total_equity,
            available_balance=self.available_balance,
            total_profit=self.total_profit,
            daily_profit=self.daily_profit,
            holds=self.holds,
        )

    def get_available_balance(self):
        return self.available_balance

    def update_position_market_value(self, price_dict: Dict[str, float]) -> None:
        for hold in self.holds:
            if hold.symbol in price_dict:
                hold.market_value = hold.volume * price_dict[hold.symbol]

    def signal_buy(self, order: Order) -> Trade:
        cost = order.price * order.volume
        if self.available_balance < cost:
            raise ValueError(
                f"Insufficient balance for buy order. Available: {self.available_balance}, Required: {cost}"
            )

        self.available_balance -= cost
        self.total -= cost
        existing_hold = next((h for h in self.holds if h.symbol == order.symbol), None)

        if existing_hold:
            total_value = (existing_hold.avg_cost * existing_hold.volume) + (
                order.price * order.volume
            )
            total_quantity = existing_hold.volume + order.volume
            existing_hold.avg_cost = total_value / total_quantity
            existing_hold.volume = total_quantity
            existing_hold.market_value = existing_hold.avg_cost * existing_hold.volume
            existing_hold.sellable_volume = int(existing_hold.sellable_volume or 0)
        else:
            hold = StockHoldRecord(
                symbol=order.symbol,
                volume=order.volume,
                sellable_volume=0,
                avg_cost=order.price,
                market_value=order.price * order.volume,
                entry_time=self._now(),
            )
            self.holds.append(hold)

        trade = Trade(
            trade_id=self._generate_id("T"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(self._now()),
            symbol=order.symbol,
            trade_type="BUY",
            price=order.price,
            quantity=order.volume,
            amount=cost,
            commission=0.0,
            slippage=0.0,
            total_cost=cost,
            signal_reason=getattr(order, "signal_reason", None),
        )
        self.trades.append(trade)
        return trade

    def signal_sell(self, order: Order) -> Trade:
        if order.volume <= 0:
            raise ValueError(f"Sell volume must be positive: {order.volume}")

        hold_to_sell = next((h for h in self.holds if h.symbol == order.symbol), None)
        if not hold_to_sell or hold_to_sell.volume < order.volume:
            raise ValueError(
                f"Not enough shares to sell or stock not held: {order.symbol}"
            )

        proceeds = order.price * order.volume
        cost_basis = hold_to_sell.avg_cost * order.volume
        pnl = proceeds - cost_basis

        if order.symbol not in self.trade_pnl:
            self.trade_pnl[order.symbol] = 0.0
        self.trade_pnl[order.symbol] += pnl

        self.available_balance += proceeds
        self.total += pnl
        self.total_profit += pnl
        self.daily_profit += pnl

        hold_to_sell.volume -= order.volume
        hold_to_sell.market_value = hold_to_sell.avg_cost * hold_to_sell.volume
        if hold_to_sell.volume == 0:
            self.holds.remove(hold_to_sell)

        trade = Trade(
            trade_id=self._generate_id("T"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(self._now()),
            symbol=order.symbol,
            trade_type="SELL",
            price=order.price,
            quantity=order.volume,
            amount=proceeds,
            commission=0.0,
            slippage=0.0,
            total_cost=proceeds,
            signal_reason=getattr(order, "signal_reason", None),
        )
        self.trades.append(trade)
        return trade

    def compute_position_snapshot(
        self,
        hold: StockHoldRecord,
        trade_date: datetime = None,
    ) -> PositionSnapshot:
        if trade_date is None:
            trade_date = self._now()

        cost_basis = hold.avg_cost * hold.volume
        pnl = hold.market_value - cost_basis
        pnl_pct = pnl / cost_basis if cost_basis > 0 else 0
        current_price = hold.market_value / hold.volume if hold.volume > 0 else 0

        return PositionSnapshot(
            snapshot_id=self._generate_id("PS"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(trade_date),
            symbol=hold.symbol,
            quantity=hold.volume,
            avg_cost=hold.avg_cost,
            current_price=current_price,
            market_value=hold.market_value,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

    def compute_daily_metrics(
        self,
        trade_date: datetime,
        close_prices: Dict[str, float] = None,
    ) -> Tuple[DailyPerformance, List[PositionSnapshot]]:
        if close_prices:
            for hold in self.holds:
                if hold.symbol in close_prices:
                    hold.market_value = hold.volume * close_prices[hold.symbol]

        position_value = sum(h.market_value for h in self.holds)
        portfolio_value = self.available_balance + position_value
        prev_portfolio = self._prev_portfolio_value
        daily_return = (
            (portfolio_value - prev_portfolio) / prev_portfolio
            if prev_portfolio > 0
            else 0.0
        )
        cumulative_return = (
            (portfolio_value - self.initial_capital) / self.initial_capital
            if self.initial_capital > 0
            else 0
        )

        daily_perf = DailyPerformance(
            performance_id=self._generate_id("DP"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(trade_date),
            portfolio_value=portfolio_value,
            cash_balance=self.available_balance,
            position_value=position_value,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            daily_pnl=self.daily_profit,
            num_positions=len(self.holds),
        )
        snapshots = [
            self.compute_position_snapshot(hold, trade_date) for hold in self.holds
        ]

        self.daily_profit = 0.0
        self._prev_portfolio_value = portfolio_value
        return daily_perf, snapshots

    @property
    def executable_holds(self) -> List[StockHoldRecord]:
        today = self._now().date()
        return [
            hold.model_copy(update={"sellable_volume": int(hold.volume)})
            for hold in self.holds
            if hold.volume > 0 and hold.entry_time.date() < today
        ]
