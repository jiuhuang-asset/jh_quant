"""
Factor Exposure Module

Calculates individual stock factor exposures (betas).
This is separate from factor return calculation.
"""

from .calculator import StockExposureCalculator, calculate_stock_exposures

__all__ = [
    "StockExposureCalculator",
    "calculate_stock_exposures",
]
