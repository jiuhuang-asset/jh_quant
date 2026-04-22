"""
Performance analytics — 计算持仓收益、换手率、绩效汇总。

所有计算函数都接收 OrderRecorder 实例和 session_id，
不直接依赖数据库实现。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

if TYPE_CHECKING:
    from .order_recorder import OrderRecorder


def calculate_holding_returns(recorder: "OrderRecorder", session_id: str) -> pd.DataFrame:
    """从持仓快照快速计算每个持仓的累计收益

    Returns DataFrame with columns:
        symbol, quantity, avg_cost, current_price, market_value,
        pnl, pnl_pct, latest_date
    """
    snaps = recorder.query_position_snapshots(session_id)
    if snaps.empty:
        return pd.DataFrame()

    latest = (
        snaps.sort_values("trade_date")
        .groupby("symbol")
        .last()
        .reset_index()
    )
    return latest[
        ["symbol", "quantity", "avg_cost", "current_price", "market_value", "pnl", "pnl_pct", "trade_date"]
    ].rename(columns={"trade_date": "latest_date"})


def calculate_turnover(recorder: "OrderRecorder", session_id: str) -> pd.DataFrame:
    """计算每日换手率（成交额 / 总持仓市值）

    Returns DataFrame with columns:
        trade_date, position_value, trade_amount, turnover_ratio
    """
    snaps = recorder.query_position_snapshots(session_id)
    if snaps.empty:
        return pd.DataFrame()

    daily_value = (
        snaps.groupby("trade_date")["market_value"]
        .sum()
        .reset_index()
        .rename(columns={"market_value": "position_value"})
    )

    trades = recorder.query_trades(session_id)
    if not trades.empty:
        daily_trades = (
            trades.groupby(trades["trade_date"].dt.date)["amount"]
            .sum()
            .reset_index()
            .rename(columns={"trade_date": "trade_date", "amount": "trade_amount"})
        )
        daily_trades["trade_date"] = pd.to_datetime(daily_trades["trade_date"])
        result = daily_value.merge(daily_trades, on="trade_date", how="left")
        result["turnover_ratio"] = result["trade_amount"] / result["position_value"]
        return result[["trade_date", "position_value", "trade_amount", "turnover_ratio"]]

    daily_value["turnover_ratio"] = 0.0
    return daily_value


def get_performance_summary(recorder: "OrderRecorder", session_id: str) -> Dict[str, Any]:
    """从交易记录和快照快速汇总关键绩效指标

    Returns dict:
        total_trades, buy_count, sell_count, win_count, loss_count,
        win_rate, avg_win, avg_loss, total_pnl, max_drawdown
    """
    trades = recorder.query_trades(session_id)
    snaps = recorder.query_position_snapshots(session_id)

    result: Dict[str, Any] = {
        "total_trades": 0,
        "buy_count": 0,
        "sell_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": None,
        "avg_win": None,
        "avg_loss": None,
        "total_pnl": 0.0,
        "max_drawdown": 0.0,
    }

    if trades.empty:
        return result

    buys = trades[trades["trade_type"] == "BUY"]
    sells = trades[trades["trade_type"] == "SELL"]
    result["total_trades"] = len(trades)
    result["buy_count"] = len(buys)
    result["sell_count"] = len(sells)

    # 卖出记录含 amount（成交额），可近似计算单笔盈亏
    if not sells.empty:
        sells = sells.copy()
        sells["pnl"] = sells["amount"]  # 简化估算，实际应关联对应买入计算成本
        wins = sells[sells["pnl"] > 0]
        losses = sells[sells["pnl"] <= 0]
        result["win_count"] = len(wins)
        result["loss_count"] = len(losses)
        total = len(wins) + len(losses)
        result["win_rate"] = len(wins) / total if total > 0 else None
        result["avg_win"] = float(wins["pnl"].mean()) if not wins.empty else None
        result["avg_loss"] = float(losses["pnl"].mean()) if not losses.empty else None
        result["total_pnl"] = float(sells["pnl"].sum())

    # 最大回撤从 snapshot 的累计最高市值计算
    if not snaps.empty:
        snaps = snaps.sort_values("trade_date")
        snaps["cumulative_max"] = snaps["market_value"].cummax()
        snaps["drawdown"] = (snaps["market_value"] - snaps["cumulative_max"]) / snaps["cumulative_max"]
        result["max_drawdown"] = float(snaps["drawdown"].min())

    return result
