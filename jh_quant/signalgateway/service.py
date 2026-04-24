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


class TradingCycleResultResponse(BaseModel):
    session_id: str = Field(description="当前交易会话 ID")
    mode: str = Field(description="服务运行模式，例如 paper 或 live")
    cycle_time: str = Field(description="本次交易周期执行完成时间")
    selection_count: int = Field(description="本次选股结果中的证券数量")
    long_candidate_count: int = Field(description="本次识别出的做多候选数量")
    short_candidate_count: int = Field(description="本次识别出的做空或卖出候选数量")
    executed_buy_count: int = Field(description="本次实际执行的买单数量")
    executed_sell_count: int = Field(description="本次实际执行的卖单数量")
    selected_symbols: List[str] = Field(default_factory=list, description="本次选中的证券代码列表")
    long_symbols: List[str] = Field(default_factory=list, description="本次做多候选证券代码列表")
    short_symbols: List[str] = Field(default_factory=list, description="本次做空或卖出候选证券代码列表")
    status: str = Field(default="success", description="本次交易周期执行状态，如 success 或 error")
    error: Optional[str] = Field(default=None, description="执行失败时的错误信息或堆栈摘要")


class ServiceStatusResponse(BaseModel):
    session_id: str = Field(description="当前服务对应的交易会话 ID")
    mode: str = Field(description="服务运行模式，例如 paper 或 live")
    running: bool = Field(description="调度器当前是否处于运行状态")
    scheduler: SchedulerStatus = Field(description="调度配置与调度状态摘要")
    last_error: Optional[str] = Field(default=None, description="最近一次运行错误信息，没有错误时为空")
    last_result: Optional[TradingCycleResultResponse] = Field(
        default=None,
        description="最近一次交易周期执行结果，没有执行记录时为空",
    )


class RuntimeSnapshotResponse(BaseModel):
    session_id: str = Field(description="当前运行态所属的交易会话 ID")
    generated_at: str = Field(description="运行态快照生成时间")
    positions: Dict[str, Any] = Field(description="当前持仓与挂单等运行态头寸信息")
    oms_state: Optional[Dict[str, Any]] = Field(default=None, description="OMS 导出的完整内部状态快照")


class PerformanceSnapshotResponse(BaseModel):
    session_id: str = Field(description="当前绩效快照所属的交易会话 ID")
    generated_at: str = Field(description="绩效快照生成时间")
    summary: Dict[str, Any] = Field(description="绩效汇总指标，如收益、回撤、胜率等")
    holding_returns: List[Dict[str, Any]] = Field(default_factory=list, description="最新持仓收益明细列表")
    turnover: List[Dict[str, Any]] = Field(default_factory=list, description="按日统计的换手率与成交金额明细")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="按日统计的权益曲线明细")
    trade_activity: List[Dict[str, Any]] = Field(default_factory=list, description="按日统计的交易活跃度明细")
    position_exposure: Dict[str, Any] = Field(default_factory=dict, description="仓位暴露与集中度分析结果")
    latest_portfolio: Dict[str, Any] = Field(default_factory=dict, description="组合最新资产快照")


class ServiceConfigResponse(BaseModel):
    session_id: str = Field(description="当前配置所属的交易会话 ID")
    service: Dict[str, Any] = Field(description="服务级配置，如模式、调度、频率、候选数等")
    selection_provider: Dict[str, Any] = Field(default_factory=dict, description="选股器或信号提供器配置")
    strategies: List[StrategySpec] = Field(default_factory=list, description="当前启用的策略配置列表")


class AnalyticsSnapshotResponse(BaseModel):
    session_id: str = Field(description="当前分析快照所属的交易会话 ID")
    generated_at: str = Field(description="分析快照生成时间")
    status: ServiceStatusResponse = Field(description="服务状态摘要")
    runtime: RuntimeSnapshotResponse = Field(description="运行态快照")
    performance: PerformanceSnapshotResponse = Field(description="绩效分析快照")
    config: ServiceConfigResponse = Field(description="服务与策略配置快照")


class ServiceActionResponse(BaseModel):
    status: str = Field(description="服务动作执行结果，例如 started 或 stopped")
    session_id: Optional[str] = Field(default=None, description="服务动作关联的交易会话 ID")


class StrategyConfigUpdateResponse(BaseModel):
    status: str = Field(description="策略配置更新结果")
    count: int = Field(description="本次生效的策略配置数量")


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
            scheduler=SchedulerStatus(
                interval_seconds=self.config.interval_seconds,
                cron_expression=self.config.cron_expression,
                timezone=self.config.timezone,
            ),
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

    def handle_llm_command(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        if self.llm_handler is None:
            response = {
                "status": "placeholder",
                "message": "No LLM handler is configured yet.",
                "command": command,
                "context": context,
            }
        else:
            response = self.llm_handler(command, context)
        self._persist_runtime_state(
            extra={"event": "llm_command", "command": command, "llm_response": response}
        )
        return response
