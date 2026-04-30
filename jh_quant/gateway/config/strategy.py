from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import inspect
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, field_validator

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


def _params_to_plain_dict(params: Any) -> Dict[str, Any]:
    if params is None:
        return {}
    if isinstance(params, dict):
        return dict(params)
    if isinstance(params, BaseModel):
        return params.model_dump(exclude_none=False)
    if is_dataclass(params) and not isinstance(params, type):
        return asdict(params)
    raise TypeError(
        "strategy params must be a dict, pydantic BaseModel, dataclass instance, or None"
    )


def _validated_model_to_dict(model_cls: type, params: Dict[str, Any]) -> Dict[str, Any]:
    adapter = TypeAdapter(model_cls)
    value = adapter.validate_python(params)
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=False)
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


def _schema_from_model(model_cls: type) -> Dict[str, Any]:
    return TypeAdapter(model_cls).json_schema()


@dataclass
class TurtleStrategyConfig:
    """海龟策略参数。"""

    entry_window: int = 20
    exit_window: int = 10


@dataclass
class MovingAverageCrossoverStrategyConfig:
    """均线交叉策略参数。"""

    short_window: int = 50
    long_window: int = 200


@dataclass
class BuyAndHoldStrategyConfig:
    """买入并持有策略参数。"""


@dataclass
class VolumeTrendStrategyConfig:
    """量价趋势策略参数。"""

    ma_window: int = 20
    volume_window: int = 20
    volume_threshold: float = 1.2
    volume_trend_threshold: float = 0.1
    price_change_threshold: float = 0.02


@dataclass
class VolumeDivergenceStrategyConfig:
    """量价背离策略参数。"""

    rsi_window: int = 14
    volume_window: int = 20
    volume_trend_threshold: float = 0.05
    price_change_threshold: float = 0.02
    rsi_oversold: float = 30
    rsi_overbought: float = 70


@dataclass
class MeanReversionStrategyConfig:
    """均值回归策略参数。"""

    ma_window: int = 20
    deviation_threshold: float = 0.02
    rsi_window: int = 14
    rsi_oversold: int = 30
    rsi_overbought: int = 70


@dataclass
class RSIStrategyConfig:
    """RSI 策略参数。"""

    rsi_window: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70
    rsi_exit_oversold: float = 50
    rsi_exit_overbought: float = 50


@dataclass
class BollingerBandsStrategyConfig:
    """布林带策略参数。"""

    window: int = 20
    num_std: float = 2.0
    use_mean_reversion: bool = False


@dataclass
class MomentumStrategyConfig:
    """动量策略参数。"""

    momentum_window: int = 20
    momentum_threshold: float = 0.05
    ma_window: int = 60


@dataclass
class BreakoutStrategyConfig:
    """突破策略参数。"""

    lookback_period: int = 20
    atr_multiplier: float = 2.0
    use_atr_stop: bool = False


@dataclass
class DualThrustStrategyConfig:
    """Dual Thrust 策略参数。"""

    k1: float = 0.5
    k2: float = 0.5
    lookback_period: int = 20


STRATEGY_REGISTRY: Dict[str, type[Strategy]] = {
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

STRATEGY_CONFIG_MODELS: Dict[str, type] = {
    "turtle": TurtleStrategyConfig,
    "moving_average_crossover": MovingAverageCrossoverStrategyConfig,
    "buy_and_hold": BuyAndHoldStrategyConfig,
    "volume_trend": VolumeTrendStrategyConfig,
    "volume_divergence": VolumeDivergenceStrategyConfig,
    "mean_reversion": MeanReversionStrategyConfig,
    "rsi": RSIStrategyConfig,
    "bollinger_bands": BollingerBandsStrategyConfig,
    "momentum": MomentumStrategyConfig,
    "breakout": BreakoutStrategyConfig,
    "dual_thrust": DualThrustStrategyConfig,
}


def register_strategy(name: str, strategy_cls: type, config_model: Optional[type] = None) -> None:
    """注册策略实现及其可选参数模型。"""

    if not issubclass(strategy_cls, Strategy):
        raise TypeError(f"{strategy_cls} must inherit from Strategy")
    STRATEGY_REGISTRY[name] = strategy_cls
    if config_model is not None:
        STRATEGY_CONFIG_MODELS[name] = config_model


def get_strategy_config_model(name: str) -> Optional[type]:
    """获取某个策略注册名对应的参数模型类。"""

    return STRATEGY_CONFIG_MODELS.get(name)


class StrategySpec(BaseModel):
    """策略配置描述。

    用于声明启用哪一个策略、它的权重，以及对应的初始化参数。
    """

    name: str = Field(description="策略注册名，例如 `turtle` 或 `moving_average_crossover`。")
    weight: float = Field(default=1.0, description="策略权重，用于多策略组合时分配影响力。")
    params: Dict[str, Any] = Field(default_factory=dict, description="策略初始化参数字典，也支持传入 dataclass 或 Pydantic 配置对象。")
    alias: Optional[str] = Field(default=None, description="可选别名，便于区分多个同类策略实例。")

    @field_validator("params", mode="before")
    @classmethod
    def _normalize_params(cls, value: Any) -> Dict[str, Any]:
        return _params_to_plain_dict(value)


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


def validate_strategy_params(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unsupported strategy name: {name}")
    if name in STRATEGY_CONFIG_MODELS:
        return _validated_model_to_dict(STRATEGY_CONFIG_MODELS[name], params)
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
    if name in STRATEGY_CONFIG_MODELS:
        return _schema_from_model(STRATEGY_CONFIG_MODELS[name])
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
            "config_model": getattr(get_strategy_config_model(name), "__name__", None),
            "runtime_dependencies": [],
        }
        for name in STRATEGY_REGISTRY
    ]
