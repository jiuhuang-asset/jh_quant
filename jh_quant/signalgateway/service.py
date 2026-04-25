from __future__ import annotations

import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, Field

from .config import STRATEGY_REGISTRY, ServiceConfig
from .persistence_coordinator import PersistenceCoordinator
from .signalgateway import SignalGateway


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

    def peek_next_tick(self) -> datetime:
        from croniter import croniter

        preview_iter = croniter(self.cron_expr, datetime.now(self._tzinfo))
        return preview_iter.get_next(datetime)

    def peek_next_ticks(self, count: int = 3) -> List[datetime]:
        from croniter import croniter

        preview_iter = croniter(self.cron_expr, datetime.now(self._tzinfo))
        return [preview_iter.get_next(datetime) for _ in range(max(0, count))]

    def wait(self, stop_event: Event) -> bool:
        """Return True when the next tick is reached, False if stopped early."""
        timeout = self.get_next_timeout()
        return not stop_event.wait(timeout=timeout)


class StrategySpec(BaseModel):
    name: str
    weight: float = 1.0
    params: Dict[str, Any] = Field(default_factory=dict)
    alias: Optional[str] = None


class LLMCommandRequest(BaseModel):
    command: str
    context: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = Field(description="服务健康状态，通常为 ok")


class SchedulerStatus(BaseModel):
    interval_seconds: int = Field(description="轮询调度间隔，单位为秒")
    cron_expression: Optional[str] = Field(default=None, description="Cron 调度表达式，为空表示使用固定间隔调度")
    timezone: str = Field(description="调度器使用的时区")
    schedule_type: str = Field(default="interval", description="当前调度模式")
    next_run_at: Optional[str] = Field(default=None, description="下一次预计触发时间")
    next_run_in_seconds: Optional[float] = Field(default=None, description="距离下一次触发的秒数")
    next_runs: List[str] = Field(default_factory=list, description="未来几次预计触发时间")

class TradingCycleResultResponse(BaseModel):
    session_id: str = Field(description="Current service session ID")
    mode: str = Field(description="Service running mode, such as paper or live")
    cycle_time: str = Field(description="Completed time for the latest trading cycle")
    selection_count: int = Field(description="Number of selected securities in the latest cycle")
    long_candidate_count: int = Field(description="Number of long candidates identified in the latest cycle")
    short_candidate_count: int = Field(description="Number of short or sell candidates identified in the latest cycle")
    executed_buy_count: int = Field(description="Number of buy orders executed in the latest cycle")
    executed_sell_count: int = Field(description="Number of sell orders executed in the latest cycle")
    selected_symbols: List[str] = Field(default_factory=list, description="Selected symbols in the latest cycle")
    long_symbols: List[str] = Field(default_factory=list, description="Long candidate symbols in the latest cycle")
    short_symbols: List[str] = Field(default_factory=list, description="Short candidate symbols in the latest cycle")
    status: str = Field(default="success", description="Execution status for the latest trading cycle")
    error: Optional[str] = Field(default=None, description="Error text when the latest trading cycle fails")


class ServiceStatusResponse(BaseModel):
    session_id: str = Field(description="Current service session ID")
    mode: str = Field(description="Service running mode")
    running: bool = Field(description="Whether the scheduler is currently running")
    scheduler: SchedulerStatus = Field(description="Scheduler configuration and status summary")
    last_error: Optional[str] = Field(default=None, description="Most recent runtime error")
    last_result: Optional[TradingCycleResultResponse] = Field(
        default=None,
        description="Most recent trading cycle result",
    )


class RuntimeSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the runtime snapshot")
    generated_at: str = Field(description="Snapshot generation time")
    positions: Dict[str, Any] = Field(description="Current positions and runtime state")
    oms_state: Optional[Dict[str, Any]] = Field(default=None, description="Full OMS exported state")


class PerformanceSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the performance snapshot")
    generated_at: str = Field(description="Snapshot generation time")
    summary: Dict[str, Any] = Field(description="Summary performance metrics")
    holding_returns: List[Dict[str, Any]] = Field(default_factory=list, description="Latest holding return rows")
    turnover: List[Dict[str, Any]] = Field(default_factory=list, description="Turnover rows grouped by trade date")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="Equity curve rows grouped by trade date")
    trade_activity: List[Dict[str, Any]] = Field(default_factory=list, description="Trade activity rows grouped by trade date")
    position_exposure: Dict[str, Any] = Field(default_factory=dict, description="Position exposure analysis")
    latest_portfolio: Dict[str, Any] = Field(default_factory=dict, description="Latest portfolio snapshot")


class ServiceConfigResponse(BaseModel):
    session_id: str = Field(description="Session ID for the service configuration snapshot")
    service: Dict[str, Any] = Field(description="Service-level configuration")
    selection_provider: Dict[str, Any] = Field(default_factory=dict, description="Selection provider configuration")
    strategies: List[StrategySpec] = Field(default_factory=list, description="Configured strategies")


class AnalyticsSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the analytics snapshot")
    generated_at: str = Field(description="Snapshot generation time")
    status: ServiceStatusResponse = Field(description="Service status snapshot")
    runtime: RuntimeSnapshotResponse = Field(description="Runtime snapshot")
    performance: PerformanceSnapshotResponse = Field(description="Performance snapshot")
    config: ServiceConfigResponse = Field(description="Config snapshot")


class ServiceActionResponse(BaseModel):
    status: str = Field(description="Result of the service action")
    session_id: Optional[str] = Field(default=None, description="Related session ID for the service action")


class StrategyConfigUpdateResponse(BaseModel):
    status: str = Field(description="Strategy configuration update result")
    count: int = Field(description="Number of strategy configs applied")


class SchedulerConfigUpdateRequest(BaseModel):
    interval_seconds: Optional[int] = Field(default=None, ge=1)
    cron_expression: Optional[str] = Field(default=None)
    timezone: Optional[str] = Field(default=None)
    auto_start: Optional[bool] = Field(default=None)


class SchedulerConfigUpdateResponse(BaseModel):
    status: str = Field(description="Scheduler configuration update result")
    running: bool = Field(description="Whether the scheduler is running after the update")
    scheduler: SchedulerStatus = Field(description="Updated scheduler configuration")
    auto_start: bool = Field(description="Updated auto-start configuration")

@dataclass
class SelectionSnapshot:
    top_selections: List[str]
    bottom_selections: Optional[List[str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradingCycleResult:
    session_id: str
    mode: str
    cycle_time: str
    selection_count: int
    long_candidate_count: int
    short_candidate_count: int
    executed_buy_count: int
    executed_sell_count: int
    selected_symbols: List[str] = field(default_factory=list)
    long_symbols: List[str] = field(default_factory=list)
    short_symbols: List[str] = field(default_factory=list)
    status: str = "success"
    error: Optional[str] = None


@runtime_checkable
class SelectionProvider(Protocol):
    def select(self, as_of_date: str) -> SelectionSnapshot:
        raise NotImplementedError("SelectionProvider subclasses must implement the select method")

    @property
    def config(self) -> Dict[str, Any]:
        return {}


class SignalGatewayService:
    def __init__(
        self,
        gateway: SignalGateway,
        config: ServiceConfig,
        selection_provider: SelectionProvider,
        strategy_specs: List[StrategySpec],
        llm_handler: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        persistence: Optional[PersistenceCoordinator] = None,
    ):
        self.gateway = gateway
        self.config = config
        self.selection_provider = selection_provider
        self.strategy_specs = strategy_specs
        self.llm_handler = llm_handler
        self.persistence = persistence or PersistenceCoordinator()

        oms_session_id = getattr(self.gateway.oms, "session_id", None)
        if self.config.session_id is None:
            self.config.session_id = oms_session_id or str(uuid.uuid4())
        elif not oms_session_id:
            self.gateway.oms.session_id = self.config.session_id

        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._running = False
        self._last_result: Optional[TradingCycleResult] = None
        self._last_error: Optional[str] = None

        self._restore_oms_state()
        self.configure_strategies(strategy_specs)

        if self.config.auto_start:
            self.start()

    def _restore_oms_state(self):
        try:
            saved = self.persistence.load_latest_session_state(self.config.session_id)
            if saved:
                self.gateway.oms.import_state(saved)
        except Exception:
            pass

    def _build_strategy_instance(self, spec: StrategySpec) -> dict:
        if spec.name not in STRATEGY_REGISTRY:
            raise ValueError(f"Unsupported strategy name: {spec.name}")
        strategy_cls = STRATEGY_REGISTRY[spec.name]
        strategy = strategy_cls(**spec.params)
        return {
            "name": spec.alias or spec.name,
            "strategy": strategy,
            "weight": spec.weight,
        }

    def configure_strategies(self, strategy_specs: List[StrategySpec]):
        with self._lock:
            built = [self._build_strategy_instance(spec) for spec in strategy_specs]
            self.gateway.replace_strategies(built)
            self.strategy_specs = strategy_specs
            self._persist_runtime_state(extra={"event": "strategy_config_updated"})

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
                    max(0.0, (next_tick - datetime.now(ZoneInfo(self.config.timezone))).total_seconds()),
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
                next_run_in_seconds = round(max(0.0, (next_tick - datetime.now()).total_seconds()), 2)
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

    def _as_of_date(self, as_of_date: Optional[str] = None) -> str:
        return as_of_date or datetime.now().strftime("%Y-%m-%d")

    def _price_start_date(self, as_of_date: str) -> str:
        dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        return (dt - timedelta(days=self.config.price_lookback_days)).strftime("%Y-%m-%d")

    def _latest_prices_from_price(self, price: pd.DataFrame) -> pd.Series:
        if price.empty:
            return pd.Series(dtype=float)
        return price.sort_values(["symbol", "date"]).groupby("symbol")["close"].last()

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

    def _update_hold_market_value(self, latest_prices: pd.Series):
        if hasattr(self.gateway.oms, "update_position_market_value"):
            prices_dict = latest_prices.to_dict()
            self.gateway.oms.update_position_market_value(prices_dict)

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
                "config": self.config.model_dump(),
                "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
                "running": self._running,
                "last_error": self._last_error,
                "last_result": asdict(self._last_result) if self._last_result else None,
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

    def _serialize_result(self, result: Optional[TradingCycleResult]) -> Optional[TradingCycleResultResponse]:
        if result is None:
            return None
        return TradingCycleResultResponse(**asdict(result))

    def get_config_snapshot(self) -> Dict[str, Any]:
        return ServiceConfigResponse(
            session_id=self.config.session_id,
            service=self.config.model_dump(),
            selection_provider=self._normalize_jsonable(getattr(self.selection_provider, "config", {})),
            strategies=list(self.strategy_specs),
        ).model_dump()

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
                executed_buy_count=len(executed_buys),
                executed_sell_count=len(executed_sells),
                selected_symbols=top_selections,
                long_symbols=[] if long_candidates.empty else long_candidates["symbol"].tolist(),
                short_symbols=[] if short_candidates.empty else short_candidates["symbol"].tolist(),
            )
            self._last_result = result
            self._last_error = None
            self._persist_runtime_state(extra={"selection_metadata": selection_meta})
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


