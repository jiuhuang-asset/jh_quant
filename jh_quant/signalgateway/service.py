from __future__ import annotations
import traceback
import uuid
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Optional
import pandas as pd
from pydantic import BaseModel, Field
from typing import Protocol, runtime_checkable

from .config import ServiceConfig, STRATEGY_REGISTRY
from .persistence_coordinator import PersistenceCoordinator
from .signalgateway import SignalGateway


class CronScheduler:
    """
    跨平台 cron 调度器，使用 croniter 实现。

    支持标准 5 字段 cron 表达式，自动处理时区。
    """

    def __init__(self, cron_expression: str, timezone: str = "Asia/Shanghai"):
        from croniter import croniter
        self.cron_expr = cron_expression
        self.timezone = timezone
        self._iter = croniter(cron_expression, time.time(), tz=timezone)

    def get_next_timeout(self) -> float:
        """返回距离下次执行的秒数（timeout）"""
        next_tick = self._iter.get_next(time.time)
        return max(0.0, next_tick - time.time())

    def wait(self, stop_event: Event) -> bool:
        """
        阻塞等待直到下次执行时间或 stop_event 被设置。

        Returns:
            True if next execution time was reached, False if stopped early.
        """
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
    """选股提供者协议，支持自定义 Selector 实现"""

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

        # Keep service session_id aligned with OMS when callers omit one side.
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

        # Restore OMS state from persistence on startup
        self._restore_oms_state()

        self.configure_strategies(strategy_specs)

        if self.config.auto_start:
            self.start()

    def _restore_oms_state(self):
        """从 recorder 恢复 OMS 状态（如果有）"""
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
        return (
            price.sort_values(["symbol", "date"])
            .groupby("symbol")["close"]
            .last()
        )

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
        """应用价格滑点"""
        if self.config.price_slippage <= 0:
            return price
        if trade_type == "BUY":
            return price * (1 + self.config.price_slippage)
        else:
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

    def get_status(self) -> Dict[str, Any]:
        return {
            "session_id": self.config.session_id,
            "mode": self.config.mode,
            "running": self._running,
            "interval_seconds": self.config.interval_seconds,
            "cron_expression": self.config.cron_expression,
            "timezone": self.config.timezone,
            "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
            "last_error": self._last_error,
            "last_result": asdict(self._last_result) if self._last_result else None,
        }

    def get_performance_snapshot(self) -> Dict[str, Any]:
        report = self.persistence.get_performance_report(self.config.session_id)
        return {
            "session_id": self.config.session_id,
            "summary": report["summary"],
            "holding_returns": self._records_from_frame(report["holding_returns"]),
            "turnover": self._records_from_frame(report["turnover"]),
            "equity_curve": self._records_from_frame(report["equity_curve"]),
            "trade_activity": self._records_from_frame(report["trade_activity"]),
            "position_exposure": self._normalize_jsonable(report["position_exposure"]),
            "latest_portfolio": self._normalize_jsonable(report["latest_portfolio"]),
        }

    def get_analysis_snapshot(self) -> Dict[str, Any]:
        positions = self.gateway.oms.get_positions()
        snapshot = {
            "session_id": self.config.session_id,
            "generated_at": datetime.now().isoformat(),
            "status": self.get_status(),
            "positions": positions.model_dump(),
            "performance": self.get_performance_snapshot(),
            "selection_provider": self._normalize_jsonable(getattr(self.selection_provider, "config", {})),
            "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
        }
        if hasattr(self.gateway.oms, "export_state"):
            snapshot["oms_state"] = self._normalize_jsonable(self.gateway.oms.export_state())
        return snapshot

    def get_runtime_snapshot(self) -> Dict[str, Any]:
        positions = self.gateway.oms.get_positions()
        runtime = {
            "status": self.get_status(),
            "positions": positions.model_dump(),
            "performance": self.get_performance_snapshot(),
        }

        if hasattr(self.gateway.oms, "export_state"):
            runtime["oms_state"] = self.gateway.oms.export_state()
        return runtime

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
                for k in dir(selection):
                    if not k.startswith("_") and k not in known:
                        v = getattr(selection, k, None)
                        if not callable(v):
                            selection_meta[k] = v

            executed_buys, executed_sells, long_candidates, short_candidates = (
                self.gateway.execute_cycle(
                    top_selections=top_selections,
                    price_start=price_start,
                    cycle_date=cycle_date,
                    frequency=self.config.frequency,
                    max_candidates=self.config.max_candidates,
                    price_slippage=self.config.price_slippage,
                )
            )

            self._persist_trades(executed_sells)
            self._persist_trades(executed_buys)

            # Compute and persist daily metrics (service layer responsibility)
            if hasattr(self.gateway.oms, "compute_daily_metrics"):
                cycle_dt = datetime.strptime(cycle_date, "%Y-%m-%d")
                latest_prices = (
                    self.gateway.get_latest_prices(top_selections)
                    if hasattr(self.gateway, "get_latest_prices")
                    else pd.Series(dtype=float)
                )
                close_prices = latest_prices.to_dict() if not latest_prices.empty else None
                perf, snapshots = self.gateway.oms.compute_daily_metrics(
                    trade_date=cycle_dt, close_prices=close_prices
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
                long_symbols=[]
                if long_candidates.empty
                else long_candidates["symbol"].tolist(),
                short_symbols=[]
                if short_candidates.empty
                else short_candidates["symbol"].tolist(),
            )
            self._last_result = result
            self._last_error = None
            self._persist_runtime_state(extra={"selection_metadata": selection_meta})
            return result

    def _run_scheduler(self):
        """基于 cron 或 interval 的调度循环"""
        use_cron = bool(self.config.cron_expression)
        scheduler: Optional[CronScheduler] = None
        if use_cron:
            scheduler = CronScheduler(
                self.config.cron_expression,
                self.config.timezone,
            )

        while not self._stop_event.is_set():
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
            if use_cron and scheduler is not None:
                scheduler.wait(self._stop_event)
            else:
                try:
                    self._stop_event.wait(self.config.interval_seconds)
                except BaseException:
                    break

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run_scheduler, daemon=False)
        self._thread.start()
        self._running = True
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
