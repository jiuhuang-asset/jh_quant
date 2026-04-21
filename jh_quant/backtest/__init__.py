"""jh_backtest - 回测和选股引擎"""

from .backtest import build_position, backtest, evaluate_strategies
from .strategy import Strategy
from .risk_management import RiskManagementParams, risk_manage_single
from .metrics import calculate_returns, calculate_strategy_returns, cal_metrics_from_returns
from .selectors import JhSelector, FactorType

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
    "JhSelector"
]