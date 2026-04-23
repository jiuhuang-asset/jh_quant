import pandas as pd
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from datetime import timedelta, datetime
import uuid
from .models import (
    Positions,
    StockHoldRecord,
    Order,
    Trade,
    DailyPerformance,
    PositionSnapshot,
)


class OMS(ABC):
    """Order Management System 基类"""

    @abstractmethod
    def get_positions(self) -> Positions:
        ...

    @abstractmethod
    def get_available_balance(self):
        ...

    @abstractmethod
    def signal_buy(self, order: Order) -> Trade:
        """
        执行买入订单
        返回交易记录
        """
        ...

    @abstractmethod
    def signal_sell(self, order: Order) -> Trade:
        """
        执行卖出订单
        返回交易记录
        """
        ...

    @abstractmethod
    def save_trade(self, trade: Trade):
        """保存交易到数据库"""
        ...

    @abstractmethod
    def save_daily_performance(self, daily_perf: DailyPerformance):
        """保存日度表现"""
        ...

    @abstractmethod
    def save_position_snapshot(self, snapshot: PositionSnapshot):
        """保存持仓快照"""
        ...

    @abstractmethod
    def save_state_snapshot(self):
        ...

    @property
    @abstractmethod
    def executable_holds(self) -> List[StockHoldRecord]:
        ...


class MockOMS(OMS):
    """模拟OMS - 支持交易记录"""

    def __init__(
        self,
        initial_capital: float,
        session_id: Optional[str] = None,
        start_time: datetime = None,
        recorder=None,
        restore_from: Optional[str] = None,
        state_dict: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化模拟OMS

        Args:
            session_id: 会话ID
            initial_capital: 初始资金
            start_time: 开始时间
            recorder: 订单记录器实例（OrderRecorder）
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
        self.recorder = recorder

        # 交易相关
        self.trades: List[Trade] = []
        self.trade_pnl: Dict[str, float] = {}  # 用于计算胜率等

        # 尝试恢复状态
        if restore_from:
            self._restore_state(restore_from, state_dict)

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

    def _restore_state(
        self, restore_from: str, state_dict: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        内部方法：根据restore_from参数恢复状态

        Args:
            restore_from: 'auto'(优先DB或state_dict)、'db'(仅DB)、'state'(仅state_dict)
            state_dict: 备选状态字典

        Returns:
            True if restored successfully, False otherwise
        """
        restored = False

        if restore_from == "auto" or restore_from == "db":
            if self.recorder:
                try:
                    state = self._load_state_from_db()
                    if state:
                        self.import_state(state)
                        restored = True
                        print(
                            f"State restored for session {self.session_id}. "
                            f"Cash: {self.available_balance}, Holdings: {len(self.holds)}, "
                            f"Trades: {len(self.trades)}"
                        )
                except Exception as e:
                    print(f"Failed to restore from DB: {e}")
                    if restore_from == "db":
                        return False

        if not restored and (restore_from == "auto" or restore_from == "state"):
            if state_dict:
                try:
                    self.import_state(state_dict)
                    restored = True
                except Exception as e:
                    print(f"Failed to restore from state_dict: {e}")

        return restored

    def _load_state_from_db(self) -> Optional[Dict[str, Any]]:
        """
        从数据库加载最新的session状态
        由recorder实现具体的DB查询逻辑

        Returns:
            状态字典，如果不存在则返回None
        """
        if not self.recorder:
            return None
        try:
            # 调用recorder的方法获取最新状态
            # 这个方法需要在recorder中实现
            if hasattr(self.recorder, "load_latest_session_state"):
                return self.recorder.load_latest_session_state(self.session_id)
            else:
                print(
                    "Warning: recorder does not have load_latest_session_state method"
                )
                return None
        except Exception as e:
            print(f"Error loading state from DB: {e}")
            return None

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
        self.save_trade(trade)

        # 立即保存更新后的持仓快照，防止数据不一致
        current_hold = next((h for h in self.holds if h.symbol == order.symbol), None)
        if current_hold:
            self._save_position_snapshot(current_hold)

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
        self.save_trade(trade)

        # 立即保存更新后的持仓快照，防止数据不一致
        # 注意：卖出后hold可能被移除，但需要在移除前保存
        current_hold = next((h for h in self.holds if h.symbol == order.symbol), None)
        if current_hold and current_hold.volume > 0:
            self._save_position_snapshot(current_hold)

        return trade

    def save_trade(self, trade: Trade):
        """保存交易到数据库"""
        if self.recorder is None:
            return

        try:
            self.recorder.save_trade(trade)
        except Exception as e:
            print(f"Failed to save trade: {e}")

    def save_daily_performance(self, daily_perf: DailyPerformance):
        """保存日度表现"""
        if self.recorder is None:
            return

        try:
            self.recorder.save_daily_snapshot(daily_perf)
        except Exception as e:
            print(f"Failed to save daily performance: {e}")

    def save_position_snapshot(self, snapshot: PositionSnapshot):
        """保存持仓快照"""
        if self.recorder is None:
            return

        try:
            self.recorder.save_position_snapshot(snapshot)
        except Exception as e:
            print(f"Failed to save position snapshot: {e}")

    def _save_position_snapshot(
        self, hold: StockHoldRecord, trade_date: datetime = None
    ):
        """
        立即保存单个持仓的快照（用于交易后立即保存，防止数据丢失）

        Args:
            hold: 要保存的持仓对象
            trade_date: 快照日期，默认为当前时间
        """
        if trade_date is None:
            trade_date = datetime.now()

        cost_basis = hold.avg_cost * hold.volume
        pnl = hold.market_value - cost_basis
        pnl_pct = pnl / cost_basis if cost_basis > 0 else 0
        current_price = hold.market_value / hold.volume if hold.volume > 0 else 0

        snapshot = PositionSnapshot(
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

        self.save_position_snapshot(snapshot)

    def save_daily_snapshot(
        self, trade_date: datetime, close_prices: Dict[str, float] = None
    ):
        """
        在每天结束时保存日度表现和持仓快照

        Args:
            trade_date: 交易日期
            close_prices: 当日收盘价格字典 {symbol: close_price}
                         如果提供，将使用该价格更新所有持仓的市值
                         如果不提供，使用hold.market_value（可能不准确）
        """
        # 如果提供了收盘价，更新所有持仓的市值
        if close_prices:
            for hold in self.holds:
                if hold.symbol in close_prices:
                    hold.market_value = hold.volume * close_prices[hold.symbol]

        # 计算投资组合价值
        position_value = sum(h.market_value for h in self.holds)
        portfolio_value = self.available_balance + position_value

        # 计算收益率
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

        # 创建日度表现记录
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

        self.save_daily_performance(daily_perf)

        # 为每个持仓保存快照
        for hold in self.holds:
            cost_basis = hold.avg_cost * hold.volume
            pnl = hold.market_value - cost_basis
            pnl_pct = pnl / cost_basis if cost_basis > 0 else 0
            current_price = hold.market_value / hold.volume if hold.volume > 0 else 0

            snapshot = PositionSnapshot(
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

            self.save_position_snapshot(snapshot)

        # 重置日盈利
        self.daily_profit = 0.0

    def save_state_snapshot(self) -> Dict[str, Any]:
        """
        保存当前状态快照到DB（如果recorder支持）

        Returns:
            导出的状态字典
        """
        state = self.export_state()

        if self.recorder and hasattr(self.recorder, "save_session_state"):
            try:
                self.recorder.save_session_state(state)
                print(f"Session state saved for {self.session_id}")
            except Exception as e:
                print(f"Failed to save session state: {e}")

        return state

    @property
    def executable_holds(self) -> List[StockHoldRecord]:
        holds = [
            hold
            for hold in self.holds
            if hold.volume > 0
            and hold.buy_date
            <= (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        ]

        return holds
