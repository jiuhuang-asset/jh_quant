"""
Configuration and Enums for Factor Calculation Framework

Defines factor model types, calculation methods, and time periods.
"""

import os
from enum import Enum
from typing import List, Dict, Optional


class FactorType(Enum):
    """
    Factor model types supported by the framework.

    Each factor type represents a different multi-factor model:
    - FF3: Fama-French Three Factor Model (MKT, SMB, HML)
    - FF5: Fama-French Five Factor Model (MKT, SMB, HML, RMW, CMA)
    - CARHART: Carhart Four Factor Model (MKT, SMB, HML, UMD)
    - NOVY_MARX: Novy-Marx Four Factor Model (MKT, HML_ADJ, UMD, GP/A)
    - HOU_XUE_ZHANG: Hou-Xue-Zhang Four Factor Model (MKT, ME, IA, ROE)
    - DHS: Daniel-Hirshleifer-Sun Three Factor Model (MKT, PEAD, FIN)
    - CAPM: CAPM单因子模型
    - CH3: 3因子模型 (MKT, SMB, VMG)
    - SY4: 4因子模型 (MKT, SMB, PERF)
    - REVERSAL: 反转因子模型( MKT, SMB, REV)
    - LOW_VOL: 低波动因子模型(MKTm SMB, IVOL)
    """

    FF3 = "ff3"
    FF5 = "ff5"
    CARHART = "carhart"
    NOVY_MARX = "novy_marx"
    HOU_XUE_ZHANG = "hou_xue_zhang"
    DHS = "dhs"
    CAPM = "capm"
    CH3 = "ch3"
    SY4 = "sy4"
    REVERSAL = "reversal"
    LOW_VOL = "low_vol"

    @classmethod
    def list_all(cls) -> List["FactorType"]:
        """List all available factor types."""
        return list(cls)

    @classmethod
    def from_value(cls, value: str) -> "FactorType":
        """Get factor type from string value."""
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"Unknown factor type: {value}")


class CalculationMethod(Enum):
    """
    Factor calculation method.

    - CLASSIC: Classic algorithm (replicates academic papers)
      - Uses value-weighted portfolios
      - Independent sorting with 2x3 or 3x3 breakpoints
      - More rigorous statistical methodology
    - SIMPLE: Simplified algorithm (default)
      - Uses equal-weighted portfolios
      - Simple median-based sorting
      - Faster computation, suitable for daily updates
    """

    CLASSIC = "classic"
    SIMPLE = "simple"

    @classmethod
    def list_all(cls) -> List["CalculationMethod"]:
        """List all available calculation methods."""
        return list(cls)


class TimePeriod(Enum):
    """
    Time granularity for factor calculation.

    - MONTHLY: Monthly frequency (default, "M")
    - DAILY: Daily frequency ("D")
    """

    MONTHLY = "M"
    DAILY = "D"

    @classmethod
    def list_all(cls) -> List["TimePeriod"]:
        """List all available time periods."""
        return list(cls)


# Factor model configuration
# Each factor model defines:
# - name: Display name
# - factors: List of factor names
# - sorting_dims: Dimensions for portfolio sorting
# - portfolio_count: Number of portfolios
# - required_data: Required data fields for this factor


FACTOR_CONFIGS: Dict[FactorType, Dict] = {
    FactorType.CAPM: {
        "name": "CAPM单因子模型",
        "factors": ["mkt"],
        "sorting_dims": [],
        "required_data": [],
    },
    FactorType.FF3: {
        "name": "Fama-French三因子模型",
        "factors": ["mkt", "smb", "hml"],
        "sorting_dims": ["size", "value"],
        "required_data": ["mkt_cap", "bm"],
    },
    FactorType.CARHART: {
        "name": "Carhart四因子模型",
        "factors": ["mkt", "smb", "hml", "umd"],
        "sorting_dims": ["size", "momentum"],
        "required_data": ["mkt_cap", "bm", "momentum"],
    },
    FactorType.FF5: {
        "name": "Fama-French五因子模型",
        "factors": ["mkt", "smb", "hml", "rmw", "cma"],
        "sorting_dims": ["size", "value", "profitability", "investment"],
        "required_data": [
            "mkt_cap",
            "bm",
            "op",
            "asset_growth",
        ],  # RMW用OP，CMA用资产增长
    },
    FactorType.NOVY_MARX: {
        "name": "Novy-Marx四因子模型",
        "factors": ["mkt", "hml_adj", "umd", "gp_a"],  # 核心是GP/A
        "sorting_dims": ["size", "value", "momentum", "profitability"],
        "required_data": ["mkt_cap", "bm", "momentum", "gross_profit", "industry"],
    },
    FactorType.HOU_XUE_ZHANG: {
        "name": "q-factor模型 (Hou-Xue-Zhang)",
        "factors": ["mkt", "me", "ia", "roe"],
        "sorting_dims": ["size", "investment", "profitability"],
        "required_data": ["mkt_cap", "asset_growth", "roe_quarterly"],
    },
    FactorType.DHS: {
        "name": "Daniel-Hirshleifer-Sun行为三因子模型",
        "factors": ["mkt", "pead", "fin"],  # 修正为行为因子
        "sorting_dims": ["earnings_surprise", "financing"],
        "required_data": ["mkt_cap", "sud", "net_share_issuance"],
    },
    # 新加模型
    FactorType.CH3: {
        "name": "中国三因子模型 (CH-3)",
        "factors": ["mkt", "smb", "vmg"],
        "sorting_dims": ["size", "value_weight"],  # VMG 需剔除小票干扰
        "required_data": ["mkt_cap", "bm", "is_st"],
    },
    FactorType.SY4: {
        "name": "Stambaugh-Yuan四因子模型",
        "factors": ["mkt", "smb", "mgmt", "perf"],
        "sorting_dims": ["size", "management_cluster", "performance_cluster"],
        "required_data": ["mkt_cap", "asset_growth", "operating_accruals", "roe"],
    },
    FactorType.REVERSAL: {
        "name": "短期反转模型",
        "factors": ["mkt", "smb", "rev"],
        "sorting_dims": ["size", "return_20d"],  # 过去20日收益率
        "required_data": ["mkt_cap", "close"],
    },
    FactorType.LOW_VOL: {
        "name": "低波动模型",
        "factors": ["mkt", "smb", "ivol"],
        "sorting_dims": ["size", "idiosyncratic_vol"],
        "required_data": ["mkt_cap", "daily_return"],
    },
}

# Default calculation parameters
DEFAULT_MIN_STOCKS = 30  # Minimum stocks required for factor calculation
DEFAULT_MIN_OBSERVATIONS = 24  # Minimum observations for beta calculation
DEFAULT_CHUNK_SIZE = 50  # Chunk size for batch processing
DEFAULT_N_JOBS = min(os.cpu_count() or 1, 4)

# Classic algorithm configuration
# Each factor model defines CLASSIC-specific parameters:
# - breakpoints: Percentile cutoffs for sorting (e.g., [0.3, 0.7] means 30th and 70th percentiles)
# - n_groups: Number of groups per dimension (3 for most models)
# - weighting: Portfolio weighting method ("value" for CLASSIC, "equal" for SIMPLE)
# - factor_definition: How each factor is computed from portfolio returns
CLASSIC_CONFIGS: Dict[FactorType, Dict] = {
    FactorType.FF3: {
        "breakpoints": {"size": [0.5], "bm": [0.3, 0.7]},
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "smb": {"type": "size Spread", "description": "Small minus Big"},
            "hml": {"type": "value Spread", "description": "High minus Low (Value)"},
        },
    },
    FactorType.FF5: {
        # FF5 使用 2x3 分组（Size分别与其他因子交叉，而非四维同时交叉）
        "breakpoints": {
            "size": [0.5],
            "bm": [0.3, 0.7],
            "op": [0.3, 0.7],  # FF5 官方是 OP (Operating Profitability)
            "investment": [0.3, 0.7],
        },
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "smb": {"type": "size Spread"},
            "hml": {"type": "value Spread"},
            "rmw": {
                "type": "profitability Spread",
                "description": "Robust minus Weak (OP)",
            },
            "cma": {
                "type": "investment Spread",
                "description": "Conservative minus Aggressive",
            },
        },
    },
    FactorType.CARHART: {
        "breakpoints": {"size": [0.5], "momentum": [0.3, 0.7]},
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "smb": {"type": "size Spread"},
            "hml": {"type": "value Spread"},
            "umd": {"type": "momentum Spread", "description": "Up minus Down"},
        },
    },
    FactorType.NOVY_MARX: {
        # Novy-Marx 核心贡献：盈利因子与价值因子的结合
        "breakpoints": {
            "size": [0.5],
            "bm": [0.3, 0.7],
            "gp_a": [0.3, 0.7],  # 必须用毛利因子 GP/A
            "momentum": [0.3, 0.7],
        },
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "smb": {"type": "size Spread"},
            "hml_adj": {"type": "value Spread", "description": "Industry-adjusted HML"},
            "umd": {"type": "momentum Spread"},
            "gp_a": {
                "type": "profitability Spread",
                "description": "Profitable minus Unprofitable (GP/A)",
            },
        },
    },
    FactorType.HOU_XUE_ZHANG: {
        # q-factor (2x3x3 分组)
        "breakpoints": {
            "size": [0.5],
            "asset_growth": [0.3, 0.7],
            "roe": [0.3, 0.7],  # 这里的ROE通常是基于最近季度财报
        },
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "me": {"type": "size Spread", "description": "Size factor"},
            "ia": {"type": "investment Spread", "description": "Investment factor"},
            "roe": {"type": "profitability Spread", "description": "ROE factor"},
        },
    },
    FactorType.DHS: {
        # Daniel-Hirshleifer-Sun (2020) 行为模型
        "breakpoints": {
            "size": [0.5],
            "pead": [0.3, 0.7],  # 盈余公告漂移 (Standardized Unanticipated Earnings)
            "fin": [0.3, 0.7],  # 融资因子 (1-year net share issuance)
        },
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "pead": {
                "type": "behavioral Spread",
                "description": "Post-Earnings Announcement Drift",
            },
            "fin": {"type": "behavioral Spread", "description": "Financing factor"},
        },
    },
    # 新加模型
    FactorType.CH3: {
        # 汪昌云-汪勇: VMG (Value Minus Growth)
        # 核心逻辑：在计算价值因子时剔除“壳价值”干扰
        "breakpoints": {"size": [0.5], "bm": [0.3, 0.7]},
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "vmg": {
                "type": "value Spread",
                "description": "Value Minus Growth (A-share Adjusted)",
            },
        },
    },
    FactorType.SY4: {
        # 误定价模型: MGMT(管理)和PERF(绩效)是多维指标聚类
        "breakpoints": {"size": [0.5], "mgmt": [0.2, 0.8], "perf": [0.2, 0.8]},
        "n_groups": 5,  # 学术界常使用五分位数
        "weighting": "value",
        "factor_definition": {
            "mgmt": {
                "type": "mispricing Spread",
                "description": "Management Cluster Factor",
            },
            "perf": {
                "type": "mispricing Spread",
                "description": "Performance Cluster Factor",
            },
        },
    },
    FactorType.REVERSAL: {
        # A股最强异象之一：20日反转
        "breakpoints": {"size": [0.5], "rev": [0.3, 0.7]},
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "rev": {
                "type": "reversal Spread",
                "description": "Short-term Reversal (Low return minus High return)",
            },
        },
    },
    FactorType.LOW_VOL: {
        # 低特质波动率异象
        "breakpoints": {"size": [0.5], "ivol": [0.3, 0.7]},
        "n_groups": 3,
        "weighting": "value",
        "factor_definition": {
            "ivol": {
                "type": "volatility Spread",
                "description": "Low Idio-Vol minus High Idio-Vol",
            },
        },
    },
}
