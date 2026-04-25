from enum import Enum
from typing import Any, Dict, Literal, Optional, runtime_checkable, Protocol
from pydantic import BaseModel, Field, field_serializer, field_validator
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
from jh_quant.backtest.selectors import FactorSelector,FactorType
from jh_quant.data import JHData
from .models import SelectionSnapshot


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
    # Cron 调度配置
    cron_expression: Optional[str] = None  # e.g. "0 9 * * 1-5" (工作日 9:00)
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




@runtime_checkable
class SelectionProvider(Protocol):
    def select(self, as_of_date: str) -> "SelectionSnapshot":
        raise NotImplementedError("SelectionProvider subclasses must implement the select method")

    @property
    def config(self) -> Dict[str, Any]:
        return {}


class SelectionSpec(BaseModel):
    """Specification for creating a SelectionProvider instance."""
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    alias: Optional[str] = None


from dataclasses import dataclass

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
        self.factor_selector = FactorSelector(jh_data=jh_data)
        self.config = config

    def select(self, as_of_date: str) -> "SelectionSnapshot":
        return self.factor_selector.select(
            **self.config,
            end=as_of_date,
        )

    @property
    def config(self) -> Dict[str, Any]:
        return self.config



SELECTION_PROVIDER_REGISTRY: Dict[str, type] = {
     "factor_selector": FactorSelectionProviderAdptor,
}


def register_selection_provider(name: str, provider_cls: type) -> None:
    """注册自定义 SelectionProvider 到全局注册表

    用户实现的 SelectionProvider 子类可通过此函数注册，
    注册后可在 SelectionSpec 中通过 name 引用。
    """
    if not issubclass(provider_cls, SelectionProvider):
        raise TypeError(f"{provider_cls} must inherit from SelectionProvider")
    SELECTION_PROVIDER_REGISTRY[name] = provider_cls


def create_selection_provider(spec: SelectionSpec, **init_kwargs) -> SelectionProvider:
    """根据 SelectionSpec 创建 SelectionProvider 实例"""
    if spec.name not in SELECTION_PROVIDER_REGISTRY:
        raise ValueError(f"Unsupported selection provider name: {spec.name}")
    provider_cls = SELECTION_PROVIDER_REGISTRY[spec.name]
    return provider_cls(**spec.params, **init_kwargs)