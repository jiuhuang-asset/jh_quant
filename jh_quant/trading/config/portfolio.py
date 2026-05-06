from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator


_VALID_OBJECTIVES: Set[str] = {"MinRisk", "Utility", "Sharpe", "MaxRet"}
_VALID_MODELS: Set[str] = {"Classic", "BL", "FM"}
_VALID_RISK_MEASURES: Set[str] = {
    "MV", "KT", "MAD", "GMD", "MSV", "SKT",
    "FLPM", "SLPM", "CVaR", "TG", "EVaR", "RLVaR",
    "WR", "RG", "CVRG", "TGRG", "EVRG", "RVRG",
    "MDD", "ADD",
}


class RebalanceMode(str, Enum):
    DISABLED = "disabled"
    INITIAL_ONLY = "initial_only"
    EVERY_CYCLE = "every_cycle"
    DRIFT_THRESHOLD = "drift_threshold"
    SCHEDULE = "schedule"
    MANUAL_ONLY = "manual_only"


class RebalancePolicySpec(BaseModel):
    """调仓触发规则配置。

    用来定义组合在什么条件下执行再平衡，例如按漂移阈值、固定计划或仅手动触发。
    """

    mode: RebalanceMode = Field(
        default=RebalanceMode.MANUAL_ONLY,
        description="调仓触发模式，例如手动、按漂移阈值或按计划调仓。",
    )
    drift_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="当模式为漂移触发时，达到该总偏离阈值后执行调仓。",
    )
    min_rebalance_interval_seconds: Optional[int] = Field(
        default=None, ge=1, description="两次调仓之间允许的最小间隔秒数。"
    )
    schedule_cron: Optional[str] = Field(
        default=None, description="按计划调仓时使用的 cron 表达式。"
    )
    on_selection_change: bool = Field(
        default=True, description="选股结果发生变化时，是否允许触发调仓。"
    )
    on_strategy_change: bool = Field(
        default=True, description="策略配置发生变化时，是否允许触发调仓。"
    )


class PortfolioAnalysisSpec(BaseModel):
    """组合分析参数。

    控制绩效分析时使用的基准、无风险利率和滚动窗口等指标。
    """

    enabled: bool = Field(default=True, description="是否启用组合分析指标计算。")
    benchmark_symbol: Optional[str] = Field(
        default=None, description="分析时使用的基准标的代码。"
    )
    risk_free_rate: float = Field(
        default=0.0, description="无风险利率，供夏普比率等指标计算使用。"
    )
    rolling_window: int = Field(
        default=60, ge=2, description="滚动分析窗口长度，单位通常为交易日。"
    )


class PortfolioSpec(BaseModel):
    """组合优化与调仓总配置。

    这部分配置决定是否启用组合优化、使用什么优化目标与风险模型，
    以及仓位约束、现金保留和调仓规则等关键行为。
    """

    enabled: bool = Field(default=False, description="是否启用组合优化与调仓流程。")
    optimizer: str = Field(default="riskfolio", description="组合优化器名称。")
    objective: str = Field(
        default="Sharpe", description="优化目标，例如最大化 Sharpe 比率。"
    )
    risk_measure: str = Field(
        default="MV", description="风险度量方式，例如均值方差 `MV`。"
    )
    model: str = Field(default="Classic", description="优化模型名称。")
    covariance_method: str = Field(default="ledoit", description="协方差矩阵估计方法。")
    historical_lookback_days: int = Field(
        default=252, ge=20, description="估计收益与风险时使用的历史回看天数。"
    )
    max_assets: Optional[int] = Field(
        default=None,
        ge=1,
        description="组合允许持有的最大资产数量；`None` 表示不限制。",
    )
    min_weight: float = Field(
        default=0.0, ge=0.0, le=1.0, description="单个资产允许的最小权重。"
    )
    max_weight: float = Field(
        default=0.2, ge=0.0, le=1.0, description="单个资产允许的最大权重。"
    )
    weight_epsilon: float = Field(
        default=0.001,
        ge=0.0,
        lt=1.0,
        description="权重清零阈值，小于该值的权重可视为 0。",
    )
    cash_reserve_ratio: float = Field(
        default=0.0, ge=0.0, lt=1.0, description="组合中预留现金的比例。"
    )
    lot_size: int = Field(default=100, ge=1, description="下单时采用的最小交易单位。")
    allow_partial_rebalance: bool = Field(
        default=True, description="现金或约束不足时，是否允许部分完成调仓。"
    )
    rebalance_policy: RebalancePolicySpec = Field(
        default_factory=RebalancePolicySpec, description="调仓触发规则配置。"
    )
    analysis: PortfolioAnalysisSpec = Field(
        default_factory=PortfolioAnalysisSpec, description="组合分析参数配置。"
    )

    @field_validator("objective")
    @classmethod
    def _validate_objective(cls, v: str) -> str:
        if v not in _VALID_OBJECTIVES:
            raise ValueError(
                f"Invalid objective '{v}'. Must be one of: {sorted(_VALID_OBJECTIVES)}"
            )
        return v

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        if v not in _VALID_MODELS:
            raise ValueError(
                f"Invalid model '{v}'. Must be one of: {sorted(_VALID_MODELS)}"
            )
        return v

    @field_validator("risk_measure")
    @classmethod
    def _validate_risk_measure(cls, v: str) -> str:
        if v not in _VALID_RISK_MEASURES:
            raise ValueError(
                f"Invalid risk_measure '{v}'. Must be one of: {sorted(_VALID_RISK_MEASURES)}"
            )
        return v


class PortfolioOptimizerDefinition(BaseModel):
    name: str
    params_schema: Dict[str, Any]
    optional_dependency: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


PORTFOLIO_OPTIMIZER_REGISTRY: Dict[str, PortfolioOptimizerDefinition] = {
    "riskfolio": PortfolioOptimizerDefinition(
        name="riskfolio",
        params_schema=PortfolioSpec.model_json_schema(),
        optional_dependency="Riskfolio-Lib",
        notes=[
            "Uses historical returns built from MarketDataProvider price data.",
            "Lazy-imports Riskfolio-Lib and only fails when optimization is explicitly requested.",
        ],
    )
}


def list_portfolio_optimizer_definitions() -> list[dict[str, Any]]:
    return [
        definition.model_dump() for definition in PORTFOLIO_OPTIMIZER_REGISTRY.values()
    ]
