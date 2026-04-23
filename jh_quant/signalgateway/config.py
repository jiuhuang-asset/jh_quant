from typing import  Dict, Literal, Optional
from pydantic import BaseModel, field_serializer, field_validator
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

from enum import Enum

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
    interval_seconds: int = 300
    price_lookback_days: int = 180
    max_candidates: int = 10
    auto_start: bool = False
    frequency: Frequency = Frequency.DAILY
    price_slippage: float = 0.0

    @field_validator("frequency", mode="before")
    @classmethod
    def _normalize_frequency(cls, value: Frequency | str) -> Frequency:
        return Frequency.from_value(value)

    @field_serializer("frequency")
    def _serialize_frequency(self, value: Frequency) -> str:
        return value.value
    


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
