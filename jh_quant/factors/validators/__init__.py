"""
因子有效性验证模块

提供两种验证方法:
1. 截距项验证 (Intercept Validation): 单样本t检验/截距回归检验因子收益是否显著
2. Fama-MacBeth两步验证 (Fama-MacBeth Two-Step): 横截面+时序两步检验因子风险溢价

参考:
- Fama-MacBeth (1973): Risk, Return, and Equilibrium
"""

from .validation import (
    # Data classes
    FactorTestResult,
    InterceptValidationResult,
    FMFactorTestResult,
    FamaMacBethValidationResult,
    # Functions
    validate_factor_intercept,
    validate_factor,
    # Classes
    FamaMacBethValidator,
)

__all__ = [
    # Data classes
    "FactorTestResult",
    "InterceptValidationResult",
    "FMFactorTestResult",
    "FamaMacBethValidationResult",
    # Functions
    "validate_factor_intercept",
    "validate_factor",
    # Classes
    "FamaMacBethValidator",
]
