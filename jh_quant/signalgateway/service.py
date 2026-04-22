from __future__ import annotations

import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field

from jh_quant.backtest.strategy import (
    Strategy,
    StrategyBollingerBands,
    StrategyBreakout,
    StrategyBuyAndHold,
    StrategyDualThrust,
    StrategyMeanReversion,
    StrategyMomentum,
    StrategyMovingAverageCrossover,
    StrategyRSI,
    StrategyTurtle,
    StrategyVolumeDivergence,
    StrategyVolumeTrend,
)

from .market_data import JHMarketData
from .oms import OMS
from .signalgateway import SignalGateway


STRATEGY_REGISTRY: Dict[str, type] = {
    "turtle": StrategyTurtle,
    "moving_average_crossover": StrategyMovingAverageCrossover,
    "buy_and_hold": StrategyBuyAndHold,
    "volume_trend": StrategyVolumeTrend,
    "volume_divergence": StrategyVolumeDivergence,
    "mean_reversion": StrategyMeanReversion,
    "rsi": StrategyRSI,
    "bollinger_bands": StrategyBollingerBands,
    "momentum": StrategyMomentum,
    "breakout": StrategyBreakout,
    "dual_thrust": StrategyDualThrust,
}


def register_strategy(name: str, strategy_cls: type) -> None:
    """注册自定义策略到全局注册表

    用户实现的 Strategy 子类可通过此函数注册，
    注册后可在 StrategySpec 中通过 name 引用。

    Example:
        from jh_quant.backtest.strategy import Strategy

        class MyStrategy(Strategy):
            ...

        register_strategy("my_strategy", MyStrategy)

        # 然后在 StrategySpec 中使用:
        # StrategySpec(name="my_strategy", ...)
    """
    if not issubclass(strategy_cls, Strategy):
        raise TypeError(f"{strategy_cls} must inherit from Strategy")
    STRATEGY_REGISTRY[name] = strategy_cls


class StrategySpec(BaseModel):
    name: str
    weight: float = 1.0
    params: Dict[str, Any] = Field(default_factory=dict)
    alias: Optional[str] = None


class FixedUniverseSelectionConfig(BaseModel):
    """固定股票池选股配置"""
    mode: Literal["fixed"] = "fixed"
    symbols: List[str]


class DummySelectionConfig(BaseModel):
    """Dummy 选股配置 - 默认从预定义股票池随机/顺序选择"""
    mode: Literal["dummy"] = "dummy"
    symbols: List[str] = Field(default_factory=list)
    top_n: int = 100


SelectionConfig = FixedUniverseSelectionConfig | DummySelectionConfig


class ServiceConfig(BaseModel):
    session_id: Optional[str] = None
    mode: Literal["paper", "live"] = "paper"
    interval_seconds: int = 300
    price_lookback_days: int = 180
    max_candidates: int = 10
    auto_start: bool = False
    period: Literal["daily", "1min", "5min", "15min", "30min", "60min"] = "daily"
    price_slippage: float = 0.0


class LLMCommandRequest(BaseModel):
    command: str
    context: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class SelectionSnapshot:
    top_selections: List[str]
    bottom_selections: List[str] = field(default_factory=list)
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


class SelectionProvider:
    """选股提供者协议，支持自定义 Selector 实现"""

    def select(self, as_of_date: str) -> SelectionSnapshot:
        raise NotImplementedError


class FixedUniverseSelectionProvider(SelectionProvider):
    def __init__(self, config: FixedUniverseSelectionConfig):
        self.config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=self.config.symbols,
            metadata={"mode": self.config.mode, "as_of_date": as_of_date},
        )


class DummySelectionProvider(SelectionProvider):
    """默认 Dummy 选股提供者 - 直接返回配置的 symbols 或自动生成

    用户可以通过 FixedUniverseSelectionConfig 指定股票池，
    也可以注入自定义 SelectionProvider 实现自己的选股逻辑。
    """

    def __init__(self, config: DummySelectionConfig):
        self.config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        symbols = self.config.symbols
        if not symbols:
            symbols = [f"DUMMY{i:04d}" for i in range(1, self.config.top_n + 1)]
        else:
            symbols = symbols[:self.config.top_n]
        return SelectionSnapshot(
            top_selections=symbols,
            metadata={"mode": self.config.mode, "as_of_date": as_of_date, "count": len(symbols)},
        )


def build_selection_provider(config: SelectionConfig) -> SelectionProvider:
    if config.mode == "fixed":
        return FixedUniverseSelectionProvider(config)
    return DummySelectionProvider(config)


class SignalGatewayService:
    def __init__(
        self,
        gateway: SignalGateway,
        config: ServiceConfig,
        selection_provider: SelectionProvider,
        strategy_specs: List[StrategySpec],
        llm_handler: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.gateway = gateway
        self.config = config
        self.selection_provider = selection_provider
        self.strategy_specs = strategy_specs
        self.llm_handler = llm_handler

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

        self.configure_strategies(strategy_specs)

        # Restore OMS state from recorder on startup
        self._restore_oms_state()

        if self.config.auto_start:
            self.start()

    def _restore_oms_state(self):
        """从 recorder 恢复 OMS 状态（如果有）"""
        recorder = getattr(self.gateway.oms, "recorder", None)
        if recorder is None:
            return
        if not hasattr(recorder, "load_latest_session_state"):
            return
        try:
            saved = recorder.load_latest_session_state(self.config.session_id)
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

    def configure_selection(self, config: SelectionConfig):
        """动态更换选股提供者"""
        with self._lock:
            self.selection_provider = build_selection_provider(config)
            self._persist_runtime_state(extra={"event": "selection_config_updated", "mode": config.mode})

    def _as_of_date(self, as_of_date: Optional[str] = None) -> str:
        return as_of_date or datetime.now().strftime("%Y-%m-%d")

    def _price_start_date(self, as_of_date: str) -> str:
        dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        return (dt - timedelta(days=self.config.price_lookback_days)).strftime("%Y-%m-%d")

    def _frequency_for_period(self) -> str:
        """根据 period 返回 MarketDataProvider 的 frequency 参数"""
        mapping = {
            "daily": "1d",
            "1min": "1m",
            "5min": "5m",
            "15min": "15m",
            "30min": "30m",
            "60min": "60m",
        }
        return mapping.get(self.config.period, "1d")

    def _latest_prices_from_price(self, price: pd.DataFrame) -> pd.Series:
        if price.empty:
            return pd.Series(dtype=float)
        return (
            price.sort_values(["symbol", "date"])
            .groupby("symbol")["close"]
            .last()
        )

    def _update_hold_market_value(self, latest_prices: pd.Series):
        if hasattr(self.gateway.oms, "update_position_market_value"):
            self.gateway.oms.update_position_market_value(latest_prices.to_dict())

    def _apply_slippage(self, price: float, trade_type: str) -> float:
        """应用价格滑点"""
        if self.config.price_slippage <= 0:
            return price
        if trade_type == "BUY":
            return price * (1 + self.config.price_slippage)
        else:
            return price * (1 - self.config.price_slippage)

    def _persist_runtime_state(self, extra: Optional[Dict[str, Any]] = None):
        recorder = getattr(self.gateway.oms, "recorder", None)
        if recorder is None or not hasattr(recorder, "save_service_state"):
            return
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
        recorder.save_service_state(payload)

    def get_status(self) -> Dict[str, Any]:
        return {
            "session_id": self.config.session_id,
            "mode": self.config.mode,
            "running": self._running,
            "interval_seconds": self.config.interval_seconds,
            "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
            "last_error": self._last_error,
            "last_result": asdict(self._last_result) if self._last_result else None,
        }

    def run_once(self, as_of_date: Optional[str] = None) -> TradingCycleResult:
        with self._lock:
            cycle_date = self._as_of_date(as_of_date)
            price_start = self._price_start_date(cycle_date)

            selection = self.selection_provider.select(as_of_date=cycle_date)
            top_selections = selection.top_selections
            bottom_selections = getattr(selection, "bottom_selections", [])
            # 动态生成 metadata（用户自定义 Provider 可能没有此属性）
            if hasattr(selection, "metadata") and selection.metadata:
                selection_meta = selection.metadata
            else:
                selection_meta = {"as_of_date": cycle_date}
                # 将 selection 对象上除已知字段外的所有属性都加入 metadata
                known = {"top_selections", "bottom_selections", "metadata"}
                for k in dir(selection):
                    if not k.startswith("_") and k not in known:
                        v = getattr(selection, k, None)
                        if not callable(v):
                            selection_meta[k] = v

            if isinstance(self.gateway.market_data_provider, JHMarketData):
                self.gateway.market_data_provider.default_symbols = top_selections

            price = self.gateway.get_price_data(
                symbols=top_selections or None,
                start_date=price_start,
                end_date=cycle_date,
            )

            latest_prices = self._latest_prices_from_price(price)
            if not latest_prices.empty:
                self._update_hold_market_value(latest_prices)

            short_candidates = self.gateway.get_short_candidates(
                start_date=price_start,
                end_date=cycle_date,
                price=price,
            )
            executed_sells = []
            if not short_candidates.empty:
                executed_sells = self.gateway.execute_short(short_candidates, latest_prices, self.config.price_slippage)

            long_candidates = self.gateway.get_long_candidates(
                start_date=price_start,
                end_date=cycle_date,
                max_candidates=self.config.max_candidates,
                price=price,
            )
            executed_buys = []
            if not long_candidates.empty:
                executed_buys = self.gateway.execute_long(long_candidates, latest_prices, self.config.price_slippage)

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

    def _loop(self):
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
                    pass  # swallow to avoid nested exception corruption
            try:
                self._stop_event.wait(self.config.interval_seconds)
            except BaseException:
                break  # exit gracefully on shutdown or other base exceptions

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._loop, daemon=False)
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
