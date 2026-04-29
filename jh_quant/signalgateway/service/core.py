from __future__ import annotations

import traceback
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from threading import Event, RLock, Thread
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from jh_quant.backtest.backtest import evaluate_strategies as backtest_evaluate_strategies

from ..config import (
    PortfolioSpec,
    SELECTION_PROVIDER_REGISTRY,
    STRATEGY_REGISTRY,
    RiskManagementParamsConfig,
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
from ..oms import MockOMS
from ..signalgateway import SignalGateway
from ..utils import rprint
from .schemas import (
    AnalyticsSnapshotResponse,
    CloseAllPositionsResponse,
    ComparisonSummary,
    DataCountResponse,
    DataQueryResponse,
    DataSchemaResponse,
    DataTypesListResponse,
    DEFAULT_PERFORMANCE_COMPARE_LIMIT,
    MAX_DATA_QUERY_ROWS,
    PerformanceComparisonItem,
    PerformanceComparisonResponse,
    PerformanceSnapshotResponse,
    RuntimeSnapshotResponse,
    SchedulerConfigSnapshotResponse,
    SchedulerConfigUpdateResponse,
    SchedulerStatus,
    ServiceComparisonResponse,
    ServiceConfigResponse,
    ServiceConfigUpdateResponse,
    ServiceEventHistoryResponse,
    ServiceInfoResponse,
    ServiceListResponse,
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
        persistence: Optional[PersistenceCoordinator] = None,
    ):
        self.gateway = gateway
        self.service_config = config
        self.config = config.service
        self.selection_specs = config.selection_spec
        self.strategy_specs = list(config.strategy_specs)
        self.portfolio_spec = config.portfolio_spec
        self.persistence = persistence or PersistenceCoordinator()
        self._latest_portfolio_optimization: Optional[Dict[str, Any]] = None
        self._latest_portfolio_rebalance: Optional[Dict[str, Any]] = None
        self._last_portfolio_rebalance_at: Optional[datetime] = None
        self.selection_provider: Optional[SelectionProvider] = None
        self._config_source = "bootstrap"
        self._persisted_user_config_available = False
        self._persisted_user_config_updated_at: Optional[str] = None
        self._suspend_user_config_persistence = True

        oms_session_id = getattr(self.gateway.oms, "session_id", None)
        if self.config.session_id is None:
            self.config.session_id = oms_session_id or str(uuid.uuid4())
        elif not oms_session_id:
            self.gateway.oms.session_id = self.config.session_id

        self._lock = RLock()
        self._scheduler_stop_event = Event()
        self._scheduler_thread: Optional[Thread] = None
        self._scheduler_running = False
        self._last_result: Optional[TradingCycleResult] = None
        self._last_error: Optional[str] = None

        self._restore_user_config()
        self._restore_service_state()
        self._initialize_selection_provider(selection_provider)
        self._restore_oms_state()
        if self.strategy_specs:
            self.configure_strategies(self.strategy_specs)

        self._suspend_user_config_persistence = False

        if self.config.auto_start:
            self.start_scheduler()

    def _restore_oms_state(self):
        try:
            saved = self.persistence.load_latest_session_state(self.config.session_id)
            if saved:
                self.gateway.oms.import_state(saved)
        except Exception:
            pass

    def _apply_config_bundle(
        self,
        config_bundle: SignalGatewayServiceConfig | Dict[str, Any],
        *,
        source: str,
    ) -> None:
        restored_bundle = (
            config_bundle
            if isinstance(config_bundle, SignalGatewayServiceConfig)
            else SignalGatewayServiceConfig.model_validate(config_bundle)
        )
        restored_session_id = self.config.session_id
        restored_restore_flag = self.config.restore_persisted_state
        self.service_config = restored_bundle
        self.config = self.service_config.service
        self.config.session_id = restored_session_id or self.config.session_id
        self.config.restore_persisted_state = restored_restore_flag
        self.service_config.service = self.config
        self.selection_specs = self.service_config.selection_spec
        self.strategy_specs = list(self.service_config.strategy_specs)
        self.portfolio_spec = self.service_config.portfolio_spec
        self._config_source = source

    def _restore_user_config(self) -> None:
        if not self.config.restore_persisted_state:
            return

        try:
            saved = self.persistence.load_latest_user_config(self.config.session_id)
            if not saved:
                return
            config_bundle = saved.get("config_bundle")
            if not config_bundle:
                return
            self._persisted_user_config_available = True
            self._persisted_user_config_updated_at = saved.get("export_time")
            self._apply_config_bundle(config_bundle, source="persisted_user_config")
        except Exception:
            pass

    def _restore_service_state(self) -> None:
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
        if (
            config_bundle
            and self.config.restore_persisted_state
            and not self._persisted_user_config_available
        ):
            self._apply_config_bundle(config_bundle, source="persisted_user_config")
            self._persisted_user_config_available = True
            self._persisted_user_config_updated_at = state.get("export_time")

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
            self._persist_user_config(source="runtime_update")
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
            self._persist_user_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "selection_config_updated"})

    def configure_portfolio(self, portfolio_spec):
        with self._lock:
            self.portfolio_spec = portfolio_spec
            self.service_config.portfolio_spec = portfolio_spec
            self._persist_user_config(source="runtime_update")
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
        elif self._last_result and self._scheduler_running:
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

        was_scheduler_running = self._scheduler_running
        if was_scheduler_running:
            self.stop_scheduler()

        with self._lock:
            if interval_seconds is not None:
                self.config.interval_seconds = interval_seconds
            self.config.cron_expression = cron_expression
            if timezone is not None:
                self.config.timezone = timezone
            if auto_start is not None:
                self.config.auto_start = auto_start
            self._persist_user_config(source="runtime_update")

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

        should_start = was_scheduler_running or self.config.auto_start
        if should_start:
            self.start_scheduler()

        return SchedulerConfigUpdateResponse(
            status="updated",
            running=self._scheduler_running,
            scheduler=self._build_scheduler_status(),
            auto_start=self.config.auto_start,
        ).model_dump()

    def replace_service_config(self, config_bundle: SignalGatewayServiceConfig) -> Dict[str, Any]:
        was_scheduler_running = self._scheduler_running
        if was_scheduler_running:
            self.stop_scheduler()

        with self._lock:
            self._apply_config_bundle(config_bundle.model_copy(deep=True), source="runtime_update")
            self._initialize_selection_provider(None)
            if self.strategy_specs:
                normalized_specs = [normalize_strategy_spec(spec) for spec in self.strategy_specs]
                built = [self._build_strategy_instance(spec) for spec in normalized_specs]
                self.gateway.replace_strategies(built)
                self.strategy_specs = normalized_specs
                self.service_config.strategy_specs = list(normalized_specs)
            else:
                self.gateway.replace_strategies([])

            self._persist_user_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "service_config_replaced"})

        if was_scheduler_running or self.config.auto_start:
            self.start_scheduler()

        return ServiceConfigUpdateResponse(
            status="updated",
            session_id=self.config.session_id,
            config_bundle=self.service_config,
        ).model_dump()

    def get_scheduler_config_snapshot(self) -> Dict[str, Any]:
        return SchedulerConfigSnapshotResponse(
            running=self._scheduler_running,
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

    def _log_execution_branch(self, branch: str, message: str) -> None:
        rprint(label=f"Service:{branch}", content=message)

    def _filter_sell_orders_by_executable_holdings(
        self,
        sell_orders: pd.DataFrame,
        latest_prices: pd.Series,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], float]:
        if sell_orders is None or sell_orders.empty:
            return pd.DataFrame(columns=["symbol", "target_qty"]), [], 0.0

        executable_map = {
            hold.symbol: int(hold.volume)
            for hold in self.gateway.oms.executable_holds
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

            executable_rows.append({"symbol": symbol, "target_qty": allowed_qty})
            if symbol in latest_prices.index:
                projected_sell_value += float(latest_prices[symbol]) * float(allowed_qty)

        filtered_orders = pd.DataFrame(executable_rows, columns=["symbol", "target_qty"])
        return filtered_orders, blocked_rows, projected_sell_value

    def _cap_buy_orders_to_cash_budget(
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
                allowed_qty = affordable_lots * lot_size
                allowed_qty = min(allowed_qty, requested_qty)

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

        filtered_orders = pd.DataFrame(executable_rows, columns=["symbol", "target_qty"])
        return filtered_orders, blocked_rows, projected_buy_cost

    def _build_portfolio_strategy_context(
        self,
        *,
        cycle_date: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        base_date = datetime.strptime(cycle_date, "%Y-%m-%d")
        lookback_days = max(self.config.price_lookback_days, self.portfolio_spec.historical_lookback_days)
        price_start = (base_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        if symbols is None:
            selection = self.selection_provider.select(as_of_date=cycle_date)
            selected_symbols = list(selection.top_selections)
        else:
            selected_symbols = list(symbols)
        selected_symbols = list(dict.fromkeys(str(symbol) for symbol in selected_symbols if symbol))
        if not selected_symbols:
            raise ValueError("No symbols available for portfolio optimization")

        price = self.gateway.get_price_data(
            symbols=selected_symbols,
            start_date=price_start,
            end_date=cycle_date,
            frequency=self.config.frequency,
        )
        buy_signals = self.gateway.aggregate_buy_signals(
            price=price,
            frequency=self.config.frequency,
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
        strategy_registered = bool(getattr(self.gateway, "strategy_pool", []))
        used_strategy_filter = strategy_registered and not positive_signals.empty
        fallback_reason: Optional[str] = None

        if used_strategy_filter:
            optimization_signals = positive_signals.sort_values(
                by=["score", "symbol"],
                ascending=[False, True],
            ).reset_index(drop=True)
        else:
            optimization_signals = signal_frame.copy()
            if strategy_registered:
                fallback_reason = "no_positive_buy_scores"
            else:
                fallback_reason = "no_strategy_registered"

        if optimization_signals.empty:
            raise ValueError("No symbols available after applying strategy-aware portfolio filters")

        if float(optimization_signals["score"].clip(lower=0.0).sum()) <= 0:
            optimization_signals["score"] = 1.0

        optimization_symbols = optimization_signals["symbol"].astype(str).tolist()
        filtered_price = price[price["symbol"].isin(optimization_symbols)].copy() if not price.empty else price

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

    def _persist_runtime_state(self, extra: Optional[Dict[str, Any]] = None):
        payload = {
            "session_id": self.config.session_id,
            "export_time": datetime.now().isoformat(),
            "service": {
                "config_bundle": self.service_config.model_dump(mode="json"),
                "config": self.config.model_dump(),
                "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
                "portfolio_spec": self.portfolio_spec.model_dump(mode="json"),
                "config_source": self._config_source,
                "persisted_user_config_available": self._persisted_user_config_available,
                "persisted_user_config_updated_at": self._persisted_user_config_updated_at,
                "running": self._scheduler_running,
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

    def _persist_user_config(self, *, source: str = "runtime_update") -> None:
        if self._suspend_user_config_persistence:
            return
        export_time = datetime.now().isoformat()
        config_bundle = self.service_config.model_dump(mode="json")
        config_bundle["export_time"] = export_time
        self.persistence.save_user_config(
            self.config.session_id,
            config_bundle,
            source=source,
        )
        self._persisted_user_config_available = True
        self._persisted_user_config_updated_at = export_time
        self._config_source = source

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
            config_source=self._config_source,
            persisted_user_config_available=self._persisted_user_config_available,
            persisted_user_config_updated_at=self._persisted_user_config_updated_at,
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
        context = self._build_portfolio_strategy_context(
            cycle_date=cycle_date,
            symbols=symbols,
        )
        optimization_symbols = context["optimization_symbols"]
        price = context["price"]
        returns = self.gateway.build_return_matrix(
            symbols=optimization_symbols,
            start_date=context["price_start"],
            end_date=cycle_date,
            frequency=self.config.frequency,
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
            self._log_execution_branch(
                "portfolio",
                (
                    "组合优化使用 Strategy 过滤后的目标池，"
                    f"selected={context['selection_count']}, "
                    f"positive_signals={context['positive_signal_count']}, "
                    f"optimized={len(optimization_symbols)}"
                ),
            )
        else:
            self._log_execution_branch(
                "portfolio",
                (
                    "组合优化未拿到可用的正向 Strategy 信号，回退到 Selection universe，"
                    f"fallback_reason={context['fallback_reason']}, "
                    f"selected={context['selection_count']}"
                ),
            )
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
            self._log_execution_branch(
                "portfolio",
                f"组合调仓分支开始执行，cycle_date={cycle_date}, force={force}, preview_only={preview_only}",
            )
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
            planned_sell_orders = pd.DataFrame(plan["sell_orders"])
            executable_sell_orders, blocked_sell_orders, executable_sell_value = (
                self._filter_sell_orders_by_executable_holdings(
                    planned_sell_orders,
                    latest_prices,
                )
            )
            planned_buy_orders = pd.DataFrame(plan["buy_orders"])
            cash_budget = float(positions_snapshot.get("available_balance") or 0.0) + executable_sell_value
            executable_buy_orders, blocked_buy_orders, executable_buy_cost = self._cap_buy_orders_to_cash_budget(
                planned_buy_orders,
                latest_prices,
                cash_budget,
            )
            projected_cash_after = cash_budget - executable_buy_cost
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

            self._log_execution_branch(
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
                self._log_execution_branch(
                    "portfolio",
                    f"检测到 {len(blocked_sell_orders)} 笔卖单受 executable_holds / A股T+1 约束影响。",
                )

            if preview_only or not should_rebalance:
                self._latest_portfolio_rebalance = payload
                self._persist_runtime_state(extra={"event": "portfolio_rebalance_preview"})
                return payload

            sell_orders = executable_sell_orders
            buy_orders = executable_buy_orders
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
            self._log_execution_branch(
                "portfolio",
                f"组合调仓执行完成，executed_sells={len(executed_sells)}, executed_buys={len(executed_buys)}",
            )
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
            running=self._scheduler_running,
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
                self._log_execution_branch(
                    "portfolio",
                    "run_once 命中 portfolio_spec.enabled=True，使用 Strategy 驱动的 portfolio overlay 分支：Selection/Strategy 决定目标池，Portfolio 负责配权与调仓。",
                )
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
                self._log_execution_branch(
                    "signals",
                    "run_once 命中 portfolio_spec.enabled=False，使用标准信号分支 gateway.execute_cycle。",
                )
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
                latest_price_symbols = list(top_selections)
                current_holds = getattr(self.gateway.oms.get_positions(), "holds", [])
                latest_price_symbols.extend(
                    hold.symbol for hold in current_holds if getattr(hold, "symbol", None)
                )
                latest_price_symbols = list(dict.fromkeys(latest_price_symbols))
                latest_prices = (
                    self.gateway.get_latest_prices(latest_price_symbols)
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

    def _run_scheduler_loop(self):
        use_cron = bool(self.config.cron_expression)
        scheduler: Optional[CronScheduler] = None
        first_iteration = True
        if use_cron:
            scheduler = CronScheduler(
                self.config.cron_expression,
                self.config.timezone,
            )

        while not self._scheduler_stop_event.is_set():
            if use_cron and scheduler is not None:
                if not scheduler.wait(self._scheduler_stop_event):
                    break
            elif not first_iteration:
                try:
                    if self._scheduler_stop_event.wait(self.config.interval_seconds):
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

    def start_scheduler(self):
        if self._scheduler_running:
            return
        self._scheduler_stop_event.clear()
        self._scheduler_running = True
        self._scheduler_thread = Thread(target=self._run_scheduler_loop, daemon=False)
        self._scheduler_thread.start()
        self._persist_runtime_state(extra={"event": "scheduler_started"})

    def stop_scheduler(self):
        if not self._scheduler_running:
            return
        self._scheduler_stop_event.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=5)
        self._scheduler_running = False
        self._persist_runtime_state(extra={"event": "scheduler_stopped"})

    def shutdown_service(self) -> None:
        if self._scheduler_running:
            self.stop_scheduler()
        self._persist_runtime_state(extra={"event": "service_shutdown"})

    # ── Data API ──────────────────────────────────────────────

    def _get_jhdata(self):
        """Resolve JHData instance from the gateway's market_data_provider."""
        from ..market_data import JHMarketDataProvider

        provider = getattr(self.gateway, "market_data_provider", None)
        if provider is None:
            raise RuntimeError("MarketDataProvider is not configured on the gateway")
        if not isinstance(provider, JHMarketDataProvider):
            raise RuntimeError(
                f"Data API requires a JHMarketDataProvider, got {type(provider).__name__}"
            )
        return provider.jhd

    def _validate_data_type(self, data_type_str: str):
        from jh_quant.data import DataTypes

        try:
            return DataTypes(data_type_str)
        except ValueError:
            raise ValueError(
                f"Unknown data_type '{data_type_str}'. "
                f"Use GET /data/types to list available types."
            )

    def get_data_count(self, *, data_type: str, symbol: Optional[str] = None, ts_code: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
        dt = self._validate_data_type(data_type)
        jhd = self._get_jhdata()
        kwargs = {}
        if symbol:
            kwargs["symbol"] = symbol
        if ts_code:
            kwargs["ts_code"] = ts_code
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end
        count = jhd.get_data_total(dt, **kwargs)
        return DataCountResponse(data_type=data_type, count=count).model_dump()

    def get_data_query(self, *, data_type: str, symbol: Optional[str] = None, ts_code: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None, remote: bool = False) -> Dict[str, Any]:
        dt = self._validate_data_type(data_type)
        jhd = self._get_jhdata()
        kwargs = {}
        if symbol:
            kwargs["symbol"] = symbol
        if ts_code:
            kwargs["ts_code"] = ts_code
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end

        total = jhd.get_data_total(dt, **kwargs)
        if total == 0:
            return DataQueryResponse(
                status="empty",
                data_type=data_type,
                count=0,
                message="No data available for the given parameters.",
            ).model_dump()

        if total > MAX_DATA_QUERY_ROWS:
            suggestion = "Please narrow your query by providing one or more of: symbol, ts_code, start, end."
            return DataQueryResponse(
                status="too_large",
                data_type=data_type,
                count=total,
                message=f"Data count ({total}) exceeds the maximum direct-return threshold ({MAX_DATA_QUERY_ROWS}).",
                suggestion=suggestion,
            ).model_dump()

        df = jhd.get_data(dt, remote=remote, **kwargs)
        if df is None or (hasattr(df, "empty") and df.empty):
            return DataQueryResponse(
                status="empty",
                data_type=data_type,
                count=0,
                message="No data returned after fetch.",
            ).model_dump()

        if hasattr(df, "to_df"):
            df = df.to_df()
        records = df.to_dict(orient="records")
        return DataQueryResponse(
            status="ok",
            data_type=data_type,
            count=len(records),
            data=records,
            message=f"Returned {len(records)} rows.",
        ).model_dump()

    def list_data_types(self) -> Dict[str, Any]:
        from jh_quant.data import DataTypes

        types = [
            {"value": dt.value, "name": dt.name}
            for dt in DataTypes
        ]
        return DataTypesListResponse(types=types, count=len(types)).model_dump()

    def get_data_schema(self, data_type: str) -> Dict[str, Any]:
        from jh_quant.data.data_types import get_table_fields, get_table_unique_keys, get_table_dt_field

        dt = self._validate_data_type(data_type)
        fields = get_table_fields(dt)
        unique_keys = get_table_unique_keys(dt)
        dt_field = get_table_dt_field(dt)
        return DataSchemaResponse(
            data_type=data_type,
            fields=fields,
            unique_keys=unique_keys,
            dt_field=dt_field,
        ).model_dump()

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

    def evaluate_strategies(
        self,
        symbol_source: str = "selection",
        as_of_date: Optional[str] = None,
        lookback_days: Optional[int] = None,
        commission_rate: float = 0.0002,
        stamp_tax_rate: float = 0.0005,
    ) -> Dict[str, Any]:
        """Evaluate configured strategies on historical price data.

        Uses the backtest module's evaluate_strategies() to compute per-stock,
        per-strategy performance metrics.

        Args:
            symbol_source: 'selection' or 'holdings'.
            as_of_date: Evaluation end date in YYYY-MM-DD format.
            lookback_days: Override for lookback days.
            commission_rate: Commission rate.
            stamp_tax_rate: Stamp tax rate for sells.
        """
        if not self.gateway.strategy_pool:
            raise ValueError("No strategies configured in the strategy pool")

        cycle_date = self._as_of_date(as_of_date)
        actual_lookback = lookback_days or self.config.price_lookback_days
        price_start = (
            datetime.strptime(cycle_date, "%Y-%m-%d") - timedelta(days=actual_lookback)
        ).strftime("%Y-%m-%d")

        if symbol_source == "holdings":
            positions = self.gateway.oms.get_positions()
            symbols = [h.symbol for h in positions.holds]
            if not symbols:
                raise ValueError("No holdings available for evaluation")
        else:
            selection = self.selection_provider.select(as_of_date=cycle_date)
            symbols = list(selection.top_selections)
            if not symbols:
                raise ValueError("No selection symbols available for evaluation")

        price = self.gateway.get_price_data(
            symbols=symbols,
            start_date=price_start,
            end_date=cycle_date,
            frequency=self.config.frequency,
        )
        if price.empty:
            raise ValueError("No price data available for the requested period")

        strategies: Dict[str, Any] = {
            item["name"]: item["strategy"]
            for item in self.gateway.strategy_pool
        }

        from jh_quant.backtest.risk_management import RiskManagementParams

        rmps: Dict[str, RiskManagementParams] = {}
        for name, config in self.service_config.risk_management_specs.items():
            rmps[name] = config.to_backtest_rmp()

        combined_performance, trading_history_data = backtest_evaluate_strategies(
            price=price,
            strategies=strategies,
            rmps=rmps,
            commission_rate=commission_rate,
            stamp_tax_rate=stamp_tax_rate,
        )

        th_df = trading_history_data.to_df() if hasattr(trading_history_data, "to_df") else trading_history_data

        return {
            "status": "completed",
            "as_of_date": cycle_date,
            "symbol_source": symbol_source,
            "symbols": symbols,
            "strategy_count": len(strategies),
            "metrics": self._records_from_frame(combined_performance),
            "trading_history": self._records_from_frame(th_df),
        }

    def get_risk_management_config(self) -> Dict[str, Any]:
        """Return the current per-strategy risk management configuration."""
        return {
            "risk_management_specs": self.service_config.risk_management_specs,
        }

    def update_risk_management_config(
        self,
        risk_management_specs: Dict[str, RiskManagementParamsConfig],
    ) -> Dict[str, Any]:
        """Replace the entire per-strategy risk management configuration."""
        with self._lock:
            self.service_config.risk_management_specs = dict(risk_management_specs)
            self._persist_user_config(source="runtime_update")
            self._persist_runtime_state(extra={"event": "risk_management_config_updated"})
        return {
            "status": "updated",
            "risk_management_specs": self.service_config.risk_management_specs,
        }

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


class MultiServiceManager:
    """Manages multiple SignalGatewayService instances in a single process.

    Each service gets its own MockOMS (isolated by session_id) and scheduler
    thread, while sharing a common PersistenceCoordinator and
    MarketDataProvider.
    """

    def __init__(
        self,
        max_services: int = 4,
        persistence: Optional[PersistenceCoordinator] = None,
        market_data_provider=None,
    ):
        self._max_services = max(max_services, 1)
        self._shared_persistence = persistence or PersistenceCoordinator()
        self._shared_md_provider = market_data_provider
        self._services: Dict[str, SignalGatewayService] = {}
        self._lock = RLock()

    # ── service lifecycle ──────────────────────────────────────

    def create_service(
        self,
        config: SignalGatewayServiceConfig,
        initial_capital: float = 100000,
    ) -> str:
        """Create and register a new service from config.

        Returns the session_id of the created service.
        """
        with self._lock:
            if len(self._services) >= self._max_services:
                raise ValueError(
                    f"Maximum number of services reached ({self._max_services}). "
                    f"Remove an existing service before creating a new one."
                )

            session_id = config.service.session_id or str(uuid.uuid4())
            if session_id in self._services:
                raise ValueError(
                    f"Service with session_id '{session_id}' already exists."
                )

            config.service.session_id = session_id
            oms = MockOMS(session_id=session_id, initial_capital=initial_capital)
            gateway = SignalGateway(
                oms=oms,
                market_data_provider=self._shared_md_provider,
            )
            service = SignalGatewayService(
                gateway=gateway,
                config=config,
                persistence=self._shared_persistence,
            )
            self._services[session_id] = service
            return session_id

    def remove_service(self, session_id: str) -> None:
        """Shutdown and remove a service by session_id."""
        with self._lock:
            service = self._services.pop(session_id, None)
        if service is not None:
            service.shutdown_service()

    def get_service(self, session_id: str) -> SignalGatewayService:
        """Get a service by session_id.

        Raises KeyError if not found.
        """
        with self._lock:
            if session_id not in self._services:
                raise KeyError(f"Service with session_id '{session_id}' not found")
            return self._services[session_id]

    def stop_all(self) -> None:
        """Shutdown all managed services, then close shared persistence."""
        with self._lock:
            services = list(self._services.values())
            self._services.clear()
        for service in services:
            try:
                service.shutdown_service()
            except Exception:
                pass
        close = getattr(self._shared_persistence, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    @property
    def max_services(self) -> int:
        return self._max_services

    # ── query ──────────────────────────────────────────────────

    def list_services(self) -> ServiceListResponse:
        """Return metadata for all managed services."""
        items: list[ServiceInfoResponse] = []
        with self._lock:
            for session_id, svc in self._services.items():
                items.append(self._build_service_info(session_id, svc))
        return ServiceListResponse(
            services=items,
            count=len(items),
            max_services=self._max_services,
        )

    def get_comparison(self) -> ServiceComparisonResponse:
        """Aggregate performance/status across all services for comparison."""
        summaries: list[ComparisonSummary] = []
        with self._lock:
            for session_id, svc in self._services.items():
                summaries.append(self._build_comparison_summary(session_id, svc))
        return ServiceComparisonResponse(
            generated_at=datetime.now().isoformat(),
            count=len(summaries),
            services=summaries,
        )

    def get_performance_comparison(
        self,
        session_ids: Optional[List[str]] = None,
        limit: int = DEFAULT_PERFORMANCE_COMPARE_LIMIT,
    ) -> PerformanceComparisonResponse:
        """Compare historical performance (incl. equity curves) across sessions.

        Args:
            session_ids: Specific sessions to compare. If None, returns the
                latest sessions up to *limit*.
            limit: Max sessions when session_ids is not specified.
        """
        with self._lock:
            all_ids = list(self._services.keys())
            if session_ids is not None:
                target_ids = [sid for sid in session_ids if sid in self._services]
            elif len(all_ids) > limit:
                target_ids = all_ids[-limit:]
            else:
                target_ids = list(all_ids)

        items: list[PerformanceComparisonItem] = []
        note: Optional[str] = None
        if session_ids is None and len(all_ids) > limit:
            note = (
                f"Showing latest {len(target_ids)} of {len(all_ids)} sessions. "
                f"Use ?session_ids=... to select specific sessions."
            )

        for sid in target_ids:
            with self._lock:
                svc = self._services.get(sid)
            if svc is None:
                continue
            items.append(self._build_performance_comparison_item(sid, svc))

        return PerformanceComparisonResponse(
            generated_at=datetime.now().isoformat(),
            count=len(items),
            sessions=items,
            note=note,
        )

    # ── helpers ────────────────────────────────────────────────

    def _build_service_info(self, session_id: str, svc: SignalGatewayService) -> ServiceInfoResponse:
        positions = svc.gateway.oms.get_positions()
        current_value = float(positions.total) if positions else None
        selection_name = getattr(svc.selection_specs, "alias", None) or getattr(svc.selection_specs, "name", None)
        portfolio_enabled = bool(getattr(svc.portfolio_spec, "enabled", False))

        return ServiceInfoResponse(
            session_id=session_id,
            mode=svc.config.mode,
            running=svc._scheduler_running,
            strategy_count=len(svc.strategy_specs),
            selection_name=str(selection_name) if selection_name else None,
            portfolio_enabled=portfolio_enabled,
            initial_capital=getattr(svc.gateway.oms, "initial_capital", 0.0),
            current_value=current_value,
            last_error=svc._last_error,
            last_result=svc._serialize_result(svc._last_result),
        )

    def _build_comparison_summary(self, session_id: str, svc: SignalGatewayService) -> ComparisonSummary:
        positions = svc.gateway.oms.get_positions()
        current_value = float(positions.total) if positions else None
        initial_capital = float(getattr(svc.gateway.oms, "initial_capital", 0.0))
        total_return_pct = None
        if current_value is not None and initial_capital > 0:
            total_return_pct = round((current_value - initial_capital) / initial_capital * 100, 2)
        daily_pnl = float(getattr(positions, "daily_profit", 0.0)) if positions else None
        selection_name = getattr(svc.selection_specs, "alias", None) or getattr(svc.selection_specs, "name", None)

        return ComparisonSummary(
            session_id=session_id,
            mode=svc.config.mode,
            running=svc._scheduler_running,
            initial_capital=initial_capital,
            current_value=current_value,
            total_return_pct=total_return_pct,
            daily_pnl=daily_pnl,
            position_count=len(getattr(positions, "holds", [])),
            strategy_names=[spec.alias or spec.name for spec in svc.strategy_specs],
            selection_name=str(selection_name) if selection_name else None,
        )

    def _build_performance_comparison_item(self, session_id: str, svc: SignalGatewayService) -> PerformanceComparisonItem:
        report = self._shared_persistence.get_performance_report(session_id)
        summary = report.get("summary", {})
        equity_curve = report.get("equity_curve")
        positions = svc.gateway.oms.get_positions()
        current_value = float(positions.total) if positions else None
        initial_capital = float(getattr(svc.gateway.oms, "initial_capital", 0.0))
        total_return_pct = None
        if current_value is not None and initial_capital > 0:
            total_return_pct = round((current_value - initial_capital) / initial_capital * 100, 2)

        equity_rows: list[dict] = []
        if equity_curve is not None and not equity_curve.empty:
            curve = equity_curve.copy()
            if hasattr(curve, "to_dict"):
                equity_rows = curve.to_dict(orient="records")
            else:
                equity_rows = list(curve)

        selection_name = getattr(svc.selection_specs, "alias", None) or getattr(svc.selection_specs, "name", None)

        return PerformanceComparisonItem(
            session_id=session_id,
            mode=svc.config.mode,
            initial_capital=initial_capital,
            strategy_names=[spec.alias or spec.name for spec in svc.strategy_specs],
            selection_name=str(selection_name) if selection_name else None,
            portfolio_value=current_value,
            total_return_pct=total_return_pct,
            daily_pnl=float(getattr(positions, "daily_profit", 0.0)) if positions else None,
            position_count=len(getattr(positions, "holds", [])),
            total_trades=int(summary.get("total_trades", 0)),
            win_rate=summary.get("win_rate"),
            total_pnl=float(summary.get("total_pnl", 0.0)),
            max_drawdown=float(summary.get("max_drawdown", 0.0)),
            equity_curve=equity_rows,
        )
