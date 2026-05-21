from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..performance import calculate_pnl_source_breakdown
from ..service.schemas import (
    AnalyticsSnapshotResponse,
    PerformanceHistoryResponse,
    PerformanceSnapshotResponse,
    PnlSourceHistoryResponse,
    RuntimeSnapshotResponse,
)

if TYPE_CHECKING:
    from ..service.core import SessionService


class SessionAnalyticsCoordinator:
    """Builds current-state and historical analytics payloads for a session."""

    def __init__(self, service: "SessionService"):
        self.service = service

    def build_current_position_rows(self, positions=None) -> list[dict[str, Any]]:
        positions = positions or self.service.gateway.broker.get_positions()
        holds = getattr(positions, "holds", []) or []
        items: list[dict[str, Any]] = []
        for hold in holds:
            quantity = int(getattr(hold, "volume", 0))
            sellable_volume = getattr(hold, "sellable_volume", None)
            avg_cost = float(getattr(hold, "avg_cost", 0.0))
            market_value = float(getattr(hold, "market_value", 0.0))
            cost_basis = avg_cost * quantity
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis) if cost_basis > 0 else 0.0
            current_price = (market_value / quantity) if quantity > 0 else 0.0
            entry_time = getattr(hold, "entry_time", None)
            items.append(
                {
                    "symbol": hold.symbol,
                    "quantity": quantity,
                    "sellable_volume": int(sellable_volume)
                    if sellable_volume is not None
                    else quantity,
                    "avg_cost": avg_cost,
                    "current_price": current_price,
                    "market_value": market_value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "entry_time": entry_time.isoformat() if entry_time else None,
                }
            )
        return sorted(items, key=lambda item: item["market_value"], reverse=True)

    def build_current_runtime_bundle(
        self,
        *,
        generated_at: Optional[str] = None,
        positions=None,
    ) -> Dict[str, Any]:
        positions = positions or self.service.gateway.broker.get_positions()
        generated_at = generated_at or datetime.now().isoformat()
        position_rows = self.build_current_position_rows(positions)
        position_value = float(sum(item["market_value"] for item in position_rows))
        cash_balance = float(getattr(positions, "available_balance", 0.0))
        portfolio_value = float(
            getattr(positions, "total", cash_balance + position_value)
        )
        realized_pnl = float(
            getattr(self.service.gateway.broker, "total_profit", 0.0) or 0.0
        )
        unrealized_pnl = float(sum(item["pnl"] for item in position_rows))
        return {
            "session_id": self.service.config.session_id,
            "generated_at": generated_at,
            "portfolio_value": portfolio_value,
            "cash_balance": cash_balance,
            "position_value": position_value,
            "position_count": len(position_rows),
            "daily_pnl": float(getattr(positions, "daily_profit", 0.0) or 0.0),
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": realized_pnl + unrealized_pnl,
            "positions": position_rows,
        }

    def build_current_portfolio_snapshot(
        self,
        runtime_bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        portfolio_value = float(runtime_bundle.get("portfolio_value", 0.0) or 0.0)
        cash_balance = float(runtime_bundle.get("cash_balance", 0.0) or 0.0)
        position_value = float(runtime_bundle.get("position_value", 0.0) or 0.0)
        return {
            "as_of": runtime_bundle.get("generated_at"),
            "portfolio_value": portfolio_value,
            "cash_balance": cash_balance,
            "position_value": position_value,
            "cash_ratio": (cash_balance / portfolio_value) if portfolio_value > 0 else 1.0,
            "invested_ratio": (
                (position_value / portfolio_value) if portfolio_value > 0 else 0.0
            ),
        }

    def build_current_position_exposure(
        self,
        runtime_bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        positions = runtime_bundle.get("positions", [])
        if not positions:
            return {
                "position_count": 0,
                "gross_market_value": 0.0,
                "cash_ratio": 1.0,
                "invested_ratio": 0.0,
                "max_position_weight": 0.0,
                "top3_concentration": 0.0,
                "top_positions": [],
            }

        portfolio_value = float(runtime_bundle.get("portfolio_value", 0.0) or 0.0)
        position_value = float(runtime_bundle.get("position_value", 0.0) or 0.0)
        denominator = portfolio_value if portfolio_value > 0 else position_value
        weighted_positions = []
        for item in positions:
            weight = (
                float(item["market_value"]) / denominator if denominator > 0 else 0.0
            )
            weighted_positions.append({**item, "weight": weight})

        top_positions = [
            {
                "symbol": item["symbol"],
                "market_value": float(item["market_value"]),
                "weight": float(item["weight"]),
                "pnl": float(item["pnl"]),
                "pnl_pct": float(item["pnl_pct"]),
            }
            for item in weighted_positions[:5]
        ]
        return {
            "position_count": int(runtime_bundle.get("position_count", 0)),
            "gross_market_value": position_value,
            "cash_ratio": (
                float(runtime_bundle.get("cash_balance", 0.0)) / portfolio_value
                if portfolio_value > 0
                else 1.0
            ),
            "invested_ratio": (position_value / portfolio_value)
            if portfolio_value > 0
            else 0.0,
            "max_position_weight": max(
                (item["weight"] for item in weighted_positions), default=0.0
            ),
            "top3_concentration": sum(
                item["weight"] for item in weighted_positions[:3]
            ),
            "top_positions": top_positions,
        }

    def build_current_performance_summary(
        self,
        *,
        report: Optional[Dict[str, Any]] = None,
        runtime_bundle: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        report = report or self.service.persistence.get_performance_report(
            self.service.config.session_id
        )
        summary = dict(report.get("summary", {}))
        runtime_bundle = runtime_bundle or self.build_current_runtime_bundle()
        initial_capital = float(
            summary.get("initial_capital")
            or getattr(self.service.gateway.broker, "initial_capital", 0.0)
            or 0.0
        )
        portfolio_value = float(runtime_bundle["portfolio_value"])
        cash_balance = float(runtime_bundle["cash_balance"])
        position_value = float(runtime_bundle["position_value"])
        summary.setdefault("total_trades", 0)
        summary.setdefault("buy_count", 0)
        summary.setdefault("sell_count", 0)
        summary.setdefault("win_count", 0)
        summary.setdefault("loss_count", 0)
        summary.setdefault("win_rate", None)
        summary.setdefault("avg_win", None)
        summary.setdefault("avg_loss", None)
        summary.setdefault("max_drawdown", 0.0)
        summary.update(
            {
                "initial_capital": initial_capital,
                "portfolio_value": portfolio_value,
                "cash_balance": cash_balance,
                "position_value": position_value,
                "daily_pnl": float(runtime_bundle["daily_pnl"]),
                "realized_pnl": float(runtime_bundle["realized_pnl"]),
                "unrealized_pnl": float(runtime_bundle["unrealized_pnl"]),
                "total_pnl": float(runtime_bundle["total_pnl"]),
                "cash_ratio": (cash_balance / portfolio_value)
                if portfolio_value > 0
                else 1.0,
                "invested_ratio": (
                    (position_value / portfolio_value) if portfolio_value > 0 else 0.0
                ),
                "total_return": (
                    (portfolio_value - initial_capital) / initial_capital
                    if initial_capital > 0
                    else 0.0
                ),
            }
        )
        return summary

    def get_runtime_state(self) -> Dict[str, Any]:
        return RuntimeSnapshotResponse(
            **self.build_current_runtime_bundle()
        ).model_dump()

    def get_positions(self) -> Dict[str, Any]:
        generated_at = datetime.now().isoformat()
        runtime_bundle = self.build_current_runtime_bundle(generated_at=generated_at)
        return {
            "session_id": self.service.config.session_id,
            "generated_at": generated_at,
            "portfolio_value": runtime_bundle["portfolio_value"],
            "cash_balance": runtime_bundle["cash_balance"],
            "position_value": runtime_bundle["position_value"],
            "realized_pnl": runtime_bundle["realized_pnl"],
            "unrealized_pnl": runtime_bundle["unrealized_pnl"],
            "total_pnl": runtime_bundle["total_pnl"],
            "num_positions": runtime_bundle["position_count"],
            "positions": runtime_bundle["positions"],
        }

    def get_position_history(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        df = self.service.persistence.query_position_snapshots(
            self.service.config.session_id
        )
        if df is None or df.empty:
            return {
                "session_id": self.service.config.session_id,
                "symbol": symbol,
                "count": 0,
                "snapshots": [],
            }
        if symbol:
            df = df[df["symbol"] == symbol]
        records = self.service._records_from_frame(df)
        return {
            "session_id": self.service.config.session_id,
            "symbol": symbol,
            "count": len(records),
            "snapshots": records,
        }

    def get_performance_snapshot(self) -> Dict[str, Any]:
        report = self.service.persistence.get_performance_report(
            self.service.config.session_id
        )
        runtime_bundle = self.build_current_runtime_bundle()
        return PerformanceSnapshotResponse(
            session_id=self.service.config.session_id,
            generated_at=datetime.now().isoformat(),
            summary=self.service._normalize_jsonable(
                self.build_current_performance_summary(
                    report=report,
                    runtime_bundle=runtime_bundle,
                )
            ),
        ).model_dump()

    def get_performance_history(self) -> Dict[str, Any]:
        report = self.service.persistence.get_performance_report(
            self.service.config.session_id
        )
        daily_performance = self.service.persistence.query_daily_performance(
            self.service.config.session_id
        )
        return PerformanceHistoryResponse(
            session_id=self.service.config.session_id,
            generated_at=datetime.now().isoformat(),
            daily_performance=self.service._records_from_frame(daily_performance),
            equity_curve=self.service._records_from_frame(report["equity_curve"]),
            turnover=self.service._records_from_frame(report["turnover"]),
            trade_activity=self.service._records_from_frame(report["trade_activity"]),
        ).model_dump()

    def get_pnl_source_history(self) -> Dict[str, Any]:
        trades = self.service.persistence.query_trades(self.service.config.session_id)
        breakdown = calculate_pnl_source_breakdown(
            self.service.persistence,
            self.service.config.session_id,
            trades=trades,
        )
        return PnlSourceHistoryResponse(
            session_id=self.service.config.session_id,
            generated_at=datetime.now().isoformat(),
            total_realized_pnl=float(breakdown["total_realized_pnl"]),
            total_profit=float(breakdown["total_profit"]),
            total_loss=float(breakdown["total_loss"]),
            profit_sources=self.service._records_from_frame(
                breakdown["profit_sources"]
            ),
            loss_sources=self.service._records_from_frame(
                breakdown["loss_sources"]
            ),
        ).model_dump()

    def get_analysis_snapshot(self) -> Dict[str, Any]:
        report = self.service.persistence.get_performance_report(
            self.service.config.session_id
        )
        runtime_bundle = self.build_current_runtime_bundle()
        trade_activity = self.service._records_from_frame(report["trade_activity"])
        turnover = self.service._records_from_frame(report["turnover"])
        return AnalyticsSnapshotResponse(
            session_id=self.service.config.session_id,
            generated_at=datetime.now().isoformat(),
            latest_portfolio=self.service._normalize_jsonable(
                self.build_current_portfolio_snapshot(runtime_bundle)
            ),
            position_exposure=self.service._normalize_jsonable(
                self.build_current_position_exposure(runtime_bundle)
            ),
            latest_trade_activity=(trade_activity[-1] if trade_activity else None),
            latest_turnover=(turnover[-1] if turnover else None),
        ).model_dump()
