import pandas as pd
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from datetime import datetime
import uuid
from typing import Tuple

from .models import (
    DailyPerformance,
    Order,
    Positions,
    PositionSnapshot,
    StockHoldRecord,
    Trade,
)


class OMS(ABC):
    """Order Management System - core trading interface only.

    Persistence is handled by the service layer via PersistenceCoordinator,
    not by OMS itself. Use compute_* methods to get data for persistence.
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


class MockOMS(OMS):
    """模拟OMS - 支持交易记录"""

    def __init__(
        self,
        initial_capital: float,
        session_id: Optional[str] = None,
        start_time: datetime = None,
        restore_from: Optional[str] = None,
        state_dict: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化模拟OMS

        Args:
            session_id: 会话ID
            initial_capital: 初始资金
            start_time: 开始时间
            restore_from: 恢复方式 - 'auto'(优先DB)、'db'(仅DB)、'state'(仅state_dict)、None(新建)
            state_dict: 状态字典，当restore_from='state'或'auto'时使用
        """
        self.session_id = session_id or f"oms_{uuid.uuid4().hex}"
        self.initial_capital = initial_capital
        self.total = initial_capital
        self.available_balance = initial_capital
        self.total_profit = 0.0
        self.daily_profit = 0.0
        self.holds: List[StockHoldRecord] = []
        self.start_time = start_time or datetime.now()

        # 交易相关
        self.trades: List[Trade] = []
        self.trade_pnl: Dict[str, float] = {}  # 用于计算胜率等

        # 从 state_dict 恢复（不含DB，DB恢复由service层处理）
        if state_dict and restore_from in ("auto", "state"):
            try:
                self.import_state(state_dict)
            except Exception:
                pass

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        self._session_id = value

    def _generate_id(self, prefix: str) -> str:
        """生成唯一ID"""
        return f"{prefix}_{self.session_id}_{uuid.uuid4().hex[:8]}"

    def export_state(self) -> Dict[str, Any]:
        """
        导出当前OMS状态快照

        Returns:
            包含所有关键状态的字典
        """

        # 将持仓和交易数据转换为可JSON序列化的格式
        def convert_to_serializable(obj):
            """递归转换所有不可JSON序列化的对象"""
            if isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            elif isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif hasattr(obj, "isoformat"):  # datetime 对象
                return obj.isoformat()
            elif isinstance(obj, (int, float, str, bool, type(None))):
                return obj
            else:
                # 对于其他类型，尝试转换为字符串
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
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "holds": convert_to_serializable(holds_data),
            "trades": convert_to_serializable(trades_data),
            "trade_pnl": self.trade_pnl,
            "export_time": datetime.now().isoformat(),
        }

    def import_state(self, state: Dict[str, Any]) -> None:
        """
        从状态字典恢复OMS状态

        Args:
            state: 通过export_state()导出的状态字典
        """
        self.session_id = state.get("session_id", self.session_id)
        self.initial_capital = state.get("initial_capital", self.initial_capital)
        self.total = state.get("total", self.initial_capital)
        self.available_balance = state.get("available_balance", self.initial_capital)
        self.total_profit = state.get("total_profit", 0.0)
        self.daily_profit = state.get("daily_profit", 0.0)

        # 恢复start_time
        start_time_str = state.get("start_time")
        if start_time_str:
            self.start_time = pd.Timestamp(start_time_str).to_pydatetime()

        # 恢复持仓
        self.holds = [StockHoldRecord(**h) for h in state.get("holds", [])]

        # 恢复交易记录
        self.trades = [Trade(**t) for t in state.get("trades", [])]

        # 恢复PnL记录
        self.trade_pnl = state.get("trade_pnl", {})

    def get_positions(self) -> Positions:
        # 计算当前持仓的总市值
        position_value = sum(h.market_value for h in self.holds)
        # 总权益 = 可用现金 + 持仓市值
        total_equity = self.available_balance + position_value

        positions = Positions(
            total=total_equity,
            available_balance=self.available_balance,
            total_profit=self.total_profit,
            daily_profit=self.daily_profit,
            holds=self.holds,
        )
        return positions

    def get_available_balance(self):
        return self.available_balance

    def update_position_market_value(self, price_dict: Dict[str, float]) -> None:
        """
        更新所有持仓的市值（当股价发生变化时调用）

        Args:
            price_dict: 符号到最新价格的映射 {symbol: price}
        """
        for hold in self.holds:
            if hold.symbol in price_dict:
                hold.market_value = hold.volume * price_dict[hold.symbol]

    def signal_buy(self, order: Order) -> Trade:
        """
        执行买入订单
        """
        # 验证余额
        cost = order.price * order.volume
        if self.available_balance < cost:
            raise ValueError(
                f"Insufficient balance for buy order. Available: {self.available_balance}, Required: {cost}"
            )

        # 扣除资金
        self.available_balance -= cost
        self.total -= cost

        # 更新或创建持仓
        existing_hold = next((h for h in self.holds if h.symbol == order.symbol), None)

        if existing_hold:
            # 更新已有持仓 - 重新计算平均成本
            total_value = (existing_hold.avg_cost * existing_hold.volume) + (
                order.price * order.volume
            )
            total_quantity = existing_hold.volume + order.volume
            existing_hold.avg_cost = total_value / total_quantity
            existing_hold.volume = total_quantity
            existing_hold.market_value = existing_hold.avg_cost * existing_hold.volume
        else:
            # 创建新持仓
            hold = StockHoldRecord(
                symbol=order.symbol,
                volume=order.volume,
                avg_cost=order.price,
                market_value=order.price * order.volume,
            )
            self.holds.append(hold)

        # 生成交易记录
        trade = Trade(
            trade_id=self._generate_id("T"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(datetime.now()),
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

        # 记录交易
        self.trades.append(trade)

        return trade

    def signal_sell(self, order: Order) -> Trade:
        """
        执行卖出订单
        """
        # 验证卖出数量
        if order.volume <= 0:
            raise ValueError(f"Sell volume must be positive: {order.volume}")

        # 查找持仓
        hold_to_sell = next((h for h in self.holds if h.symbol == order.symbol), None)

        if not hold_to_sell or hold_to_sell.volume < order.volume:
            raise ValueError(
                f"Not enough shares to sell or stock not held: {order.symbol}"
            )

        # 计算收益
        proceeds = order.price * order.volume
        cost_basis = hold_to_sell.avg_cost * order.volume
        pnl = proceeds - cost_basis

        # 记录PnL用于统计
        if order.symbol not in self.trade_pnl:
            self.trade_pnl[order.symbol] = 0.0
        self.trade_pnl[order.symbol] += pnl

        # 更新资金
        self.available_balance += proceeds
        self.total += pnl
        self.total_profit += pnl
        self.daily_profit += pnl

        # 更新持仓
        hold_to_sell.volume -= order.volume
        hold_to_sell.market_value = hold_to_sell.avg_cost * hold_to_sell.volume

        # 移除空持仓
        if hold_to_sell.volume == 0:
            self.holds.remove(hold_to_sell)

        # 生成交易记录
        trade = Trade(
            trade_id=self._generate_id("T"),
            session_id=self.session_id,
            trade_date=pd.Timestamp(datetime.now()),
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

        # 记录交易
        self.trades.append(trade)

        return trade

    def compute_position_snapshot(
        self,
        hold: StockHoldRecord,
        trade_date: datetime = None,
    ) -> PositionSnapshot:
        """
        Compute a position snapshot from current hold state.
        Does NOT persist - caller is responsible for persistence.

        Args:
            hold: The hold to snapshot
            trade_date: Snapshot date, defaults to now

        Returns:
            PositionSnapshot object
        """
        if trade_date is None:
            trade_date = datetime.now()

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
        """
        Compute daily performance and position snapshots from current state.
        Does NOT persist - caller passes results to PersistenceCoordinator.

        Args:
            trade_date: The trading date for the snapshot
            close_prices: Optional closing prices to update hold market values
                          before computing

        Returns:
            Tuple of (DailyPerformance, List[PositionSnapshot])
        """
        # Update hold market values from close prices
        if close_prices:
            for hold in self.holds:
                if hold.symbol in close_prices:
                    hold.market_value = hold.volume * close_prices[hold.symbol]

        # Compute portfolio metrics
        position_value = sum(h.market_value for h in self.holds)
        portfolio_value = self.available_balance + position_value

        prev_portfolio = self.total - self.daily_profit
        daily_return = (
            (portfolio_value - prev_portfolio) / prev_portfolio
            if prev_portfolio > 0
            else 0
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

        # Reset daily profit after computing
        self.daily_profit = 0.0

        return daily_perf, snapshots

    @property
    def executable_holds(self) -> List[StockHoldRecord]:
        """Positions eligible for sale (T+1 gate: bought on a prior calendar day)."""
        today = datetime.now().date()
        holds = [
            hold
            for hold in self.holds
            if hold.volume > 0 and hold.entry_time.date() < today
        ]

        return holds
