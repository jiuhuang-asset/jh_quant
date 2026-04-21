"""
Factor Returns Calculation Module

Calculates factor returns for various factor models.
Uses independent sorting methodology similar to Fama-French.

设计原则：依赖抽象接口（DataSource），不依赖具体实现

支持的因子模型:
- FF3: Fama-French三因子
- FF5: Fama-French五因子
- CARHART: Carhart四因子
- NOVY_MARX: Novy-Marx四因子
- HOU_XUE_ZHANG: Hou-Xue-Zhang四因子
- DHS: Daniel-Hirshleifer-Sun三因子
"""

from .general import GeneralFactorCalculator

__all__ = [
    "GeneralFactorCalculator",
]
