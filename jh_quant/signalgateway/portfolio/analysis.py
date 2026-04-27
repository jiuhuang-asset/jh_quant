from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def _normalize_timestamp(series: pd.Series) -> pd.Series:
    values = pd.to_datetime(series, errors="coerce", utc=True)
    return values.dt.tz_localize(None)


def build_portfolio_drift_snapshot(
    current_holdings: pd.DataFrame,
    *,
    target_weights: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    if current_holdings is None or current_holdings.empty:
        current = pd.DataFrame(columns=["symbol", "current_weight"])
    else:
        current = current_holdings[["symbol", "current_weight"]].copy()

    if target_weights is None or target_weights.empty:
        return {
            "total_abs_drift": 0.0,
            "max_abs_drift": 0.0,
            "rows": [],
        }

    merged = current.merge(target_weights[["symbol", "target_weight"]], on="symbol", how="outer").fillna(0.0)
    merged["abs_drift"] = (merged["current_weight"] - merged["target_weight"]).abs()
    merged = merged.sort_values("abs_drift", ascending=False)
    return {
        "total_abs_drift": float(merged["abs_drift"].sum()),
        "max_abs_drift": float(merged["abs_drift"].max()) if not merged.empty else 0.0,
        "rows": merged.to_dict(orient="records"),
    }


def build_current_portfolio_snapshot(
    positions: Dict[str, Any],
    *,
    target_weights: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    holds = positions.get("holds", []) or []
    total = float(positions.get("total") or 0.0)
    available_balance = float(positions.get("available_balance") or 0.0)
    rows = []
    for hold in holds:
        market_value = float(hold.get("market_value") or 0.0)
        rows.append(
            {
                "symbol": hold.get("symbol"),
                "quantity": int(hold.get("volume") or 0),
                "avg_cost": float(hold.get("avg_cost") or 0.0),
                "market_value": market_value,
                "current_weight": (market_value / total) if total > 0 else 0.0,
            }
        )
    current = pd.DataFrame(rows)
    drift = build_portfolio_drift_snapshot(current, target_weights=target_weights)
    return {
        "portfolio_value": total,
        "cash_balance": available_balance,
        "cash_ratio": (available_balance / total) if total > 0 else 1.0,
        "holdings": rows,
        "drift": drift,
    }


def build_portfolio_history(position_snapshots: pd.DataFrame) -> Dict[str, Any]:
    if position_snapshots is None or position_snapshots.empty:
        return {
            "weight_history": [],
            "portfolio_value_history": [],
        }

    frame = position_snapshots.copy()
    frame["trade_date"] = _normalize_timestamp(frame["trade_date"])
    frame = frame.dropna(subset=["trade_date"])
    frame["portfolio_value"] = frame.groupby("trade_date")["market_value"].transform("sum")
    frame["weight"] = frame["market_value"] / frame["portfolio_value"].replace(0, pd.NA)
    weight_history = frame[["trade_date", "symbol", "quantity", "market_value", "weight"]].copy()
    weight_history["trade_date"] = weight_history["trade_date"].apply(lambda value: value.isoformat())

    portfolio_value_history = (
        frame.groupby("trade_date", as_index=False)["portfolio_value"]
        .max()
        .sort_values("trade_date")
    )
    portfolio_value_history["trade_date"] = portfolio_value_history["trade_date"].apply(
        lambda value: value.isoformat()
    )
    return {
        "weight_history": weight_history.to_dict(orient="records"),
        "portfolio_value_history": portfolio_value_history.to_dict(orient="records"),
    }
