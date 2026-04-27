from __future__ import annotations

import traceback
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from threading import Event, RLock, Thread
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import (
    PortfolioSpec,
    SELECTION_PROVIDER_REGISTRY,
    STRATEGY_REGISTRY,
    SelectionProvider,
    SelectionSpec,
    SignalGatewayServiceConfig,
    StrategySpec,
    build_selection_provider,
    list_selection_definitions,
    list_strategy_definitions,
    normalize_strategy_spec,
)
from ..models import Order
from ..persistence import PersistenceCoordinator
from ..portfolio import (
    build_rebalance_plan,
    build_current_portfolio_snapshot,
    build_portfolio_history,
    list_portfolio_optimizer_definitions,
    optimize_portfolio_preview,
)
from ..signalgateway import SignalGateway
from .schemas import (
    AnalyticsSnapshotResponse,
    CloseAllPositionsResponse,
    PerformanceSnapshotResponse,
    RuntimeSnapshotResponse,
    SchedulerConfigSnapshotResponse,
    SchedulerConfigUpdateResponse,
    SchedulerStatus,
    ServiceConfigResponse,
    ServiceConfigUpdateResponse,
    ServiceEventHistoryResponse,
    ServiceStatusResponse,
    SingleSymbolTradeResponse,
    TradingCycleResult,
    TradingCycleResultResponse,
)


class CronScheduler:
    """Simple cron-based scheduler backed by croniter."""

    def __init__(self, cron_expression: str, timezone: str = "Asia/Shanghai"):
        from croniter import croniter

        self.cron_expr = cron_expression
        self.timezone = timezone
        self._tzinfo = ZoneInfo(timezone)
        self._iter = croniter(cron_expression, datetime.now(self._tzinfo))

    def get_next_timeout(self) -> float:
        next_tick = self._iter.get_next(datetime)
        return max(0.0, (next_tick - datetime.now(self._tzinfo)).total_seconds())

    def peek_next_ticks(self, count: int = 3) -> List[datetime]:
        from croniter import croniter

        preview_iter = croniter(self.cron_expr, datetime.now(self._tzinfo))
        return [preview_iter.get_next(datetime) for _ in range(max(0, count))]

    def wait(self, stop_event: Event) -> bool:
        timeout = self.get_next_timeout()
        return not stop_event.wait(timeout=timeout)


class SignalGatewayService:
    def __init__(
        self,
        gateway: SignalGateway,
        config: SignalGatewayServiceConfig,
        selection_provider: Optional[SelectionProvider] = None,
        llm_handler: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        persistence: Optional[PersistenceCoordinator] = None,
    ):
        self.gateway = gateway
        self.service_config = config
        self.config = config.service
        self.selection_specs = config.selection_spec
        self.strategy_specs = list(config.strategy_specs)
        self.portfolio_spec = config.portfolio_spec
        self.llm_handler = llm_handler
        self.persistence = persistence or PersistenceCoordinator()
        self._latest_portfolio_optimization: Optional[Dict[str, Any]] = None
        self._latest_portfolio_rebalance: Optional[Dict[str, Any]] = None
        self._last_portfolio_rebalance_at: Optional[datetime] = None
        self.selection_provider: Optional[SelectionProvider] = None

        oms_session_id = getattr(self.gateway.oms, "session_id", None)
        if self.config.session_id is None:
            self.config.session_id = oms_session_id or str(uuid.uuid4())
        elif not oms_session_id:
            self.gateway.oms.session_id = self.config.session_id

        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._running = False
        self._last_result: Optional[TradingCycleResult] = None
        self._last_error: Optional[str] = None

        self._restore_service_state()
        self._initialize_selection_provider(selection_provider)
        self._restore_oms_state()
        if self.strategy_specs:
            self.configure_strategies(self.strategy_specs)

        if self.config.auto_start:
            self.start()

    def _restore_oms_state(self):
        try:
            saved = self.persistence.load_latest_session_state(self.config.session_id)
            if saved:
                self.gateway.oms.import_state(saved)
        except Exception:
            pass

    def _restore_service_state(self) -> None:
        if not self.config.restore_persisted_state:
            return

        try:
            saved = self.persistence.load_latest_service_state(self.config.session_id)
            if not saved:
                return
            self._apply_service_state(saved)
        except Exception:
            pass

    def _apply_service_state(self, state: Dict[str, Any]) -> None:
        service_state = state.get("service") or {}
        config_bundle = service_state.get("config_bundle")
        if config_bundle:
            restored_bundle = SignalGatewayServiceConfig.model_validate(config_bundle)
            restored_session_id = self.config.session_id
            restored_restore_flag = self.config.restore_persisted_state
            self.service_config = restored_bundle
            self.config = self.service_config.service
            self.config.session_id = restored_session_id
            self.config.restore_persisted_state = restored_restore_flag
            self.service_config.service = self.config
            self.selection_specs = self.service_config.selection_spec
            self.strategy_specs = list(self.service_config.strategy_specs)
            self.portfolio_spec = self.service_config.portfolio_spec

        last_result = service_state.get("last_result")
        if last_result:
            self._last_result = TradingCycleResult(**last_result)
        self._last_error = None
        self._latest_portfolio_optimization = service_state.get("latest_portfolio_optimization")
        self._latest_portfolio_rebalance = service_state.get("latest_portfolio_rebalance")

        last_rebalance_at = service_state.get("last_portfolio_rebalance_at")
        if last_rebalance_at:
            self._last_portfolio_rebalance_at = datetime.fromisoformat(last_rebalance_at)

    def _initialize_selection_provider(
        self,
        selection_provider: Optional[SelectionProvider],
    ) -> None:
        if self.selection_specs is not None:
            self.selection_specs, self.selection_provider = build_selection_provider(
                self.selection_specs,
                getattr(self.gateway, "market_data_provider", None),
            )
            self.service_config.selection_spec = self.selection_specs
            return
        if selection_provider is not None:
            self.selection_provider = selection_provider
            self.selection_specs = None
            return
        raise ValueError("Either selection_provider or selection_spec must be provided")

    def _build_strategy_instance(self, spec: StrategySpec) -> dict:
        normalized_spec = normalize_strategy_spec(spec)
        strategy_cls = STRATEGY_REGISTRY[normalized_spec.name]
        strategy = strategy_cls(**normalized_spec.params)
        return {
            "name": normalized_spec.alias or normalized_spec.name,
            "strategy": strategy,
            "weight": normalized_spec.weight,
        }

    def configure_strategies(self, strategy_specs: List[StrategySpec]):
        with self._lock:
            normalized_specs = [normalize_strategy_spec(spec) for spec in strategy_specs]
            built = [self._build_strategy_instance(spec) for spec in normalized_specs]
            self.gateway.replace_strategies(built)
            self.strategy_specs = normalized_specs
            self.service_config.strategy_specs = list(normalized_specs)
            self._persist_runtime_state(extra={"event": "strategy_config_updated"})

    def _build_selection_instance(self, spec: SelectionSpec) -> SelectionProvider:
        normalized_spec, provider = build_selection_provider(
            spec,
            getattr(self.gateway, "market_data_provider", None),
        )
        self.selection_specs = normalized_spec
        return provider

    def configure_selection(self, selection_spec: SelectionSpec):
        with self._lock:
            provider = self._build_selection_instance(selection_spec)
            self.selection_provider = provider
            self.service_config.selection_spec = self.selection_specs
            self._persist_runtime_state(extra={"event": "selection_config_updated"})

    def configure_portfolio(self, portfolio_spec):
        with self._lock:
            self.portfolio_spec = portfolio_spec
            self.service_config.portfolio_spec = portfolio_spec
            self._persist_runtime_state(extra={"event": "portfolio_config_updated"})

    def _validate_scheduler_inputs(
        self,
        *,
        interval_seconds: Optional[int] = None,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
    ) -> None:
        if interval_seconds is not None and interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive integer")

        if timezone is not None:
            ZoneInfo(timezone)

        if cron_expression:
            from croniter import croniter

            tzinfo = ZoneInfo(timezone or self.config.timezone)
            croniter(cron_expression, datetime.now(tzinfo))

    def _build_scheduler_status(self) -> SchedulerStatus:
        schedule_type = "cron" if self.config.cron_expression else "interval"
        next_run_at: Optional[str] = None
        next_run_in_seconds: Optional[float] = None
        next_runs: List[str] = []

        if self.config.cron_expression:
            try:
                scheduler = CronScheduler(
                    cron_expression=self.config.cron_expression,
                    timezone=self.config.timezone,
                )
                next_ticks = scheduler.peek_next_ticks(count=3)
                next_tick = next_ticks[0] if next_ticks else None
                next_runs = [tick.isoformat() for tick in next_ticks]
                if next_tick is None:
                    raise ValueError("cron preview returned no next tick")
                next_run_at = next_tick.isoformat()
                next_run_in_seconds = round(
                    max(
                        0.0,
                        (next_tick - datetime.now(ZoneInfo(self.config.timezone))).total_seconds(),
                    ),
                    2,
                )
            except Exception:
                next_run_at = None
                next_run_in_seconds = None
                next_runs = []
        elif self._last_result and self._running:
            try:
                base_time = datetime.fromisoformat(self._last_result.cycle_time)
                next_tick = base_time + timedelta(seconds=self.config.interval_seconds)
                next_run_at = next_tick.isoformat()
                next_run_in_seconds = round(
                    max(0.0, (next_tick - datetime.now()).total_seconds()),
                    2,
                )
                next_runs = [
                    (next_tick + timedelta(seconds=self.config.interval_seconds * offset)).isoformat()
                    for offset in range(3)
                ]
            except Exception:
                next_run_at = None
                next_run_in_seconds = None
                next_runs = []

        return SchedulerStatus(
            interval_seconds=self.config.interval_seconds,
            cron_expression=self.config.cron_expression,
            timezone=self.config.timezone,
            schedule_type=schedule_type,
            next_run_at=next_run_at,
            next_run_in_seconds=next_run_in_seconds,
            next_runs=next_runs,
        )

    def update_scheduler_config(
        self,
        *,
        interval_seconds: Optional[int] = None,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
        auto_start: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._validate_scheduler_inputs(
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            timezone=timezone,
        )

        was_running = self._running
        if was_running:
            self.stop()

        with self._lock:
            if interval_seconds is not None:
                self.config.interval_seconds = interval_seconds
            self.config.cron_expression = cron_expression
            if timezone is not None:
                self.config.timezone = timezone
            if auto_start is not None:
                self.config.auto_start = auto_start

            self._persist_runtime_state(
                extra={
                    "event": "scheduler_config_updated",
                    "scheduler": {
                        "interval_seconds": self.config.interval_seconds,
                        "cron_expression": self.config.cron_expression,
                        "timezone": self.config.timezone,
                        "auto_start": self.config.auto_start,
                    },
                }
            )

        if was_running:
            self.start()

        return SchedulerConfigUpdateResponse(
            status="updated",
            running=self._running,
            scheduler=self._build_scheduler_status(),
            auto_start=self.config.auto_start,
        ).model_dump()

    def replace_service_config(self, config_bundle: SignalGatewayServiceConfig) -> Dict[str, Any]:
        was_running = self._running
        if was_running:
            self.stop()

        with self._lock:
            restored_session_id = self.config.session_id
            self.service_config = config_bundle.model_copy(deep=True)
            self.config = self.service_config.service
            self.config.session_id = restored_session_id or self.config.session_id
            self.service_config.service = self.config
            self.selection_specs = self.service_config.selection_spec
            self.strategy_specs = list(self.service_config.strategy_specs)
            self.portfolio_spec = self.service_config.portfolio_spec
            self._initialize_selection_provider(None)
            if self.strategy_specs:
                normalized_specs = [normalize_strategy_spec(spec) for spec in self.strategy_specs]
                built = [self._build_strategy_instance(spec) for spec in normalized_specs]
                self.gateway.replace_strategies(built)
                self.strategy_specs = normalized_specs
                self.service_config.strategy_specs = list(normalized_specs)
            else:
                self.gateway.replace_strategies([])

            self._persist_runtime_state(extra={"event": "service_config_replaced"})

        if was_running or self.config.auto_start:
            self.start()

        return ServiceConfigUpdateResponse(
            status="updated",
            session_id=self.config.session_id,
            config_bundle=self.service_config,
        ).model_dump()

    def get_scheduler_config_snapshot(self) -> Dict[str, Any]:
        return SchedulerConfigSnapshotResponse(
            running=self._running,
            auto_start=self.config.auto_start,
            scheduler=self._build_scheduler_status(),
        ).model_dump()

    def _as_of_date(self, as_of_date: Optional[str] = None) -> str:
        return as_of_date or datetime.now().strftime("%Y-%m-%d")

    def _price_start_date(self, as_of_date: str) -> str:
        dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        return (dt - timedelta(days=self.config.price_lookback_days)).strftime("%Y-%m-%d")

    def _records_from_frame(self, frame: pd.DataFrame) -> List[Dict[str, Any]]:
        if frame is None or frame.empty:
            return []

        normalized = frame.copy()
        for column in normalized.columns:
            if pd.api.types.is_datetime64_any_dtype(normalized[column]):
                normalized[column] = normalized[column].apply(
                    lambda value: value.isoformat() if pd.notna(value) else None
                )
        return normalized.to_dict(orient="records")

    def _normalize_jsonable(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._normalize_jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_jsonable(item) for item in value]
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _apply_slippage(self, price: float, trade_type: str) -> float:
        if self.config.price_slippage <= 0:
            return price
        if trade_type == "BUY":
            return price * (1 + self.config.price_slippage)
        return price * (1 - self.config.price_slippage)

    def _persist_runtime_state(self, extra: Optional[Dict[str, Any]] = None):
        payload = {
            "session_id": self.config.session_id,
            "export_time": datetime.now().isoformat(),
            "service": {
                "config_bundle": self.service_config.model_dump(mode="json"),
                "config": self.config.model_dump(),
                "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
                "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
                "running": self._running,
                "last_error": self._last_error,
                "last_result": asdict(self._last_result) if self._last_result else None,
                "latest_portfolio_optimization": self._latest_portfolio_optimization,
                "latest_portfolio_rebalance": self._latest_portfolio_rebalance,
                "last_portfolio_rebalance_at": (
                    self._last_portfolio_rebalance_at.isoformat()
                    if self._last_portfolio_rebalance_at is not None
                    else None
                ),
            },
        }
        if extra:
            payload["service"]["extra"] = extra
        self.persistence.save_service_state(payload)
        if hasattr(self.gateway.oms, "export_state"):
            self.persistence.save_session_state(self.gateway.oms.export_state())

    def _persist_trades(self, trades: List[Any]) -> None:
        for trade in trades:
            self.persistence.persist_trade(trade)

    def _serialize_result(
        self, result: Optional[TradingCycleResult]
    ) -> Optional[TradingCycleResultResponse]:
        if result is None:
            return None
        return TradingCycleResultResponse(**asdict(result))

    def get_config_snapshot(self) -> Dict[str, Any]:
        return ServiceConfigResponse(
            session_id=self.config.session_id,
            config_bundle=self.service_config.model_dump(mode="json"),
            service=self.config.model_dump(),
            selection_spec=(
                self.selection_specs.model_dump() if self.selection_specs is not None else None
            ),
            selection_provider=self._normalize_jsonable(getattr(self.selection_provider, "config", {})),
            strategy_specs=[spec.model_dump() for spec in self.strategy_specs],
            portfolio_spec=self.portfolio_spec.model_dump(mode="json"),
        ).model_dump()

    def get_strategy_config_snapshot(self) -> Dict[str, Any]:
        return {
            "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
            "available_strategies": list_strategy_definitions(),
        }

    def get_selection_config_snapshot(self) -> Dict[str, Any]:
        return {
            "selection_spec": self.selection_specs.model_dump() if self.selection_specs is not None else None,
            "active_selection_config": self._normalize_jsonable(getattr(self.selection_provider, "config", {})),
            "available_selections": list_selection_definitions(),
        }

    def get_portfolio_config_snapshot(self) -> Dict[str, Any]:
        return {
            "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
            "available_optimizers": list_portfolio_optimizer_definitions(),
        }

    def optimize_portfolio(
        self,
        *,
        as_of_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        preview_only: bool = True,
    ) -> Dict[str, Any]:
        if not self.portfolio_spec.enabled:
            raise ValueError("Portfolio optimization is disabled in the current portfolio spec")

        cycle_date = self._as_of_date(as_of_date)
        base_date = datetime.strptime(cycle_date, "%Y-%m-%d")
        lookback_days = max(self.config.price_lookback_days, self.portfolio_spec.historical_lookback_days)
        price_start = (base_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        if symbols is None:
            selection = self.selection_provider.select(as_of_date=cycle_date)
            symbols = list(selection.top_selections)
        if not symbols:
            raise ValueError("No symbols available for portfolio optimization")

        price = self.gateway.get_price_data(
            symbols=symbols,
            start_date=price_start,
            end_date=cycle_date,
            frequency=self.config.frequency,
        )
        returns = self.gateway.build_return_matrix(
            symbols=symbols,
            start_date=price_start,
            end_date=cycle_date,
            frequency=self.config.frequency,
            price=price,
        )
        signals = self.gateway.aggregate_buy_signals(
            price=price,
            frequency=self.config.frequency,
        )
        if signals.empty:
            signals = pd.DataFrame({"symbol": symbols, "score": [1.0] * len(symbols)})
        else:
            signals = (
                pd.DataFrame({"symbol": symbols})
                .merge(signals[["symbol", "score"]], on="symbol", how="left")
                .fillna({"score": 0.0})
            )
        result = optimize_portfolio_preview(
            returns,
            self.portfolio_spec,
            signals=signals,
        )
        payload = {
            "status": "optimized",
            "optimizer": result.optimizer,
            "as_of_date": cycle_date,
            "symbols": result.symbols,
            "weights": result.weights.to_dict(orient="records"),
            "diagnostics": result.diagnostics,
            "preview_only": preview_only,
        }
        self._latest_portfolio_optimization = payload
        self._persist_runtime_state(extra={"event": "portfolio_optimized"})
        return payload

    def should_rebalance_portfolio(
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

        if mode == "disabled":
            return False, "rebalance policy disabled"
        if mode == "manual_only":
            return False, "rebalance policy is manual_only"
        if mode == "every_cycle":
            return True, "rebalance policy is every_cycle"
        if mode == "initial_only":
            has_positions = bool(self.gateway.oms.get_positions().holds)
            return (not has_positions), ("initial allocation required" if not has_positions else "positions already exist")
        if mode == "drift_threshold":
            threshold = policy.drift_threshold
            if threshold is None:
                return False, "drift_threshold mode requires drift_threshold"
            total_abs_drift = float(drift.get("total_abs_drift") or 0.0)
            max_abs_drift = float(drift.get("max_abs_drift") or 0.0)
            triggered = max(total_abs_drift, max_abs_drift) >= float(threshold)
            if not triggered:
                return False, f"drift below threshold {threshold}"
            if (
                policy.min_rebalance_interval_seconds is not None
                and self._last_portfolio_rebalance_at is not None
            ):
                elapsed = (now - self._last_portfolio_rebalance_at).total_seconds()
                if elapsed < policy.min_rebalance_interval_seconds:
                    return False, "minimum rebalance interval not reached"
            return True, f"drift threshold reached ({max(total_abs_drift, max_abs_drift):.4f})"
        if mode == "schedule":
            return False, "schedule mode is not implemented yet"
        return False, f"unsupported rebalance mode: {mode}"

    def rebalance_portfolio(
        self,
        *,
        as_of_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        preview_only: bool = True,
        force: bool = False,
    ) -> Dict[str, Any]:
        if not self.portfolio_spec.enabled:
            raise ValueError("Portfolio rebalance is disabled in the current portfolio spec")

        with self._lock:
            cycle_date = self._as_of_date(as_of_date)
            optimization = self.optimize_portfolio(
                as_of_date=cycle_date,
                symbols=symbols,
                preview_only=True,
            )
            weights = pd.DataFrame(optimization["weights"])
            if weights.empty:
                raise ValueError("No optimized weights available for rebalance")

            target_symbols = list(weights["symbol"].astype(str))
            current_symbols = [hold.symbol for hold in self.gateway.oms.get_positions().holds]
            price_symbols = list(dict.fromkeys(target_symbols + current_symbols))
            latest_prices = self.gateway.get_latest_prices(price_symbols)
            positions_snapshot = self.gateway.oms.get_positions().model_dump()
            plan = build_rebalance_plan(
                target_weights=weights,
                positions=positions_snapshot,
                latest_prices=latest_prices,
                portfolio_spec=self.portfolio_spec,
            )
            should_rebalance, reason = self.should_rebalance_portfolio(
                plan["drift"],
                force=force,
                as_of_time=datetime.now(),
            )
            payload = {
                "status": "preview" if preview_only else "pending",
                "as_of_date": cycle_date,
                "preview_only": preview_only,
                "should_rebalance": should_rebalance,
                "reason": reason,
                "target_allocations": plan["target_allocations"],
                "buy_orders": plan["buy_orders"],
                "sell_orders": plan["sell_orders"],
                "projected_buy_cost": plan["projected_buy_cost"],
                "projected_sell_value": plan["projected_sell_value"],
                "projected_cash_after": plan["projected_cash_after"],
                "drift": plan["drift"],
                "executed_buy_count": 0,
                "executed_sell_count": 0,
            }

            if preview_only or not should_rebalance:
                self._latest_portfolio_rebalance = payload
                self._persist_runtime_state(extra={"event": "portfolio_rebalance_preview"})
                return payload

            sell_orders = pd.DataFrame(plan["sell_orders"])
            buy_orders = pd.DataFrame(plan["buy_orders"])
            executed_sells = self.gateway.execute_short(sell_orders, self.config.price_slippage) if not sell_orders.empty else []
            executed_buys = self.gateway.execute_long(buy_orders, self.config.price_slippage) if not buy_orders.empty else []
            self._persist_trades(executed_sells)
            self._persist_trades(executed_buys)

            payload["status"] = "rebalanced"
            payload["preview_only"] = False
            payload["executed_buy_count"] = len(executed_buys)
            payload["executed_sell_count"] = len(executed_sells)
            self._latest_portfolio_rebalance = payload
            self._last_portfolio_rebalance_at = datetime.now()
            self._persist_runtime_state(extra={"event": "portfolio_rebalanced"})
            return payload

    def get_portfolio_analysis_snapshot(self) -> Dict[str, Any]:
        runtime = self.get_runtime_state()
        target_weights = None
        if self._latest_portfolio_optimization and self._latest_portfolio_optimization.get("weights"):
            target_weights = pd.DataFrame(self._latest_portfolio_optimization["weights"])
        current = build_current_portfolio_snapshot(
            runtime["positions"],
            target_weights=target_weights,
        )
        return {
            "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
            "current_portfolio": current,
            "drift": current.get("drift", {}),
            "latest_optimization": self._latest_portfolio_optimization,
            "latest_rebalance": self._latest_portfolio_rebalance,
        }

    def get_portfolio_history(self) -> Dict[str, Any]:
        snapshots = self.persistence.query_position_snapshots(self.config.session_id)
        return build_portfolio_history(snapshots)

    def get_service_event_history(self) -> Dict[str, Any]:
        records = self.persistence.query_service_events(self.config.session_id)
        events = self._records_from_frame(records)
        return ServiceEventHistoryResponse(
            session_id=self.config.session_id,
            count=len(events),
            events=events,
        ).model_dump()

    def _empty_portfolio_cycle_payload(self, cycle_date: str, reason: str) -> Dict[str, Any]:
        payload = {
            "status": "skipped",
            "as_of_date": cycle_date,
            "preview_only": False,
            "should_rebalance": False,
            "reason": reason,
            "target_allocations": [],
            "buy_orders": [],
            "sell_orders": [],
            "projected_buy_cost": 0.0,
            "projected_sell_value": 0.0,
            "projected_cash_after": float(self.gateway.oms.get_positions().available_balance),
            "drift": {"total_abs_drift": 0.0, "max_abs_drift": 0.0, "rows": []},
            "executed_buy_count": 0,
            "executed_sell_count": 0,
        }
        self._latest_portfolio_rebalance = payload
        return payload

    def get_status(self) -> Dict[str, Any]:
        return ServiceStatusResponse(
            session_id=self.config.session_id,
            mode=self.config.mode,
            running=self._running,
            scheduler=self._build_scheduler_status(),
            last_error=self._last_error,
            last_result=self._serialize_result(self._last_result),
        ).model_dump()

    def get_runtime_state(self) -> Dict[str, Any]:
        positions = self.gateway.oms.get_positions()
        return RuntimeSnapshotResponse(
            session_id=self.config.session_id,
            generated_at=datetime.now().isoformat(),
            positions=self._normalize_jsonable(positions.model_dump()),
            oms_state=(
                self._normalize_jsonable(self.gateway.oms.export_state())
                if hasattr(self.gateway.oms, "export_state")
                else None
            ),
        ).model_dump()

    def get_performance_snapshot(self) -> Dict[str, Any]:
        report = self.persistence.get_performance_report(self.config.session_id)
        return PerformanceSnapshotResponse(
            session_id=self.config.session_id,
            generated_at=datetime.now().isoformat(),
            summary=self._normalize_jsonable(report["summary"]),
            holding_returns=self._records_from_frame(report["holding_returns"]),
            turnover=self._records_from_frame(report["turnover"]),
            equity_curve=self._records_from_frame(report["equity_curve"]),
            trade_activity=self._records_from_frame(report["trade_activity"]),
            position_exposure=self._normalize_jsonable(report["position_exposure"]),
            latest_portfolio=self._normalize_jsonable(report["latest_portfolio"]),
        ).model_dump()

    def get_analysis_snapshot(self) -> Dict[str, Any]:
        return AnalyticsSnapshotResponse(
            session_id=self.config.session_id,
            generated_at=datetime.now().isoformat(),
            status=ServiceStatusResponse.model_validate(self.get_status()),
            runtime=RuntimeSnapshotResponse.model_validate(self.get_runtime_state()),
            performance=PerformanceSnapshotResponse.model_validate(self.get_performance_snapshot()),
            config=ServiceConfigResponse.model_validate(self.get_config_snapshot()),
        ).model_dump()

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        return self.get_runtime_state()

    def run_once(self, as_of_date: Optional[str] = None) -> TradingCycleResult:
        with self._lock:
            cycle_date = self._as_of_date(as_of_date)
            price_start = self._price_start_date(cycle_date)
            selection = self.selection_provider.select(as_of_date=cycle_date)
            top_selections = selection.top_selections

            if hasattr(selection, "metadata") and selection.metadata:
                selection_meta = selection.metadata
            else:
                selection_meta = {"as_of_date": cycle_date}
                known = {"top_selections", "bottom_selections", "metadata"}
                for key in dir(selection):
                    if not key.startswith("_") and key not in known:
                        value = getattr(selection, key, None)
                        if not callable(value):
                            selection_meta[key] = value

            executed_buy_count = 0
            executed_sell_count = 0
            long_candidates = pd.DataFrame()
            short_candidates = pd.DataFrame()
            portfolio_cycle_payload: Optional[Dict[str, Any]] = None

            if self.portfolio_spec.enabled:
                if top_selections:
                    portfolio_cycle_payload = self.rebalance_portfolio(
                        as_of_date=cycle_date,
                        symbols=top_selections,
                        preview_only=False,
                        force=False,
                    )
                else:
                    portfolio_cycle_payload = self._empty_portfolio_cycle_payload(
                        cycle_date,
                        "no selected symbols for portfolio rebalance",
                    )

                long_candidates = pd.DataFrame(portfolio_cycle_payload.get("buy_orders", []))
                short_candidates = pd.DataFrame(portfolio_cycle_payload.get("sell_orders", []))
                executed_buy_count = int(portfolio_cycle_payload.get("executed_buy_count", 0))
                executed_sell_count = int(portfolio_cycle_payload.get("executed_sell_count", 0))
            else:
                executed_buys, executed_sells, long_candidates, short_candidates = self.gateway.execute_cycle(
                    top_selections=top_selections,
                    price_start=price_start,
                    cycle_date=cycle_date,
                    frequency=self.config.frequency,
                    max_candidates=self.config.max_candidates,
                    price_slippage=self.config.price_slippage,
                )

                self._persist_trades(executed_sells)
                self._persist_trades(executed_buys)
                executed_buy_count = len(executed_buys)
                executed_sell_count = len(executed_sells)

            if hasattr(self.gateway.oms, "compute_daily_metrics"):
                cycle_dt = datetime.strptime(cycle_date, "%Y-%m-%d")
                latest_prices = (
                    self.gateway.get_latest_prices(top_selections)
                    if hasattr(self.gateway, "get_latest_prices")
                    else pd.Series(dtype=float)
                )
                close_prices = latest_prices.to_dict() if not latest_prices.empty else None
                perf, snapshots = self.gateway.oms.compute_daily_metrics(
                    trade_date=cycle_dt,
                    close_prices=close_prices,
                )
                self.persistence.persist_daily_metrics(perf, snapshots)

            result = TradingCycleResult(
                session_id=self.config.session_id,
                mode=self.config.mode,
                cycle_time=datetime.now().isoformat(),
                selection_count=len(top_selections),
                long_candidate_count=len(long_candidates),
                short_candidate_count=len(short_candidates),
                executed_buy_count=executed_buy_count,
                executed_sell_count=executed_sell_count,
                selected_symbols=top_selections,
                long_symbols=[] if long_candidates.empty or "symbol" not in long_candidates.columns else long_candidates["symbol"].tolist(),
                short_symbols=[] if short_candidates.empty or "symbol" not in short_candidates.columns else short_candidates["symbol"].tolist(),
            )
            self._last_result = result
            self._last_error = None
            extra = {"selection_metadata": selection_meta}
            if portfolio_cycle_payload is not None:
                extra["portfolio_rebalance"] = portfolio_cycle_payload
            self._persist_runtime_state(extra=extra)
            return result

    def _run_scheduler(self):
        use_cron = bool(self.config.cron_expression)
        scheduler: Optional[CronScheduler] = None
        first_iteration = True
        if use_cron:
            scheduler = CronScheduler(
                self.config.cron_expression,
                self.config.timezone,
            )

        while not self._stop_event.is_set():
            if use_cron and scheduler is not None:
                if not scheduler.wait(self._stop_event):
                    break
            elif not first_iteration:
                try:
                    if self._stop_event.wait(self.config.interval_seconds):
                        break
                except BaseException:
                    break

            try:
                self.run_once()
            except BaseException as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._last_result = TradingCycleResult(
                    session_id=self.config.session_id,
                    mode=self.config.mode,
                    cycle_time=datetime.now().isoformat(),
                    selection_count=0,
                    long_candidate_count=0,
                    short_candidate_count=0,
                    executed_buy_count=0,
                    executed_sell_count=0,
                    status="error",
                    error=traceback.format_exc(),
                )
                try:
                    self._persist_runtime_state(extra={"event": "cycle_error"})
                except Exception:
                    pass
            first_iteration = False

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = Thread(target=self._run_scheduler, daemon=False)
        self._thread.start()
        self._persist_runtime_state(extra={"event": "service_started"})

    def stop(self):
        if not self._running:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._running = False
        self._persist_runtime_state(extra={"event": "service_stopped"})

    def close(self) -> None:
        if self._running:
            self.stop()
        close = getattr(self.persistence, "close", None)
        if callable(close):
            close()

    def close_all_positions(self, slippage: float = 0.0) -> CloseAllPositionsResponse:
        with self._lock:
            holdings = self.gateway.oms.executable_holds
            if not holdings:
                return CloseAllPositionsResponse(
                    status="no_holdings",
                    closed_count=0,
                    executed_trades=[],
                )

            trades = self.gateway.close_all_positions(slippage=slippage)
            self._persist_trades(trades)

            return CloseAllPositionsResponse(
                status="success",
                closed_count=len(trades),
                executed_trades=[trade.model_dump(mode="json") for trade in trades],
            )

    def signal_buy_symbol(
        self,
        symbol: str,
        target_qty: Optional[int] = None,
        slippage: float = 0.0,
    ) -> SingleSymbolTradeResponse:
        with self._lock:
            latest_prices = self.gateway.get_latest_prices([symbol])
            if latest_prices.empty or symbol not in latest_prices.index:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_buy",
                    symbol=symbol,
                    executed=False,
                    message=f"Unable to get latest price for {symbol}",
                )

            price = latest_prices[symbol]
            exec_price = self._apply_slippage(price, "BUY") if slippage > 0 else price

            if target_qty is None:
                positions = self.gateway.oms.get_positions()
                available_balance = positions.available_balance
                if available_balance <= 0:
                    return SingleSymbolTradeResponse(
                        status="error",
                        action="signal_buy",
                        symbol=symbol,
                        executed=False,
                        message=f"Insufficient available balance: {available_balance}",
                    )
                target_qty = int(available_balance // exec_price)
                if target_qty <= 0:
                    return SingleSymbolTradeResponse(
                        status="error",
                        action="signal_buy",
                        symbol=symbol,
                        executed=False,
                        message=f"Available balance is too low to buy a single share at {exec_price}",
                    )

            try:
                order = Order(symbol=symbol, price=exec_price, volume=target_qty)
                trade = self.gateway.oms.signal_buy(order)
                self._persist_trades([trade])

                return SingleSymbolTradeResponse(
                    status="success",
                    action="signal_buy",
                    symbol=symbol,
                    executed=True,
                    trade=trade.model_dump(mode="json"),
                    message=f"Bought {symbol} {target_qty} shares @ {exec_price:.2f}",
                )
            except Exception as exc:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_buy",
                    symbol=symbol,
                    executed=False,
                    message=f"Buy failed: {exc}",
                )

    def signal_sell_symbol(
        self,
        symbol: str,
        target_qty: Optional[int] = None,
        slippage: float = 0.0,
    ) -> SingleSymbolTradeResponse:
        with self._lock:
            positions = self.gateway.oms.get_positions()
            holdings_map = {h.symbol: h for h in positions.holds}

            if symbol not in holdings_map:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_sell",
                    symbol=symbol,
                    executed=False,
                    message=f"No holdings found for {symbol}",
                )

            holding = holdings_map[symbol]
            latest_prices = self.gateway.get_latest_prices([symbol])
            if latest_prices.empty or symbol not in latest_prices.index:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_sell",
                    symbol=symbol,
                    executed=False,
                    message=f"Unable to get latest price for {symbol}",
                )

            price = latest_prices[symbol]
            exec_price = self._apply_slippage(price, "SELL") if slippage > 0 else price

            sell_qty = target_qty if target_qty else holding.volume
            if sell_qty > holding.volume:
                sell_qty = holding.volume

            try:
                order = Order(symbol=symbol, price=exec_price, volume=sell_qty)
                trade = self.gateway.oms.signal_sell(order)
                self._persist_trades([trade])

                pnl = (exec_price - holding.avg_cost) * sell_qty
                pnl_pct = (pnl / (holding.avg_cost * sell_qty) * 100) if holding.avg_cost > 0 else 0

                return SingleSymbolTradeResponse(
                    status="success",
                    action="signal_sell",
                    symbol=symbol,
                    executed=True,
                    trade=trade.model_dump(mode="json"),
                    message=f"Sold {symbol} {sell_qty} shares @ {exec_price:.2f}, PnL: {pnl:.2f} ({pnl_pct:.2f}%)",
                )
            except Exception as exc:
                return SingleSymbolTradeResponse(
                    status="error",
                    action="signal_sell",
                    symbol=symbol,
                    executed=False,
                    message=f"Sell failed: {exc}",
                )
