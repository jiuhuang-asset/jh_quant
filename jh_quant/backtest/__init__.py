"""jh_backtest public exports."""

from .backtest import backtest, build_position, evaluate_strategies
from .metrics import cal_metrics_from_returns, calculate_returns, calculate_strategy_returns
from .risk_management import RiskManagementParams, risk_manage_single
from .strategy import Strategy

try:
    from .selectors import FactorSelector, SelectionResult, Selector
except ImportError:  # pragma: no cover - optional factor stack
    FactorSelector = None
    SelectionResult = None
    Selector = None

__all__ = [
    "build_position",
    "backtest",
    "evaluate_strategies",
    "Strategy",
    "RiskManagementParams",
    "risk_manage_single",
    "calculate_returns",
    "calculate_strategy_returns",
    "cal_metrics_from_returns",
    "FactorSelector",
    "SelectionResult",
    "Selector",
]
