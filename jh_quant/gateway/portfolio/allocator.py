from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .analysis import build_portfolio_drift_snapshot
from ..config import PortfolioSpec


def build_rebalance_plan(
    *,
    target_weights: pd.DataFrame,
    positions: Dict[str, Any],
    latest_prices: pd.Series,
    portfolio_spec: PortfolioSpec,
) -> Dict[str, Any]:
    if target_weights is None or target_weights.empty:
        raise ValueError("Target weights are required to build a rebalance plan")

    holds = positions.get("holds", []) or []
    current_rows = []
    total_equity = float(positions.get("total") or 0.0)
    cash_balance = float(positions.get("available_balance") or 0.0)
    lot_size = max(1, int(portfolio_spec.lot_size))
    investable_equity = total_equity * (1.0 - float(portfolio_spec.cash_reserve_ratio))

    for hold in holds:
        market_value = float(hold.get("market_value") or 0.0)
        current_rows.append(
            {
                "symbol": hold.get("symbol"),
                "current_qty": int(hold.get("volume") or 0),
                "current_market_value": market_value,
                "current_weight": (
                    (market_value / total_equity) if total_equity > 0 else 0.0
                ),
            }
        )

    current = pd.DataFrame(current_rows)
    if current.empty:
        current = pd.DataFrame(
            columns=["symbol", "current_qty", "current_market_value", "current_weight"]
        )

    target = target_weights.copy()
    target["target_weight"] = target["target_weight"].astype(float)
    if float(target["target_weight"].sum()) > 0:
        target["target_weight"] = target["target_weight"] / float(
            target["target_weight"].sum()
        )
    target["target_weight"] = target["target_weight"].clip(
        lower=float(portfolio_spec.min_weight),
        upper=float(portfolio_spec.max_weight),
    )

    prices = latest_prices.rename("latest_price").to_frame()
    merged = current.merge(
        target[["symbol", "target_weight"]], on="symbol", how="outer"
    ).merge(prices, left_on="symbol", right_index=True, how="left")
    merged["current_qty"] = (
        pd.to_numeric(merged["current_qty"], errors="coerce").fillna(0).astype(int)
    )
    merged["current_market_value"] = pd.to_numeric(
        merged["current_market_value"], errors="coerce"
    ).fillna(0.0)
    merged["current_weight"] = pd.to_numeric(
        merged["current_weight"], errors="coerce"
    ).fillna(0.0)
    merged["target_weight"] = pd.to_numeric(
        merged["target_weight"], errors="coerce"
    ).fillna(0.0)
    merged = merged.dropna(subset=["latest_price"]).copy()
    merged["target_value"] = merged["target_weight"] * investable_equity
    merged["target_qty"] = (
        (merged["target_value"] / merged["latest_price"]) // lot_size
    ) * lot_size
    merged["target_qty"] = merged["target_qty"].fillna(0).astype(int)
    merged["delta_qty"] = merged["target_qty"] - merged["current_qty"].astype(int)
    merged["delta_value"] = merged["delta_qty"] * merged["latest_price"]
    merged["abs_delta_weight"] = (
        merged["target_weight"] - merged["current_weight"]
    ).abs()

    buy_orders = merged.loc[merged["delta_qty"] > 0, ["symbol", "delta_qty"]].copy()
    buy_orders.rename(columns={"delta_qty": "target_qty"}, inplace=True)
    sell_orders = merged.loc[merged["delta_qty"] < 0, ["symbol", "delta_qty"]].copy()
    sell_orders["target_qty"] = sell_orders["delta_qty"].abs().astype(int)
    sell_orders = sell_orders[["symbol", "target_qty"]]

    projected_buy_cost = float(
        merged.loc[merged["delta_qty"] > 0, "delta_value"].clip(lower=0).sum()
    )
    projected_sell_value = float(
        (-merged.loc[merged["delta_qty"] < 0, "delta_value"]).clip(lower=0).sum()
    )
    projected_cash_after = cash_balance + projected_sell_value - projected_buy_cost

    drift = build_portfolio_drift_snapshot(
        merged[["symbol", "current_weight"]],
        target_weights=merged[["symbol", "target_weight"]],
    )

    return {
        "target_allocations": merged[
            [
                "symbol",
                "latest_price",
                "current_qty",
                "target_qty",
                "delta_qty",
                "current_weight",
                "target_weight",
                "abs_delta_weight",
                "target_value",
            ]
        ]
        .sort_values(["target_weight", "symbol"], ascending=[False, True])
        .to_dict(orient="records"),
        "buy_orders": buy_orders.to_dict(orient="records"),
        "sell_orders": sell_orders.to_dict(orient="records"),
        "projected_buy_cost": projected_buy_cost,
        "projected_sell_value": projected_sell_value,
        "projected_cash_after": projected_cash_after,
        "drift": drift,
    }
