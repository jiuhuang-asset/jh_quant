from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from ..config import PortfolioSpec, RebalanceMode, SelectionProvider, SessionConfig
from .allocator import build_rebalance_plan
from .optimizer import optimize_portfolio_preview


class PortfolioRuntimeCoordinator:
    """Session-scoped portfolio optimization and rebalance decision helper."""

    def __init__(
        self,
        *,
        gateway,
        selection_provider: SelectionProvider,
        session_config: SessionConfig,
        portfolio_spec: PortfolioSpec,
        log: Callable[[str, str], None],
        strategy_registered: Callable[[], bool],
        last_rebalance_at: Callable[[], Optional[datetime]],
    ):
        self.gateway = gateway
        self.selection_provider = selection_provider
        self.session_config = session_config
        self.portfolio_spec = portfolio_spec
        self._log = log
        self._strategy_registered = strategy_registered
        self._last_rebalance_at = last_rebalance_at

    def filter_sell_orders_by_executable_holdings(
        self,
        sell_orders: pd.DataFrame,
        latest_prices: pd.Series,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], float]:
        if sell_orders is None or sell_orders.empty:
            return pd.DataFrame(columns=["symbol", "target_qty"]), [], 0.0

        executable_map = {
            hold.symbol: int(hold.volume)
            for hold in self.gateway.broker.executable_holds
            if int(hold.volume) > 0
        }
        executable_rows: list[dict[str, int]] = []
        blocked_rows: list[dict[str, Any]] = []
        projected_sell_value = 0.0

        for _, row in sell_orders.iterrows():
            symbol = str(row["symbol"])
            requested_qty = int(row["target_qty"])
            executable_qty = int(executable_map.get(symbol, 0))
            allowed_qty = min(requested_qty, executable_qty)

            if allowed_qty <= 0:
                blocked_rows.append(
                    {
                        "symbol": symbol,
                        "requested_qty": requested_qty,
                        "executable_qty": executable_qty,
                        "reason": "not_in_executable_holds",
                    }
                )
                continue

            if allowed_qty < requested_qty:
                blocked_rows.append(
                    {
                        "symbol": symbol,
                        "requested_qty": requested_qty,
                        "executable_qty": executable_qty,
                        "reason": "capped_by_executable_holds",
                    }
                )

            executable_rows.append(
                {
                    "symbol": symbol,
                    "target_qty": allowed_qty,
                }
            )
            if symbol in latest_prices.index:
                projected_sell_value += float(latest_prices[symbol]) * float(
                    allowed_qty
                )

        filtered_orders = pd.DataFrame(
            executable_rows, columns=["symbol", "target_qty"]
        )
        return filtered_orders, blocked_rows, projected_sell_value

    def cap_buy_orders_to_cash_budget(
        self,
        buy_orders: pd.DataFrame,
        latest_prices: pd.Series,
        cash_budget: float,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], float]:
        if buy_orders is None or buy_orders.empty:
            return pd.DataFrame(columns=["symbol", "target_qty"]), [], 0.0

        lot_size = max(1, int(self.portfolio_spec.lot_size))
        remaining_cash = max(0.0, float(cash_budget))
        executable_rows: list[dict[str, int]] = []
        blocked_rows: list[dict[str, Any]] = []
        projected_buy_cost = 0.0

        for _, row in buy_orders.iterrows():
            symbol = str(row["symbol"])
            requested_qty = int(row["target_qty"])
            if requested_qty <= 0:
                continue
            if symbol not in latest_prices.index:
                blocked_rows.append(
                    {
                        "symbol": symbol,
                        "requested_qty": requested_qty,
                        "allowed_qty": 0,
                        "reason": "missing_latest_price",
                    }
                )
                continue

            latest_price = float(latest_prices[symbol])
            if latest_price <= 0:
                blocked_rows.append(
                    {
                        "symbol": symbol,
                        "requested_qty": requested_qty,
                        "allowed_qty": 0,
                        "reason": "invalid_latest_price",
                    }
                )
                continue

            requested_cost = latest_price * requested_qty
            if requested_cost <= remaining_cash + 1e-9:
                allowed_qty = requested_qty
            elif not self.portfolio_spec.allow_partial_rebalance:
                allowed_qty = 0
            else:
                affordable_lots = int(remaining_cash // (latest_price * lot_size))
                allowed_qty = min(affordable_lots * lot_size, requested_qty)

            if allowed_qty <= 0:
                blocked_rows.append(
                    {
                        "symbol": symbol,
                        "requested_qty": requested_qty,
                        "allowed_qty": 0,
                        "reason": "insufficient_cash_after_t1_filter",
                    }
                )
                continue

            if allowed_qty < requested_qty:
                blocked_rows.append(
                    {
                        "symbol": symbol,
                        "requested_qty": requested_qty,
                        "allowed_qty": allowed_qty,
                        "reason": "partially_capped_by_cash_budget",
                    }
                )

            cost = latest_price * allowed_qty
            executable_rows.append({"symbol": symbol, "target_qty": allowed_qty})
            projected_buy_cost += cost
            remaining_cash -= cost

        filtered_orders = pd.DataFrame(
            executable_rows, columns=["symbol", "target_qty"]
        )
        return filtered_orders, blocked_rows, projected_buy_cost

    def build_strategy_context(
        self,
        *,
        cycle_date: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        base_date = datetime.strptime(cycle_date, "%Y-%m-%d")
        lookback_days = max(
            self.session_config.price_lookback_days,
            self.portfolio_spec.historical_lookback_days,
        )
        price_start = (base_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        if symbols is None:
            selection = self.selection_provider.select(as_of_date=cycle_date)
            selected_symbols = list(selection.top_selections)
        else:
            selected_symbols = list(symbols)
        selected_symbols = list(
            dict.fromkeys(str(symbol) for symbol in selected_symbols if symbol)
        )
        if not selected_symbols:
            raise ValueError("No symbols available for portfolio optimization")

        price = self.gateway.get_price_data(
            symbols=selected_symbols,
            start_date=price_start,
            end_date=cycle_date,
            frequency=self.session_config.frequency,
        )
        buy_signals = self.gateway.aggregate_buy_signals(
            price=price,
            frequency=self.session_config.frequency,
        )

        signal_frame = pd.DataFrame({"symbol": selected_symbols})
        if buy_signals is not None and not buy_signals.empty:
            signal_frame = signal_frame.merge(
                buy_signals[["symbol", "score"]],
                on="symbol",
                how="left",
            ).fillna({"score": 0.0})
        else:
            signal_frame["score"] = 0.0

        signal_frame["score"] = signal_frame["score"].astype(float)
        positive_signals = signal_frame.loc[signal_frame["score"] > 0].copy()
        strategy_registered = self._strategy_registered()
        used_strategy_filter = strategy_registered and not positive_signals.empty
        fallback_reason: Optional[str] = None

        if used_strategy_filter:
            optimization_signals = positive_signals.sort_values(
                by=["score", "symbol"],
                ascending=[False, True],
            ).reset_index(drop=True)
        else:
            optimization_signals = signal_frame.copy()
            fallback_reason = (
                "no_positive_buy_scores" if strategy_registered else "no_strategy_registered"
            )

        if optimization_signals.empty:
            raise ValueError(
                "No symbols available after applying strategy-aware portfolio filters"
            )

        if float(optimization_signals["score"].clip(lower=0.0).sum()) <= 0:
            optimization_signals["score"] = 1.0

        optimization_symbols = optimization_signals["symbol"].astype(str).tolist()
        filtered_price = (
            price[price["symbol"].isin(optimization_symbols)].copy()
            if not price.empty
            else price
        )

        return {
            "cycle_date": cycle_date,
            "price_start": price_start,
            "selected_symbols": selected_symbols,
            "price": filtered_price,
            "signals": optimization_signals[["symbol", "score"]].copy(),
            "optimization_symbols": optimization_symbols,
            "strategy_registered": strategy_registered,
            "used_strategy_filter": used_strategy_filter,
            "fallback_reason": fallback_reason,
            "positive_signal_count": int(len(positive_signals)),
            "selection_count": int(len(selected_symbols)),
        }

    def optimize(
        self,
        *,
        cycle_date: str,
        symbols: Optional[List[str]] = None,
        preview_only: bool = True,
    ) -> Dict[str, Any]:
        context = self.build_strategy_context(cycle_date=cycle_date, symbols=symbols)
        optimization_symbols = context["optimization_symbols"]
        price = context["price"]
        returns = self.gateway.build_return_matrix(
            symbols=optimization_symbols,
            start_date=context["price_start"],
            end_date=cycle_date,
            frequency=self.session_config.frequency,
            price=price,
        )
        result = optimize_portfolio_preview(
            returns,
            self.portfolio_spec,
            signals=context["signals"],
        )
        diagnostics = {
            **result.diagnostics,
            "selection_count": context["selection_count"],
            "positive_signal_count": context["positive_signal_count"],
            "selected_symbols": context["selected_symbols"],
            "optimization_symbols": optimization_symbols,
            "strategy_registered": context["strategy_registered"],
            "used_strategy_filter": context["used_strategy_filter"],
            "fallback_reason": context["fallback_reason"],
        }
        payload = {
            "status": "optimized",
            "optimizer": result.optimizer,
            "as_of_date": cycle_date,
            "symbols": result.symbols,
            "weights": result.weights.to_dict(orient="records"),
            "diagnostics": diagnostics,
            "preview_only": preview_only,
        }
        if context["used_strategy_filter"]:
            self._log(
                "portfolio",
                (
                    "组合优化使用 Strategy 过滤后的目标池，"
                    f"selected={context['selection_count']}, "
                    f"positive_signals={context['positive_signal_count']}, "
                    f"optimized={len(optimization_symbols)}"
                ),
            )
        else:
            self._log(
                "portfolio",
                (
                    "组合优化未拿到可用的正向 Strategy 信号，回退到 Selection universe，"
                    f"fallback_reason={context['fallback_reason']}, "
                    f"selected={context['selection_count']}"
                ),
            )
        return payload

    def should_rebalance(
        self,
        drift: Dict[str, Any],
        *,
        force: bool = False,
        as_of_time: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        if force:
            return True, "forced"

        policy = self.portfolio_spec.rebalance_policy
        mode = policy.mode.value
        now = as_of_time or datetime.now()

        if mode == RebalanceMode.DISABLED.value:
            return False, "rebalance policy disabled"
        if mode == RebalanceMode.MANUAL_ONLY.value:
            return False, "rebalance policy is manual_only"
        if mode == RebalanceMode.EVERY_CYCLE.value:
            return True, "rebalance policy is every_cycle"
        if mode == RebalanceMode.INITIAL_ONLY.value:
            has_positions = bool(self.gateway.broker.get_positions().holds)
            return (not has_positions), (
                "initial allocation required"
                if not has_positions
                else "positions already exist"
            )
        if mode == RebalanceMode.DRIFT_THRESHOLD.value:
            threshold = policy.drift_threshold
            if threshold is None:
                return False, "drift_threshold mode requires drift_threshold"
            total_abs_drift = float(drift.get("total_abs_drift") or 0.0)
            max_abs_drift = float(drift.get("max_abs_drift") or 0.0)
            triggered = max(total_abs_drift, max_abs_drift) >= float(threshold)
            if not triggered:
                return False, f"drift below threshold {threshold}"
            last_rebalance_at = self._last_rebalance_at()
            if (
                policy.min_rebalance_interval_seconds is not None
                and last_rebalance_at is not None
            ):
                elapsed = (now - last_rebalance_at).total_seconds()
                if elapsed < policy.min_rebalance_interval_seconds:
                    return False, "minimum rebalance interval not reached"
            return (
                True,
                f"drift threshold reached ({max(total_abs_drift, max_abs_drift):.4f})",
            )
        if mode == RebalanceMode.SCHEDULE.value:
            return False, "schedule mode is not implemented yet"
        return False, f"unsupported rebalance mode: {mode}"

    def build_rebalance_preview(
        self,
        *,
        cycle_date: str,
        optimization_payload: Dict[str, Any],
        force: bool = False,
    ) -> Dict[str, Any]:
        weights = pd.DataFrame(optimization_payload["weights"])
        if weights.empty:
            raise ValueError("No optimized weights available for rebalance")

        target_symbols = list(weights["symbol"].astype(str))
        current_symbols = [hold.symbol for hold in self.gateway.broker.get_positions().holds]
        price_symbols = list(dict.fromkeys(target_symbols + current_symbols))
        latest_prices = self.gateway.get_latest_prices(price_symbols)
        positions_snapshot = self.gateway.broker.get_positions().model_dump()
        plan = build_rebalance_plan(
            target_weights=weights,
            positions=positions_snapshot,
            latest_prices=latest_prices,
            portfolio_spec=self.portfolio_spec,
        )

        planned_sell_orders = pd.DataFrame(plan["sell_orders"])
        executable_sell_orders, blocked_sell_orders, executable_sell_value = (
            self.filter_sell_orders_by_executable_holdings(
                planned_sell_orders,
                latest_prices,
            )
        )
        planned_buy_orders = pd.DataFrame(plan["buy_orders"])
        cash_budget = float(positions_snapshot.get("available_balance") or 0.0) + executable_sell_value
        executable_buy_orders, blocked_buy_orders, executable_buy_cost = (
            self.cap_buy_orders_to_cash_budget(
                planned_buy_orders,
                latest_prices,
                cash_budget,
            )
        )
        projected_cash_after = cash_budget - executable_buy_cost
        should_rebalance, reason = self.should_rebalance(
            plan["drift"],
            force=force,
            as_of_time=datetime.now(),
        )
        payload = {
            "status": "preview",
            "as_of_date": cycle_date,
            "preview_only": True,
            "should_rebalance": should_rebalance,
            "reason": reason,
            "target_allocations": plan["target_allocations"],
            "buy_orders": executable_buy_orders.to_dict(orient="records"),
            "sell_orders": executable_sell_orders.to_dict(orient="records"),
            "projected_buy_cost": executable_buy_cost,
            "projected_sell_value": executable_sell_value,
            "projected_cash_after": projected_cash_after,
            "drift": plan["drift"],
            "executed_buy_count": 0,
            "executed_sell_count": 0,
            "execution_path": "strategy_driven_portfolio_overlay",
            "blocked_sell_orders": blocked_sell_orders,
            "blocked_buy_orders": blocked_buy_orders,
        }
        self._log(
            "portfolio",
            (
                "组合调仓计划已生成，"
                f"sell_orders={len(payload['sell_orders'])}, "
                f"buy_orders={len(payload['buy_orders'])}, "
                f"blocked_sells={len(blocked_sell_orders)}, "
                f"blocked_buys={len(blocked_buy_orders)}"
            ),
        )
        if blocked_sell_orders:
            self._log(
                "portfolio",
                f"检测到 {len(blocked_sell_orders)} 笔卖单受 executable_holds / A股T+1 约束影响。",
            )
        return payload
