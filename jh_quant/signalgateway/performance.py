"""
Performance analytics helpers for persistence-backed trading sessions.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Optional, Protocol

import pandas as pd

HOLDING_RETURN_COLUMNS = [
    "symbol",
    "quantity",
    "avg_cost",
    "current_price",
    "market_value",
    "pnl",
    "pnl_pct",
    "latest_date",
]

TURNOVER_COLUMNS = [
    "trade_date",
    "position_value",
    "portfolio_value",
    "trade_amount",
    "turnover_ratio",
]


class PerformanceDataSource(Protocol):
    def query_trades(self, session_id: str) -> pd.DataFrame: ...

    def query_daily_performance(self, session_id: str) -> pd.DataFrame: ...

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame: ...


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _normalize_trade_dates(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(frame[column], errors="coerce")


def _load_daily_position_values(
    source: PerformanceDataSource,
    session_id: str,
    daily_perf: Optional[pd.DataFrame] = None,
    snaps: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    daily_perf = source.query_daily_performance(session_id) if daily_perf is None else daily_perf
    if not daily_perf.empty:
        daily_perf = daily_perf.copy()
        daily_perf["trade_date"] = pd.to_datetime(daily_perf["trade_date"], errors="coerce")
        return daily_perf[["trade_date", "position_value", "portfolio_value"]].dropna(
            subset=["trade_date"]
        )

    snaps = source.query_position_snapshots(session_id) if snaps is None else snaps
    if snaps.empty:
        return _empty_frame(["trade_date", "position_value", "portfolio_value"])

    snaps = snaps.copy()
    snaps["trade_date"] = pd.to_datetime(snaps["trade_date"], errors="coerce")
    snaps["trade_day"] = snaps["trade_date"].dt.normalize()
    daily_positions = (
        snaps.sort_values("trade_date")
        .groupby(["trade_day", "symbol"], as_index=False)
        .last()
        .groupby("trade_day", as_index=False)["market_value"]
        .sum()
        .rename(columns={"trade_day": "trade_date", "market_value": "position_value"})
    )
    daily_positions["portfolio_value"] = daily_positions["position_value"]
    return daily_positions


def calculate_holding_returns(
    source: PerformanceDataSource,
    session_id: str,
    snaps: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    snaps = source.query_position_snapshots(session_id) if snaps is None else snaps
    if snaps.empty:
        return _empty_frame(HOLDING_RETURN_COLUMNS)

    snaps = snaps.copy()
    snaps["trade_date"] = pd.to_datetime(snaps["trade_date"], errors="coerce")
    latest = snaps.sort_values("trade_date").groupby("symbol").last().reset_index()
    latest.rename(columns={"trade_date": "latest_date"}, inplace=True)
    return latest[
        [
            "symbol",
            "quantity",
            "avg_cost",
            "current_price",
            "market_value",
            "pnl",
            "pnl_pct",
            "latest_date",
        ]
    ]


def calculate_turnover(
    source: PerformanceDataSource,
    session_id: str,
    trades: Optional[pd.DataFrame] = None,
    daily_perf: Optional[pd.DataFrame] = None,
    snaps: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    daily_values = _load_daily_position_values(
        source,
        session_id,
        daily_perf=daily_perf,
        snaps=snaps,
    )
    if daily_values.empty:
        return _empty_frame(TURNOVER_COLUMNS)

    trades = source.query_trades(session_id) if trades is None else trades
    if trades.empty:
        result = daily_values.copy()
        result["trade_amount"] = 0.0
        result["turnover_ratio"] = 0.0
        return result[TURNOVER_COLUMNS]

    trades = trades.copy()
    trades["trade_date"] = _normalize_trade_dates(trades, "trade_date")
    trades["trade_day"] = trades["trade_date"].dt.normalize()
    daily_trades = (
        trades.groupby("trade_day", as_index=False)["amount"]
        .sum()
        .rename(columns={"trade_day": "trade_date", "amount": "trade_amount"})
    )

    result = daily_values.merge(daily_trades, on="trade_date", how="left")
    result["trade_amount"] = result["trade_amount"].fillna(0.0)
    denominator = result["portfolio_value"].where(result["portfolio_value"] > 0)
    result["turnover_ratio"] = (result["trade_amount"] / denominator).fillna(0.0)
    return result[TURNOVER_COLUMNS]


def _realized_pnl_from_trades(trades: pd.DataFrame) -> list[float]:
    costs: dict[str, float] = defaultdict(float)
    quantities: dict[str, int] = defaultdict(int)
    realized: list[float] = []

    ordered = trades.copy()
    ordered["trade_date"] = _normalize_trade_dates(ordered, "trade_date")
    ordered = ordered.sort_values(["trade_date", "trade_id"])

    for _, row in ordered.iterrows():
        symbol = row["symbol"]
        qty = int(row["quantity"])
        price = float(row["price"])
        trade_type = row["trade_type"]

        if trade_type == "BUY":
            total_qty = quantities[symbol] + qty
            if total_qty <= 0:
                costs[symbol] = 0.0
                quantities[symbol] = 0
                continue
            weighted_cost = ((costs[symbol] * quantities[symbol]) + (price * qty)) / total_qty
            quantities[symbol] = total_qty
            costs[symbol] = weighted_cost
            continue

        avg_cost = costs[symbol]
        sell_qty = min(qty, quantities[symbol]) if quantities[symbol] > 0 else qty
        pnl = (price - avg_cost) * sell_qty
        realized.append(float(pnl))
        quantities[symbol] = max(0, quantities[symbol] - sell_qty)
        if quantities[symbol] == 0:
            costs[symbol] = 0.0

    return realized


def get_performance_summary(
    source: PerformanceDataSource,
    session_id: str,
    trades: Optional[pd.DataFrame] = None,
    daily_perf: Optional[pd.DataFrame] = None,
    snaps: Optional[pd.DataFrame] = None,
    holding_returns: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    trades = source.query_trades(session_id) if trades is None else trades
    daily_values = _load_daily_position_values(
        source,
        session_id,
        daily_perf=daily_perf,
        snaps=snaps,
    )
    holding_returns = (
        calculate_holding_returns(source, session_id, snaps=snaps)
        if holding_returns is None
        else holding_returns
    )

    result: Dict[str, Any] = {
        "total_trades": 0,
        "buy_count": 0,
        "sell_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": None,
        "avg_win": None,
        "avg_loss": None,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "max_drawdown": 0.0,
    }

    if trades.empty:
        if not holding_returns.empty:
            result["unrealized_pnl"] = float(holding_returns["pnl"].fillna(0.0).sum())
            result["total_pnl"] = result["unrealized_pnl"]
        return result

    buys = trades[trades["trade_type"] == "BUY"]
    sells = trades[trades["trade_type"] == "SELL"]
    result["total_trades"] = int(len(trades))
    result["buy_count"] = int(len(buys))
    result["sell_count"] = int(len(sells))

    realized_pnls = _realized_pnl_from_trades(trades)
    if realized_pnls:
        realized_series = pd.Series(realized_pnls, dtype=float)
        wins = realized_series[realized_series > 0]
        losses = realized_series[realized_series <= 0]
        result["win_count"] = int(len(wins))
        result["loss_count"] = int(len(losses))
        total_closed = len(realized_series)
        result["win_rate"] = float(len(wins) / total_closed) if total_closed else None
        result["avg_win"] = float(wins.mean()) if not wins.empty else None
        result["avg_loss"] = float(losses.mean()) if not losses.empty else None
        result["realized_pnl"] = float(realized_series.sum())

    if not holding_returns.empty:
        result["unrealized_pnl"] = float(holding_returns["pnl"].fillna(0.0).sum())
    result["total_pnl"] = result["realized_pnl"] + result["unrealized_pnl"]

    if not daily_values.empty:
        equity_curve = daily_values.sort_values("trade_date")["portfolio_value"].astype(float)
        running_peak = equity_curve.cummax()
        drawdown = ((equity_curve - running_peak) / running_peak.replace(0, pd.NA)).fillna(0.0)
        result["max_drawdown"] = float(drawdown.min())

    return result


def build_performance_report(
    source: PerformanceDataSource,
    session_id: str,
) -> Dict[str, Any]:
    trades = source.query_trades(session_id)
    daily_perf = source.query_daily_performance(session_id)
    snaps = source.query_position_snapshots(session_id)
    holding_returns = calculate_holding_returns(source, session_id, snaps=snaps)
    turnover = calculate_turnover(
        source,
        session_id,
        trades=trades,
        daily_perf=daily_perf,
        snaps=snaps,
    )
    summary = get_performance_summary(
        source,
        session_id,
        trades=trades,
        daily_perf=daily_perf,
        snaps=snaps,
        holding_returns=holding_returns,
    )
    return {
        "summary": summary,
        "holding_returns": holding_returns,
        "turnover": turnover,
    }
