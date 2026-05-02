"""jh_backtest public exports."""

from .backtest import backtest, build_position, evaluate_strategies
from .metrics import (
    cal_metrics_from_returns,
    calculate_returns,
    calculate_strategy_returns,
)
from .rules import (
    ATRTrailingStopRule,
    MaxConsecutiveFallingBarsRule,
    MaxConsecutiveRisingBarsRule,
    MaxHoldingBarsRule,
    PositionState,
    RiskRule,
    StopLossRule,
    TakeProfitRule,
    TrailingStopRule,
    apply_rules,
    maybe_compute_atr,
)
from .strategy import Strategy

try:
    from .selectors import FactorSelector, SelectionResult, Selector
except ImportError:  # pragma: no cover - optional factor stack
    FactorSelector = None
    SelectionResult = None
    Selector = None

__all__ = [
    "ATRTrailingStopRule",
    "backtest",
    "build_position",
    "cal_metrics_from_returns",
    "calculate_returns",
    "calculate_strategy_returns",
    "evaluate_strategies",
    "FactorSelector",
    "MaxConsecutiveFallingBarsRule",
    "MaxConsecutiveRisingBarsRule",
    "MaxHoldingBarsRule",
    "maybe_compute_atr",
    "PositionState",
    "RiskRule",
    "SelectionResult",
    "Selector",
    "StopLossRule",
    "Strategy",
    "TakeProfitRule",
    "TrailingStopRule",
    "apply_rules",
]
