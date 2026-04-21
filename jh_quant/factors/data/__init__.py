"""
Data Access Module
"""

from .base import (
    # 抽象基类
    FactorReturnData,
    # 具体数据准备类
    FF3Data,
    FF5Data,
    CARHARTData,
    NOVY_MARXData,
    HOU_XUE_ZHANGData,
    DHSData,
    CAPMData,
    # 注册表
    get_factor_data_class,
    DATA_CLASS_REGISTRY,
)
from .transform import (
    daily_to_monthly,
    calculate_returns,
    calculate_log_returns,
)

__all__ = [
    # 抽象基类
    "FactorReturnData",
    # 具体数据准备类
    "FF3Data",
    "FF5Data",
    "CARHARTData",
    "NOVY_MARXData",
    "HOU_XUE_ZHANGData",
    "DHSData",
    "CAPMData",
    # 注册表
    "get_factor_data_class",
    "DATA_CLASS_REGISTRY",
    # 数据转换
    "daily_to_monthly",
    "calculate_returns",
    "calculate_log_returns",
]
