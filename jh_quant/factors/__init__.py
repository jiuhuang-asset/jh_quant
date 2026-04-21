"""
Jiuhuang Factor Calculation Framework
"""

from .main import FactorEngine, calculate_exposures, calculate_factor_returns

# 导出因子验证
from .validators import (
    validate_factor_intercept,
    validate_factor,
    FamaMacBethValidator,
    InterceptValidationResult,
    FamaMacBethValidationResult,
)
from .config import FactorType, CalculationMethod, TimePeriod, FACTOR_CONFIGS

__all__ = [
    # 配置
    "FACTOR_CONFIGS",
    "FactorType",
    "CalculationMethod",
    "TimePeriod",
    # 数据准备类
    "FactorReturnData",
    "FF3Data",
    "FF5Data",
    "CARHARTData",
    "NOVY_MARXData",
    "HOU_XUE_ZHANGData",
    "DHSData",
    "CAPMData",
    "get_factor_data_class",
    # 因子计算
    "GeneralFactorCalculator",
    "calculate_factor_returns",
    # 暴露计算
    "StockExposureCalculator",
    "calculate_stock_exposures",
    # 主入口
    "FactorEngine",
    "calculate_exposures",
    # 因子验证
    "validate_factor_intercept",
    "validate_factor",
    "FamaMacBethValidator",
    "InterceptValidationResult",
    "FamaMacBethValidationResult",
]
