from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import inspect
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, field_serializer, field_validator

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
from jh_quant.data import JHData

from .models import SelectionSnapshot

if TYPE_CHECKING:
    from jh_quant.backtest.selectors import FactorSelector
    from .market_data import MarketDataProvider


class Frequency(Enum):
    DAILY = "1d"
    MINUTE_1 = "1min"
    MINUTE_5 = "5min"
    MINUTE_15 = "15min"
    MINUTE_30 = "30min"
    MINUTE_60 = "60min"
    HOUR_1 = "1hour"

    @classmethod
    def from_value(cls, value: "Frequency | str | None") -> "Frequency":
        if isinstance(value, cls):
            return value

        mapping = {
            None: cls.DAILY,
            "daily": cls.DAILY,
            "day": cls.DAILY,
            "1day": cls.DAILY,
            "1d": cls.DAILY,
            "1min": cls.MINUTE_1,
            "1m": cls.MINUTE_1,
            "5min": cls.MINUTE_5,
            "5m": cls.MINUTE_5,
            "15min": cls.MINUTE_15,
            "15m": cls.MINUTE_15,
            "30min": cls.MINUTE_30,
            "30m": cls.MINUTE_30,
            "60min": cls.MINUTE_60,
            "60m": cls.MINUTE_60,
            "1hour": cls.HOUR_1,
            "1h": cls.HOUR_1,
        }
        normalized = mapping.get(str(value).lower() if value is not None else None)
        if normalized is None:
            raise ValueError(f"Unsupported frequency: {value}")
        return normalized


class ServiceConfig(BaseModel):
    session_id: Optional[str] = None
    mode: Literal["paper", "live"] = "paper"
    price_lookback_days: int = 180
    max_candidates: int = 10
    auto_start: bool = False
    frequency: Frequency = Frequency.DAILY
    price_slippage: float = 0.0
    interval_seconds: int = 300
    cron_expression: Optional[str] = None
    timezone: str = "Asia/Shanghai"

    @field_validator("frequency", mode="before")
    @classmethod
    def _normalize_frequency(cls, value: Frequency | str) -> Frequency:
        return Frequency.from_value(value)

    @field_serializer("frequency")
    def _serialize_frequency(self, value: Frequency) -> str:
        return value.value


STRATEGY_REGISTRY: Dict[str, Strategy] = {
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
    if not issubclass(strategy_cls, Strategy):
        raise TypeError(f"{strategy_cls} must inherit from Strategy")
    STRATEGY_REGISTRY[name] = strategy_cls


class StrategySpec(BaseModel):
    name: str
    weight: float = 1.0
    params: Dict[str, Any] = Field(default_factory=dict)
    alias: Optional[str] = None


@runtime_checkable
class SelectionProvider(Protocol):
    def select(self, as_of_date: str) -> SelectionSnapshot:
        raise NotImplementedError

    @property
    def config(self) -> Dict[str, Any]:
        return {}


class SelectionSpec(BaseModel):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    alias: Optional[str] = None


@dataclass
class FactorSelectionConfig:
    factor: str
    start: str
    top_n: int = 100
    bottom_n: int = 100
    factor_alpha: float = 0.10
    default_weight: float = 0.1
    period: str = "M"
    insignificant_weight_ratio: float = 0.5
    missing_data_threshold: float = 0.10
    test_window: int = 36
    verbose: bool = True


class FactorSelectionProviderAdptor(SelectionProvider):
    def __init__(self, jh_data: JHData, config: FactorSelectionConfig):
        from jh_quant.backtest.selectors import FactorSelector

        self.factor_selector: FactorSelector = FactorSelector(jh_data=jh_data)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return self.factor_selector.select(
            **asdict(self._config),
            end=as_of_date,
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


SELECTION_PROVIDER_REGISTRY: Dict[str, type] = {
    "factor_selector": FactorSelectionProviderAdptor,
}

SELECTION_PROVIDER_CONFIG_MODELS: Dict[str, type] = {
    "factor_selector": FactorSelectionConfig,
}

SELECTION_PROVIDER_RUNTIME_DEPENDENCIES: Dict[str, tuple[str, ...]] = {
    "factor_selector": ("jh_data",),
}


def _callable_param_model(target: Any, model_name: str, *, exclude: Optional[set[str]] = None):
    exclude = exclude or set()
    signature = inspect.signature(target)
    fields: Dict[str, tuple[Any, Any]] = {}
    for name, param in signature.parameters.items():
        if name in exclude or param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = Any if param.annotation is inspect.Signature.empty else param.annotation
        default = ... if param.default is inspect.Signature.empty else param.default
        fields[name] = (annotation, default)
    return create_model(model_name, __config__=ConfigDict(extra="forbid"), **fields)


def _validate_callable_params(
    target: Any,
    params: Dict[str, Any],
    model_name: str,
    *,
    exclude: Optional[set[str]] = None,
) -> Dict[str, Any]:
    model = _callable_param_model(target, model_name, exclude=exclude)
    return model.model_validate(params).model_dump(exclude_none=False)


def _schema_from_callable(
    target: Any,
    model_name: str,
    *,
    exclude: Optional[set[str]] = None,
) -> Dict[str, Any]:
    model = _callable_param_model(target, model_name, exclude=exclude)
    return model.model_json_schema()


def _validate_dataclass_params(model_cls: type, params: Dict[str, Any]) -> Dict[str, Any]:
    adapter = TypeAdapter(model_cls)
    value = adapter.validate_python(params)
    return asdict(value) if is_dataclass(value) else dict(value)


def _schema_from_dataclass(model_cls: type) -> Dict[str, Any]:
    return TypeAdapter(model_cls).json_schema()


def validate_strategy_params(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unsupported strategy name: {name}")
    strategy_cls = STRATEGY_REGISTRY[name]
    return _validate_callable_params(
        strategy_cls.__init__,
        params,
        f"{strategy_cls.__name__}Params",
        exclude={"self"},
    )


def normalize_strategy_spec(spec: StrategySpec) -> StrategySpec:
    return spec.model_copy(update={"params": validate_strategy_params(spec.name, spec.params)})


def get_strategy_params_schema(name: str) -> Dict[str, Any]:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unsupported strategy name: {name}")
    strategy_cls = STRATEGY_REGISTRY[name]
    return _schema_from_callable(
        strategy_cls.__init__,
        f"{strategy_cls.__name__}Params",
        exclude={"self"},
    )


def list_strategy_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "params_schema": get_strategy_params_schema(name),
            "runtime_dependencies": [],
        }
        for name in STRATEGY_REGISTRY
    ]


def _resolve_selection_runtime_kwargs(
    name: str,
    market_data_provider: Optional["MarketDataProvider"],
) -> Dict[str, Any]:
    if name == "factor_selector":
        jh_data = getattr(market_data_provider, "jhd", None)
        if jh_data is None:
            raise ValueError(
                "selection provider 'factor_selector' requires a market data provider with a 'jhd' attribute"
            )
        return {"jh_data": jh_data}
    return {}


def validate_selection_params(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if name not in SELECTION_PROVIDER_REGISTRY:
        raise ValueError(f"Unsupported selection provider name: {name}")
    if name in SELECTION_PROVIDER_CONFIG_MODELS:
        return _validate_dataclass_params(SELECTION_PROVIDER_CONFIG_MODELS[name], params)
    provider_cls = SELECTION_PROVIDER_REGISTRY[name]
    return _validate_callable_params(
        provider_cls.__init__,
        params,
        f"{provider_cls.__name__}Params",
        exclude={"self"},
    )


def normalize_selection_spec(spec: SelectionSpec) -> SelectionSpec:
    return spec.model_copy(update={"params": validate_selection_params(spec.name, spec.params)})


def get_selection_params_schema(name: str) -> Dict[str, Any]:
    if name not in SELECTION_PROVIDER_REGISTRY:
        raise ValueError(f"Unsupported selection provider name: {name}")
    if name in SELECTION_PROVIDER_CONFIG_MODELS:
        return _schema_from_dataclass(SELECTION_PROVIDER_CONFIG_MODELS[name])
    provider_cls = SELECTION_PROVIDER_REGISTRY[name]
    return _schema_from_callable(
        provider_cls.__init__,
        f"{provider_cls.__name__}Params",
        exclude={"self"},
    )


def list_selection_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "params_schema": get_selection_params_schema(name),
            "runtime_dependencies": list(SELECTION_PROVIDER_RUNTIME_DEPENDENCIES.get(name, ())),
        }
        for name in SELECTION_PROVIDER_REGISTRY
    ]


def build_selection_provider(spec: SelectionSpec, market_data_provider: Optional["MarketDataProvider"]) -> tuple[SelectionSpec, SelectionProvider]:
    normalized_spec = normalize_selection_spec(spec)
    provider_cls = SELECTION_PROVIDER_REGISTRY[normalized_spec.name]
    runtime_kwargs = _resolve_selection_runtime_kwargs(normalized_spec.name, market_data_provider)

    if normalized_spec.name in SELECTION_PROVIDER_CONFIG_MODELS:
        config_cls = SELECTION_PROVIDER_CONFIG_MODELS[normalized_spec.name]
        provider = provider_cls(
            config=config_cls(**normalized_spec.params),
            **runtime_kwargs,
        )
    else:
        provider = provider_cls(
            **normalized_spec.params,
            **runtime_kwargs,
        )

    return normalized_spec, provider


def register_selection_provider(name: str, provider_cls: type) -> None:
    if not inspect.isclass(provider_cls):
        raise TypeError(f"{provider_cls} must be a class")
    if not callable(getattr(provider_cls, "select", None)):
        raise TypeError(f"{provider_cls} must define a callable select method")
    SELECTION_PROVIDER_REGISTRY[name] = provider_cls


def create_selection_provider(spec: SelectionSpec, **init_kwargs) -> SelectionProvider:
    normalized_spec = normalize_selection_spec(spec)
    provider_cls = SELECTION_PROVIDER_REGISTRY[normalized_spec.name]
    if normalized_spec.name in SELECTION_PROVIDER_CONFIG_MODELS:
        config_cls = SELECTION_PROVIDER_CONFIG_MODELS[normalized_spec.name]
        return provider_cls(config=config_cls(**normalized_spec.params), **init_kwargs)
    return provider_cls(**normalized_spec.params, **init_kwargs)
