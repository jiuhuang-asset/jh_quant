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

EQUITY_CURVE_COLUMNS = [
    "trade_date",
    "portfolio_value",
    "cash_balance",
    "position_value",
    "daily_return",
    "cumulative_return",
    "daily_pnl",
    "num_positions",
    "drawdown",
]

TRADE_ACTIVITY_COLUMNS = [
    "trade_date",
    "trade_count",
    "buy_count",
    "sell_count",
    "buy_amount",
    "sell_amount",
    "net_amount",
]


class PerformanceDataSource(Protocol):
    def query_trades(self, session_id: str) -> pd.DataFrame: ...

    def query_daily_performance(self, session_id: str) -> pd.DataFrame: ...

    def query_position_snapshots(self, session_id: str) -> pd.DataFrame: ...


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _normalize_trade_dates(frame: pd.DataFrame, column: str) -> pd.Series:
    series = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return series.dt.tz_localize(None)


def _load_daily_position_values(
    source: PerformanceDataSource,
    session_id: str,
    daily_perf: Optional[pd.DataFrame] = None,
    snaps: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    daily_perf = (
        source.query_daily_performance(session_id) if daily_perf is None else daily_perf
    )
    if not daily_perf.empty:
        daily_perf = daily_perf.copy()
        daily_perf["trade_date"] = _normalize_trade_dates(daily_perf, "trade_date")
        return daily_perf[["trade_date", "position_value", "portfolio_value"]].dropna(
            subset=["trade_date"]
        )

    snaps = source.query_position_snapshots(session_id) if snaps is None else snaps
    if snaps.empty:
        return _empty_frame(["trade_date", "position_value", "portfolio_value"])

    snaps = snaps.copy()
    snaps["trade_date"] = _normalize_trade_dates(snaps, "trade_date")
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
    snaps["trade_date"] = _normalize_trade_dates(snaps, "trade_date")
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


def calculate_equity_curve(
    source: PerformanceDataSource,
    session_id: str,
    daily_perf: Optional[pd.DataFrame] = None,
    snaps: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    daily_perf = (
        source.query_daily_performance(session_id) if daily_perf is None else daily_perf
    )
    if not daily_perf.empty:
        result = daily_perf.copy()
        result["trade_date"] = _normalize_trade_dates(result, "trade_date")
        result = result.sort_values("trade_date")
        result["portfolio_value"] = result["portfolio_value"].astype(float)
        initial_value = result["portfolio_value"].iloc[0]
        if initial_value and initial_value > 0:
            result["cumulative_return"] = (
                result["portfolio_value"] - initial_value
            ) / initial_value
        else:
            result["cumulative_return"] = 0.0
        result["daily_return"] = result["portfolio_value"].pct_change().fillna(0.0)
        peak = result["portfolio_value"].cummax()
        result["drawdown"] = (
            (result["portfolio_value"] - peak) / peak.replace(0, pd.NA)
        ).fillna(0.0)
        for column in EQUITY_CURVE_COLUMNS:
            if column not in result.columns:
                result[column] = 0.0 if column != "trade_date" else pd.NaT
        return result[EQUITY_CURVE_COLUMNS]

    daily_values = _load_daily_position_values(
        source,
        session_id,
        daily_perf=daily_perf,
        snaps=snaps,
    )
    if daily_values.empty:
        return _empty_frame(EQUITY_CURVE_COLUMNS)

    result = daily_values.copy().sort_values("trade_date")
    result["cash_balance"] = 0.0
    result["daily_return"] = 0.0
    result["cumulative_return"] = 0.0
    result["daily_pnl"] = 0.0
    result["num_positions"] = 0
    peak = result["portfolio_value"].astype(float).cummax()
    result["drawdown"] = (
        (result["portfolio_value"].astype(float) - peak) / peak.replace(0, pd.NA)
    ).fillna(0.0)
    return result[EQUITY_CURVE_COLUMNS]


def calculate_trade_activity(
    source: PerformanceDataSource,
    session_id: str,
    trades: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    trades = source.query_trades(session_id) if trades is None else trades
    if trades.empty:
        return _empty_frame(TRADE_ACTIVITY_COLUMNS)

    normalized = trades.copy()
    normalized["trade_date"] = _normalize_trade_dates(normalized, "trade_date")
    normalized["trade_day"] = normalized["trade_date"].dt.normalize()
    normalized["buy_amount"] = normalized["amount"].where(
        normalized["trade_type"] == "BUY",
        0.0,
    )
    normalized["sell_amount"] = normalized["amount"].where(
        normalized["trade_type"] == "SELL",
        0.0,
    )
    grouped = (
        normalized.groupby("trade_day", as_index=False)
        .agg(
            trade_count=("trade_id", "count"),
            buy_count=("trade_type", lambda values: int((values == "BUY").sum())),
            sell_count=("trade_type", lambda values: int((values == "SELL").sum())),
            buy_amount=("buy_amount", "sum"),
            sell_amount=("sell_amount", "sum"),
        )
        .rename(columns={"trade_day": "trade_date"})
    )
    grouped["net_amount"] = grouped["buy_amount"] - grouped["sell_amount"]
    return grouped[TRADE_ACTIVITY_COLUMNS]


def summarize_position_exposure(
    holding_returns: pd.DataFrame,
    equity_curve: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    if holding_returns.empty:
        return {
            "position_count": 0,
            "gross_market_value": 0.0,
            "cash_ratio": 1.0,
            "invested_ratio": 0.0,
            "max_position_weight": 0.0,
            "top3_concentration": 0.0,
            "top_positions": [],
        }

    latest = holding_returns.copy().sort_values("market_value", ascending=False)
    gross_market_value = float(latest["market_value"].fillna(0.0).sum())
    latest_portfolio_value = gross_market_value
    latest_cash_balance = 0.0

    if equity_curve is not None and not equity_curve.empty:
        last_row = equity_curve.sort_values("trade_date").iloc[-1]
        latest_portfolio_value = float(
            last_row.get("portfolio_value", gross_market_value) or 0.0
        )
        latest_cash_balance = float(last_row.get("cash_balance", 0.0) or 0.0)

    denominator = (
        latest_portfolio_value if latest_portfolio_value > 0 else gross_market_value
    )
    weights = (
        latest["market_value"].astype(float) / denominator
        if denominator > 0
        else pd.Series([0.0] * len(latest))
    )
    latest["weight"] = weights.fillna(0.0)

    top_positions = latest.head(5)[
        ["symbol", "market_value", "pnl", "pnl_pct", "weight"]
    ].to_dict(orient="records")

    invested_ratio = (
        gross_market_value / latest_portfolio_value
        if latest_portfolio_value > 0
        else 0.0
    )
    cash_ratio = (
        latest_cash_balance / latest_portfolio_value
        if latest_portfolio_value > 0
        else 1.0
    )
    return {
        "position_count": int(len(latest)),
        "gross_market_value": gross_market_value,
        "cash_ratio": float(cash_ratio),
        "invested_ratio": float(invested_ratio),
        "max_position_weight": (
            float(latest["weight"].max()) if not latest.empty else 0.0
        ),
        "top3_concentration": (
            float(latest["weight"].head(3).sum()) if not latest.empty else 0.0
        ),
        "top_positions": top_positions,
    }


def summarize_latest_portfolio(equity_curve: pd.DataFrame) -> Dict[str, Any]:
    if equity_curve.empty:
        return {}

    last_row = equity_curve.sort_values("trade_date").iloc[-1]
    portfolio_value = float(last_row.get("portfolio_value", 0.0) or 0.0)
    cash_balance = float(last_row.get("cash_balance", 0.0) or 0.0)
    position_value = float(last_row.get("position_value", 0.0) or 0.0)
    return {
        "trade_date": last_row.get("trade_date"),
        "portfolio_value": portfolio_value,
        "cash_balance": cash_balance,
        "position_value": position_value,
        "cash_ratio": (cash_balance / portfolio_value) if portfolio_value > 0 else 1.0,
        "invested_ratio": (
            (position_value / portfolio_value) if portfolio_value > 0 else 0.0
        ),
    }


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
            weighted_cost = (
                (costs[symbol] * quantities[symbol]) + (price * qty)
            ) / total_qty
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
        "total_return": 0.0,
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
        equity_curve = daily_values.sort_values("trade_date")["portfolio_value"].astype(
            float
        )
        running_peak = equity_curve.cummax()
        drawdown = (
            (equity_curve - running_peak) / running_peak.replace(0, pd.NA)
        ).fillna(0.0)
        result["max_drawdown"] = float(drawdown.min())
        initial_value = float(equity_curve.iloc[0])
        if initial_value > 0:
            result["total_return"] = float(
                (equity_curve.iloc[-1] - initial_value) / initial_value
            )

    return result


def build_performance_report(
    source: PerformanceDataSource,
    session_id: str,
) -> Dict[str, Any]:
    trades = source.query_trades(session_id)
    daily_perf = source.query_daily_performance(session_id)
    snaps = source.query_position_snapshots(session_id)
    holding_returns = calculate_holding_returns(source, session_id, snaps=snaps)
    equity_curve = calculate_equity_curve(
        source,
        session_id,
        daily_perf=daily_perf,
        snaps=snaps,
    )
    trade_activity = calculate_trade_activity(
        source,
        session_id,
        trades=trades,
    )
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
    position_exposure = summarize_position_exposure(
        holding_returns,
        equity_curve=equity_curve,
    )
    latest_portfolio = summarize_latest_portfolio(equity_curve)
    return {
        "summary": summary,
        "holding_returns": holding_returns,
        "turnover": turnover,
        "equity_curve": equity_curve,
        "trade_activity": trade_activity,
        "position_exposure": position_exposure,
        "latest_portfolio": latest_portfolio,
    }
