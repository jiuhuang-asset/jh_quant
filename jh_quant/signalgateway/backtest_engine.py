"""
回测引擎 - 基于交易数据进行回测分析和统计

职责：
- 读取 OMS 的交易数据（trades）
- 计算回测统计指标（胜率、收益率、Sharpe比等）
- 生成回测会话报告（BacktestSession）
- 管理回测结果的持久化

架构：
OMS（订单系统）
  ├── 执行交易 (signal_buy/signal_sell)
  └── 生成交易记录 (trades)
        │
        └→ BacktestEngine（回测分析）
            ├── 读取交易记录
            ├── 计算统计指标
            └── 生成会话报告
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from .models import Trade, BacktestSession
from .order_recorder import OrderRecorder


class BacktestEngine:
    """回测分析引擎 - 基于交易数据进行分析"""

    def __init__(self, recorder: Optional[OrderRecorder] = None):
        """
        初始化回测引擎

        Args:
            recorder: 可选的订单记录器，用于持久化回测结果
        """
        self.recorder = recorder

    def analyze_session(
        self,
        session_id: str,
        initial_capital: float,
        trades: List[Trade],
        strategy_id: str,
        strategy_name: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
    ) -> BacktestSession:
        """
        分析一个回测会话

        Args:
            session_id: 会话ID
            initial_capital: 初始资金
            trades: 交易列表
            strategy_id: 策略ID
            strategy_name: 策略名称
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            BacktestSession: 回测会话报告
        """
        if not trades:
            # 没有交易，返回空会话
            return BacktestSession(
                session_id=session_id,
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                start_time=pd.Timestamp(start_time)
                if start_time
                else pd.Timestamp.now(),
                end_time=pd.Timestamp(end_time) if end_time else pd.Timestamp.now(),
                initial_capital=initial_capital,
                final_balance=initial_capital,
                total_return=0.0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_trades=0,
                avg_win=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
            )

        # 计算统计指标
        stats = self._calculate_statistics(trades, initial_capital)

        # 创建会话对象
        session = BacktestSession(
            session_id=session_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            start_time=pd.Timestamp(start_time)
            if start_time
            else pd.Timestamp(trades[0].trade_date),
            end_time=pd.Timestamp(end_time)
            if end_time
            else pd.Timestamp(trades[-1].trade_date),
            initial_capital=initial_capital,
            final_balance=stats["final_balance"],
            total_return=stats["total_return"],
            winning_trades=stats["winning_trades"],
            losing_trades=stats["losing_trades"],
            win_rate=stats["win_rate"],
            total_trades=stats["total_trades"],
            avg_win=stats["avg_win"],
            avg_loss=stats["avg_loss"],
            profit_factor=stats["profit_factor"],
        )

        # 保存到数据库
        if self.recorder and hasattr(self.recorder, "save_session"):
            try:
                self.recorder.save_session(session)
            except Exception as e:
                print(f"Failed to save session: {e}")

        return session

    def _calculate_statistics(
        self, trades: List[Trade], initial_capital: float
    ) -> Dict[str, Any]:
        """
        计算交易统计指标

        Args:
            trades: 交易列表
            initial_capital: 初始资金

        Returns:
            统计指标字典
        """
        if not trades:
            return {
                "total_trades": 0,
                "buy_trades": 0,
                "sell_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "total_profit": 0.0,
                "total_return": 0.0,
                "final_balance": initial_capital,
            }

        # 按symbol分组计算PnL
        trade_pnl = self._calculate_pnl_by_symbol(trades)

        # 统计数据
        buy_trades = [t for t in trades if t.trade_type == "BUY"]
        sell_trades = [t for t in trades if t.trade_type == "SELL"]

        # 计算胜负
        winning_count = sum(1 for pnl in trade_pnl.values() if pnl > 0)
        losing_count = sum(1 for pnl in trade_pnl.values() if pnl < 0)

        avg_win = (
            sum(pnl for pnl in trade_pnl.values() if pnl > 0) / winning_count
            if winning_count > 0
            else 0.0
        )
        avg_loss = (
            sum(pnl for pnl in trade_pnl.values() if pnl < 0) / losing_count
            if losing_count > 0
            else 0.0
        )

        total_profit = sum(pnl for pnl in trade_pnl.values())
        total_loss = sum(pnl for pnl in trade_pnl.values() if pnl < 0)

        profit_factor = (
            total_profit / abs(total_loss)
            if total_loss < 0 and total_loss != 0
            else (float("inf") if total_profit > 0 else 0.0)
        )

        win_rate = winning_count / len(trade_pnl) if trade_pnl else 0.0

        final_balance = initial_capital + total_profit
        total_return = (
            (final_balance - initial_capital) / initial_capital
            if initial_capital > 0
            else 0.0
        )

        return {
            "total_trades": len(trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "winning_trades": winning_count,
            "losing_trades": losing_count,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "total_profit": total_profit,
            "total_return": total_return,
            "final_balance": final_balance,
        }

    def _calculate_pnl_by_symbol(self, trades: List[Trade]) -> Dict[str, float]:
        """
        按symbol计算PnL

        Args:
            trades: 交易列表

        Returns:
            {symbol: pnl} 字典
        """
        pnl_map = {}

        for trade in trades:
            symbol = trade.symbol
            if symbol not in pnl_map:
                pnl_map[symbol] = 0.0

            if trade.trade_type == "SELL":
                # 卖出时计算PnL
                pnl_map[symbol] += trade.amount - trade.total_cost
            # 买入时不计算PnL，等待卖出时一起结算

        return pnl_map

    def print_report(self, session: BacktestSession):
        """
        打印回测报告

        Args:
            session: 回测会话
        """
        print("\n" + "=" * 60)
        print(f"回测报告: {session.strategy_name or session.strategy_id}")
        print("=" * 60)
        print(f"会话ID: {session.session_id}")
        print(f"初始资金: ¥{session.initial_capital:,.2f}")
        print(f"最终余额: ¥{session.final_balance:,.2f}")
        print(f"总收益率: {session.total_return * 100:,.2f}%")
        print(f"-" * 60)
        print(f"总交易数: {session.total_trades}")
        print(f"胜利交易: {session.winning_trades}")
        print(f"失败交易: {session.losing_trades}")
        print(f"胜率: {session.win_rate * 100:.2f}%")
        print(f"-" * 60)
        print(f"平均盈利: ¥{session.avg_win:,.2f}")
        print(f"平均亏损: ¥{session.avg_loss:,.2f}")
        print(f"利润因子: {session.profit_factor:.2f}")
        print(f"-" * 60)
        print(f"开始时间: {session.start_time}")
        print(f"结束时间: {session.end_time}")
        print("=" * 60 + "\n")
