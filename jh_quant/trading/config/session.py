from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from .enums import Frequency
from .portfolio import PortfolioAnalysisSpec, PortfolioSpec, RebalancePolicySpec
from .risk_rules import RiskRuleSpec
from .selection import SelectionSpec
from .strategy import StrategySpec


class _UnsetType:
    pass


_UNSET = _UnsetType()


class SessionConfig(BaseModel):
    """Session 运行参数。

    这部分配置控制 session 如何调度、以什么模式运行，以及是否恢复历史状态。
    一般通过 `SessionServiceConfigBuilder.with_session(...)` 设置。
    """

    session_id: Optional[str] = Field(
        default=None, description="会话 ID，用于关联持久化状态、订单和运行记录。"
    )
    mode: Literal["paper", "live"] = Field(
        default="paper", description="运行模式：`paper` 为模拟盘，`live` 为实盘。"
    )
    price_lookback_days: int = Field(
        default=180, description="执行策略和选股时向前回看的行情天数。"
    )
    max_candidates: int = Field(default=20, description="每轮最多处理的候选标的数量。")
    auto_start: bool = Field(
        default=True, description="Session 初始化完成后是否自动启动调度线程。"
    )
    frequency: Frequency = Field(
        default=Frequency.DAILY, description="交易频率枚举，用于描述策略运行节奏。"
    )
    price_slippage: float = Field(
        default=0, description="成交滑点比例，例如 `0.001` 表示千分之一。"
    )
    cron_expression: Optional[str] = Field(
        default=None, description="cron 调度表达式。"
    )
    timezone: str = Field(
        default="Asia/Shanghai", description="cron 调度使用的时区名称。"
    )
    restore_persisted_state: bool = Field(
        default=True,
        description="启动时是否从持久化存储恢复最近一次保存的 session 状态。",
    )
    enable_backfill: bool = Field(
        default=False,
        description="是否启用回填模式。启用后会从 backfill_from 开始逐日模拟交易。仅支持 Daily 或更粗频率。",
    )
    backfill_from: Optional[str] = Field(
        default=None,
        description="回填起始日期（格式 YYYY-MM-DD）。仅在 enable_backfill=True 时生效。",
    )

    @field_validator("frequency", mode="before")
    @classmethod
    def _normalize_frequency(cls, value: Frequency | str) -> Frequency:
        return Frequency.from_value(value)

    @field_serializer("frequency")
    def _serialize_frequency(self, value: Frequency) -> str:
        return value.value


class SessionServiceConfig(BaseModel):
    """Trading 模块的完整配置包。

    包含三部分：
    - `session`：session 的运行参数
    - `selection_spec`：选股器配置
    - `strategy_specs` / `portfolio_spec`：策略和组合配置
    """

    session: SessionConfig = Field(
        default_factory=SessionConfig, description="Session 运行参数。"
    )
    selection_spec: Optional[SelectionSpec] = Field(
        default=None, description="当前使用的选股器配置。"
    )
    strategy_specs: List[StrategySpec] = Field(
        default_factory=list, description="当前启用的策略配置列表。"
    )
    risk_rule_specs: List[RiskRuleSpec] = Field(
        default_factory=list,
        description="风险规则配置列表，用于实盘/模拟盘的风险管理。",
    )
    portfolio_spec: PortfolioSpec = Field(
        default_factory=PortfolioSpec, description="组合优化与调仓配置。"
    )

    @classmethod
    def defaults(cls) -> "SessionServiceConfig":
        return cls()


class SessionServiceConfigBuilder:
    """链式构建 Trading 配置的辅助类。

    设计目标是让调用端可以用连续的 `.with_xxx(...).add_xxx(...).build()`
    写法组织配置，同时保留较好的 IDE 自动补全体验。
    """

    def __init__(self, base_config: Optional[SessionServiceConfig] = None):
        self._config = (base_config or SessionServiceConfig.defaults()).model_copy(
            deep=True
        )

    @classmethod
    def defaults(cls) -> "SessionServiceConfigBuilder":
        """从默认配置创建一个新的 builder。"""
        return cls()

    def _apply_model_updates(
        self, target_model: BaseModel, **candidate_updates: Any
    ) -> BaseModel:
        updates = {
            key: value
            for key, value in candidate_updates.items()
            if not isinstance(value, _UnsetType)
        }
        return target_model.model_copy(update=updates)

    def with_session(
        self,
        *,
        session_id: str | None | _UnsetType = _UNSET,
        mode: Literal["paper", "live"] | _UnsetType = _UNSET,
        price_lookback_days: int | _UnsetType = _UNSET,
        max_candidates: int | _UnsetType = _UNSET,
        auto_start: bool | _UnsetType = _UNSET,
        frequency: Frequency | str | _UnsetType = _UNSET,
        price_slippage: float | _UnsetType = _UNSET,
        cron_expression: str | None | _UnsetType = _UNSET,
        timezone: str | _UnsetType = _UNSET,
        restore_persisted_state: bool | _UnsetType = _UNSET,
        enable_backfill: bool | _UnsetType = _UNSET,
        backfill_from: str | None | _UnsetType = _UNSET,
    ) -> "SessionServiceConfigBuilder":
        """更新 session 运行参数。

        常用参数说明：
        - `session_id`：本次运行的会话标识，用于关联持久化状态和交易记录。
        - `mode`：运行模式，`paper` 为模拟盘，`live` 为实盘。
        - `price_lookback_days`：拉取行情和指标时向前回看的天数。
        - `max_candidates`：每轮交易最多处理的候选标的数量。
        - `auto_start`：Session 初始化后是否自动启动调度线程。
        - `frequency`：交易频率枚举，可传 `Frequency` 或其字符串值。
        - `price_slippage`：成交滑点比例，例如 `0.001` 表示千分之一。
        - `cron_expression`：按 cron 表达式调度时的规则。
        - `timezone`：cron 调度所使用的时区。
        - `restore_persisted_state`：启动时是否从持久化存储恢复上一次保存的 session 状态。
        - `enable_backfill`：是否启用回填模式，从 backfill_from 逐日模拟交易。
        - `backfill_from`：回填起始日期（YYYY-MM-DD），仅在 enable_backfill=True 时生效。

        未传入的参数会保持原值不变；显式传入 `None` 的字段会被更新为 `None`。
        """
        self._config.session = self._apply_model_updates(
            self._config.session,
            session_id=session_id,
            mode=mode,
            price_lookback_days=price_lookback_days,
            max_candidates=max_candidates,
            auto_start=auto_start,
            frequency=frequency,
            price_slippage=price_slippage,
            cron_expression=cron_expression,
            timezone=timezone,
            restore_persisted_state=restore_persisted_state,
            enable_backfill=enable_backfill,
            backfill_from=backfill_from,
        )
        return self

    def with_selection(
        self,
        *,
        name: str,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        """设置选股器配置。

        参数说明：
        - `name`：选股器注册名，例如 `factor_selector`。
        - `params`：传给选股器的参数字典，具体字段取决于对应 provider。
        - `alias`：可选别名，便于在外部接口或日志里区分配置。
        """
        self._config.selection_spec = SelectionSpec(
            name=name,
            params=params or {},
            alias=alias,
        )
        return self

    def with_selection_spec(
        self,
        selection_spec: Optional[SelectionSpec],
    ) -> "SessionServiceConfigBuilder":
        """直接替换完整的选股器配置对象。"""
        self._config.selection_spec = selection_spec
        return self

    def with_strategies(
        self,
        strategy_specs: List[StrategySpec],
    ) -> "SessionServiceConfigBuilder":
        """一次性替换全部策略配置列表。"""
        self._config.strategy_specs = list(strategy_specs)
        return self

    def with_strategy(
        self,
        *,
        name: str,
        weight: float = 1.0,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        """替换为单条策略配置（清空已有策略列表）。"""
        self._config.strategy_specs = [
            StrategySpec(
                name=name,
                weight=weight,
                params=params or {},
                alias=alias,
            )
        ]
        return self

    def add_strategy(
        self,
        *,
        name: str,
        weight: float = 1.0,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        """追加一条策略配置。

        参数说明：
        - `name`：策略注册名，例如 `turtle`、`moving_average_crossover`。
        - `weight`：策略权重，用于多策略组合时分配影响力。
        - `params`：策略初始化参数字典。
        - `alias`：可选别名，用于日志、接口展示或区分多个同类策略实例。
        """
        self._config.strategy_specs.append(
            StrategySpec(
                name=name,
                weight=weight,
                params=params or {},
                alias=alias,
            )
        )
        return self

    def with_risk_rules(
        self,
        risk_rule_specs: List[RiskRuleSpec],
    ) -> "SessionServiceConfigBuilder":
        """一次性替换全部风险规则配置列表。"""
        self._config.risk_rule_specs = list(risk_rule_specs)
        return self

    def with_risk_rule(
        self,
        *,
        name: str,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        """替换为单条风险规则配置（清空已有风险规则列表）。"""
        self._config.risk_rule_specs = [
            RiskRuleSpec(
                name=name,
                params=params or {},
                alias=alias,
            )
        ]
        return self

    def add_risk_rule(
        self,
        *,
        name: str,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        """追加一条风险规则配置。

        参数说明：
        - `name`：规则注册名，例如 `stop_loss`、`trailing_stop`。
        - `params`：规则初始化参数字典。
        - `alias`：可选别名，便于日志、接口展示或区分多个同类规则实例。
        """
        self._config.risk_rule_specs.append(
            RiskRuleSpec(
                name=name,
                params=params or {},
                alias=alias,
            )
        )
        return self

    def with_portfolio(
        self,
        *,
        enabled: bool | _UnsetType = _UNSET,
        optimizer: str | _UnsetType = _UNSET,
        objective: str | _UnsetType = _UNSET,
        risk_measure: str | _UnsetType = _UNSET,
        model: str | _UnsetType = _UNSET,
        covariance_method: str | _UnsetType = _UNSET,
        historical_lookback_days: int | _UnsetType = _UNSET,
        max_assets: int | None | _UnsetType = _UNSET,
        min_weight: float | _UnsetType = _UNSET,
        max_weight: float | _UnsetType = _UNSET,
        weight_epsilon: float | _UnsetType = _UNSET,
        cash_reserve_ratio: float | _UnsetType = _UNSET,
        lot_size: int | _UnsetType = _UNSET,
        allow_partial_rebalance: bool | _UnsetType = _UNSET,
        rebalance_policy: RebalancePolicySpec | _UnsetType = _UNSET,
        analysis: PortfolioAnalysisSpec | _UnsetType = _UNSET,
    ) -> "SessionServiceConfigBuilder":
        """更新组合优化与调仓参数（对接 riskfolio-lib）。

        常用参数说明：
        - `enabled`：是否启用组合优化/调仓流程。
        - `optimizer`：优化器名称，当前默认是 `riskfolio`。
        - `objective`：优化目标，可选值：
            - ``'MinRisk'``：最小化所选风险度量。
            - ``'Utility'``：最大化 Utility 函数 μw - l·φ_i(w)。
            - ``'Sharpe'``：最大化风险调整回报率（夏普比率），**默认值**。
            - ``'MaxRet'``：最大化组合预期收益。
        - `risk_measure`：风险度量方式，可选值：
            - ``'MV'``：标准差（均值方差），**默认值**。
            - ``'KT'``：Kurtosis 的平方根。
            - ``'MAD'``：平均绝对偏差。
            - ``'GMD'``：Gini 均值差。
            - ``'MSV'``：半标准差。
            - ``'SKT'``：Semi Kurtosis 的平方根。
            - ``'FLPM'``：一阶下偏矩（Omega Ratio）。
            - ``'SLPM'``：二阶下偏矩（Sortino Ratio）。
            - ``'CVaR'``：条件在险价值（Conditional Value at Risk）。
            - ``'TG'``：尾部 Gini。
            - ``'EVaR'``：熵在险价值。
            - ``'RLVaR'``：相对论在险价值（建议仅与 MOSEK 求解器配合使用）。
            - ``'WR'``：最坏情景（Minimax）。
            - ``'RG'``：收益范围。
            - ``'CVRG'``：CVaR 收益范围。
            - ``'TGRG'``：尾部 Gini 收益范围。
            - ``'EVRG'``：EVaR 收益范围。
            - ``'RVRG'``：RLVaR 收益范围（建议仅与 MOSEK 求解器配合使用）。
            - ``'MDD'``：最大回撤（Calmar Ratio）。
            - ``'ADD'``：平均回撤。
        - `model`：优化模型，可选值：
            - ``'Classic'``：经典优化模型，**默认值**。
            - ``'BL'``：Black-Litterman 模型。
            - ``'FM'``：因子模型。
        - `covariance_method`：协方差矩阵估计方法，可选值：
            - ``'hist'``：历史协方差。
            - ``'ewma1'`` / ``'ewma2'``：指数加权移动平均。
            - ``'ledoit'``：Ledoit-Wolf 收缩估计，**默认值**。
            - ``'oas'``：Oracle Approximating Shrinkage。
            - ``'shrunk'``：压缩估计。
            - ``'gl'``：Graphical Lasso。
            - ``'jlogo'``：JLOGO。
            - ``'fixed'``：固定协方差矩阵。
            - ``'spectral'``：谱聚类。
            - ``'shrink'``：通用收缩法。
            - ``'gerber1'`` / ``'gerber2'``：Gerber 统计量方法。
        - `historical_lookback_days`：用于估计收益与风险的历史回看天数。
        - `max_assets`：组合中允许持有的最大资产数，`None` 表示不额外限制。
        - `min_weight` / `max_weight`：单资产权重上下界。
        - `weight_epsilon`：权重清零阈值，小于该值的权重可视为 0。
        - `cash_reserve_ratio`：保留现金比例。
        - `lot_size`：下单时的最小交易单位。
        - `allow_partial_rebalance`：现金不足时是否允许部分调仓。
        - `rebalance_policy`：调仓触发规则对象。
        - `analysis`：组合分析参数对象。
        """
        self._config.portfolio_spec = self._apply_model_updates(
            self._config.portfolio_spec,
            enabled=enabled,
            optimizer=optimizer,
            objective=objective,
            risk_measure=risk_measure,
            model=model,
            covariance_method=covariance_method,
            historical_lookback_days=historical_lookback_days,
            max_assets=max_assets,
            min_weight=min_weight,
            max_weight=max_weight,
            weight_epsilon=weight_epsilon,
            cash_reserve_ratio=cash_reserve_ratio,
            lot_size=lot_size,
            allow_partial_rebalance=allow_partial_rebalance,
            rebalance_policy=rebalance_policy,
            analysis=analysis,
        )
        return self

    def with_portfolio_spec(
        self,
        portfolio_spec: PortfolioSpec,
    ) -> "SessionServiceConfigBuilder":
        """直接替换完整的组合配置对象。"""
        self._config.portfolio_spec = portfolio_spec
        return self

    def build(self) -> SessionServiceConfig:
        """生成最终配置对象。"""
        return self._config.model_copy(deep=True)


def default_session_config() -> SessionServiceConfig:
    return SessionServiceConfig.defaults()


def build_session_config(
    base_config: Optional[SessionServiceConfig] = None,
) -> SessionServiceConfigBuilder:
    return SessionServiceConfigBuilder(base_config=base_config)
