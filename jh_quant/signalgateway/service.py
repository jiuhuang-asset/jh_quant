from __future__ import annotations

import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field

from jh_quant.backtest import JhSelector
from jh_quant.backtest.selectors import FactorSelectionResult
from jh_quant.backtest.strategy import (
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
from jh_quant.data import JHData
from jh_quant.factors import FactorType

from .market_data import JHMarketData
from .oms import OMS
from .signalgateway import SignalGateway


STRATEGY_REGISTRY = {
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


class StrategySpec(BaseModel):
    name: str
    weight: float = 1.0
    params: Dict[str, Any] = Field(default_factory=dict)
    alias: Optional[str] = None


class FixedUniverseSelectionConfig(BaseModel):
    mode: Literal["fixed"] = "fixed"
    symbols: List[str]


class FactorSelectionConfig(BaseModel):
    mode: Literal["factor"] = "factor"
    factor: str
    start: str
    end: Optional[str] = None
    top_n: int = 50
    bottom_n: int = 0
    factor_alpha: float = 0.10
    default_weight: float = 0.1
    period: str = "M"
    insignificant_weight_ratio: float = 0.5
    missing_data_threshold: float = 0.10
    test_window: Optional[int] = 36
    verbose: bool = False


SelectionConfig = FixedUniverseSelectionConfig | FactorSelectionConfig


class ServiceConfig(BaseModel):
    session_id: str
    mode: Literal["paper", "live"] = "paper"
    interval_seconds: int = 300
    price_lookback_days: int = 180
    max_candidates: int = 10
    auto_start: bool = False


class LLMCommandRequest(BaseModel):
    command: str
    context: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class SelectionSnapshot:
    symbols: List[str]
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
    def select(self, as_of_date: str) -> SelectionSnapshot:
        raise NotImplementedError


class FixedUniverseSelectionProvider(SelectionProvider):
    def __init__(self, config: FixedUniverseSelectionConfig):
        self.config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            symbols=self.config.symbols,
            metadata={"mode": self.config.mode, "as_of_date": as_of_date},
        )


class FactorSelectionProvider(SelectionProvider):
    def __init__(self, jhd: JHData, config: FactorSelectionConfig):
        self.jhd = jhd
        self.config = config
        self.selector = JhSelector(jhd)

    def _resolve_factor(self) -> FactorType:
        for factor in FactorType:
            if factor.name == self.config.factor or factor.value == self.config.factor:
                return factor
        raise ValueError(f"Unknown factor: {self.config.factor}")

    def select(self, as_of_date: str) -> SelectionSnapshot:
        factor = self._resolve_factor()
        result: FactorSelectionResult = self.selector.select_by_factor(
            factor=factor,
            start=self.config.start,
            end=self.config.end or as_of_date,
            top_n=self.config.top_n,
            bottom_n=self.config.bottom_n,
            factor_alpha=self.config.factor_alpha,
            default_weight=self.config.default_weight,
            period=self.config.period,
            insignificant_weight_ratio=self.config.insignificant_weight_ratio,
            missing_data_threshold=self.config.missing_data_threshold,
            test_window=self.config.test_window,
            verbose=self.config.verbose,
        )
        return SelectionSnapshot(
            symbols=result.top_stocks,
            metadata={
                "mode": self.config.mode,
                "factor": self.config.factor,
                "weights": result.weights,
                "top_scores": result.top_scores,
                "bottom_scores": result.bottom_scores,
            },
        )


def build_selection_provider(jhd: JHData, config: SelectionConfig) -> SelectionProvider:
    if config.mode == "fixed":
        return FixedUniverseSelectionProvider(config)
    return FactorSelectionProvider(jhd, config)


class SignalGatewayService:
    def __init__(
        self,
        gateway: SignalGateway,
        jhd: JHData,
        config: ServiceConfig,
        selection_config: SelectionConfig,
        strategy_specs: List[StrategySpec],
        llm_handler: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.gateway = gateway
        self.jhd = jhd
        self.config = config
        self.selection_config = selection_config
        self.strategy_specs = strategy_specs
        self.selection_provider = build_selection_provider(jhd, selection_config)
        self.llm_handler = llm_handler

        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._running = False
        self._last_result: Optional[TradingCycleResult] = None
        self._last_error: Optional[str] = None

        self.configure_strategies(strategy_specs)
        if self.config.auto_start:
            self.start()

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

    def configure_selection(self, selection_config: SelectionConfig):
        with self._lock:
            self.selection_config = selection_config
            self.selection_provider = build_selection_provider(self.jhd, selection_config)
            self._persist_runtime_state(extra={"event": "selection_config_updated"})

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

    def _update_hold_market_value(self, latest_prices: pd.Series):
        if hasattr(self.gateway.oms, "update_position_market_value"):
            self.gateway.oms.update_position_market_value(latest_prices.to_dict())

    def _persist_runtime_state(self, extra: Optional[Dict[str, Any]] = None):
        recorder = getattr(self.gateway.oms, "recorder", None)
        if recorder is None or not hasattr(recorder, "save_session_state"):
            return
        payload = {
            "session_id": self.config.session_id,
            "export_time": datetime.now().isoformat(),
            "service": {
                "config": self.config.model_dump(),
                "selection_config": self.selection_config.model_dump(),
                "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
                "running": self._running,
                "last_error": self._last_error,
                "last_result": asdict(self._last_result) if self._last_result else None,
            },
        }
        if extra:
            payload["service"]["extra"] = extra
        recorder.save_session_state(payload)

    def get_status(self) -> Dict[str, Any]:
        return {
            "session_id": self.config.session_id,
            "mode": self.config.mode,
            "running": self._running,
            "interval_seconds": self.config.interval_seconds,
            "selection_config": self.selection_config.model_dump(),
            "strategy_specs": [spec.model_dump() for spec in self.strategy_specs],
            "last_error": self._last_error,
            "last_result": asdict(self._last_result) if self._last_result else None,
        }

    def run_once(self, as_of_date: Optional[str] = None) -> TradingCycleResult:
        with self._lock:
            cycle_date = self._as_of_date(as_of_date)
            price_start = self._price_start_date(cycle_date)

            selection = self.selection_provider.select(cycle_date)
            symbols = selection.symbols

            if isinstance(self.gateway.market_data_provider, JHMarketData):
                self.gateway.market_data_provider.default_symbols = symbols

            price = self.gateway.get_price_data(
                symbols=symbols or None,
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
                executed_sells = self.gateway.execute_short(short_candidates, latest_prices)

            long_candidates = self.gateway.get_long_candidates(
                start_date=price_start,
                end_date=cycle_date,
                max_candidates=self.config.max_candidates,
                price=price,
            )
            executed_buys = []
            if not long_candidates.empty:
                executed_buys = self.gateway.execute_long(long_candidates, latest_prices)

            result = TradingCycleResult(
                session_id=self.config.session_id,
                mode=self.config.mode,
                cycle_time=datetime.now().isoformat(),
                selection_count=len(symbols),
                long_candidate_count=len(long_candidates),
                short_candidate_count=len(short_candidates),
                executed_buy_count=len(executed_buys),
                executed_sell_count=len(executed_sells),
                selected_symbols=symbols,
                long_symbols=[]
                if long_candidates.empty
                else long_candidates["symbol"].tolist(),
                short_symbols=[]
                if short_candidates.empty
                else short_candidates["symbol"].tolist(),
            )
            self._last_result = result
            self._last_error = None
            self._persist_runtime_state(extra={"selection_metadata": selection.metadata})
            return result

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:  # pragma: no cover - runtime service path
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
                self._persist_runtime_state(extra={"event": "cycle_error"})
            self._stop_event.wait(self.config.interval_seconds)

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._loop, daemon=True)
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
