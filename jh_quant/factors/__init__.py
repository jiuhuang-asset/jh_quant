"""Jiuhuang factor calculation framework."""

from .config import FACTOR_CONFIGS, CalculationMethod, FactorType, TimePeriod
from .exposure import StockExposureCalculator, calculate_stock_exposures
from .factors import GeneralFactorCalculator
from .loaders import load_ts_factor_inputs
from .main import FactorEngine, calculate_exposures, calculate_factor_returns
from .validators import (
    FamaMacBethValidationResult,
    FamaMacBethValidator,
    InterceptValidationResult,
    validate_factor,
    validate_factor_intercept,
)

__all__ = [
    "FACTOR_CONFIGS",
    "FactorType",
    "CalculationMethod",
    "TimePeriod",
    "GeneralFactorCalculator",
    "calculate_factor_returns",
    "StockExposureCalculator",
    "calculate_stock_exposures",
    "FactorEngine",
    "calculate_exposures",
    "load_ts_factor_inputs",
    "validate_factor_intercept",
    "validate_factor",
    "FamaMacBethValidator",
    "InterceptValidationResult",
    "FamaMacBethValidationResult",
]
