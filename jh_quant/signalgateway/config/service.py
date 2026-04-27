from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from .enums import Frequency
from .portfolio import PortfolioAnalysisSpec, PortfolioSpec, RebalancePolicySpec
from .selection import SelectionSpec
from .strategy import StrategySpec


class _UnsetType:
    pass


_UNSET = _UnsetType()


class ServiceConfig(BaseModel):
    """SignalGateway 服务运行参数。

    这部分配置控制服务如何调度、以什么模式运行，以及是否恢复历史状态。
    一般通过 `SignalGatewayServiceConfigBuilder.with_service(...)` 设置。
    """

    session_id: Optional[str] = Field(default=None, description="服务会话 ID，用于关联持久化状态、订单和运行记录。")
    mode: Literal["paper", "live"] = Field(default="paper", description="运行模式：`paper` 为模拟盘，`live` 为实盘。")
    price_lookback_days: int = Field(default=180, description="执行策略和选股时向前回看的行情天数。")
    max_candidates: int = Field(default=10, description="每轮最多处理的候选标的数量。")
    auto_start: bool = Field(default=False, description="服务初始化完成后是否自动启动调度线程。")
    frequency: Frequency = Field(default=Frequency.DAILY, description="交易频率枚举，用于描述策略运行节奏。")
    price_slippage: float = Field(default=0.0, description="成交滑点比例，例如 `0.001` 表示千分之一。")
    interval_seconds: int = Field(default=300, description="固定间隔调度模式下，两次执行之间的秒数。")
    cron_expression: Optional[str] = Field(default=None, description="cron 调度表达式；设置后通常优先于固定秒级间隔。")
    timezone: str = Field(default="Asia/Shanghai", description="cron 调度使用的时区名称。")
    restore_persisted_state: bool = Field(default=True, description="启动时是否从持久化存储恢复最近一次保存的服务状态。")

    @field_validator("frequency", mode="before")
    @classmethod
    def _normalize_frequency(cls, value: Frequency | str) -> Frequency:
        return Frequency.from_value(value)

    @field_serializer("frequency")
    def _serialize_frequency(self, value: Frequency) -> str:
        return value.value


class SignalGatewayServiceConfig(BaseModel):
    """SignalGateway 的完整配置包。

    包含三部分：
    - `service`：服务本身的运行参数
    - `selection_spec`：选股器配置
    - `strategy_specs` / `portfolio_spec`：策略和组合配置
    """

    service: ServiceConfig = Field(default_factory=ServiceConfig, description="服务运行参数。")
    selection_spec: Optional[SelectionSpec] = Field(default=None, description="当前使用的选股器配置。")
    strategy_specs: List[StrategySpec] = Field(default_factory=list, description="当前启用的策略配置列表。")
    portfolio_spec: PortfolioSpec = Field(default_factory=PortfolioSpec, description="组合优化与调仓配置。")

    @classmethod
    def defaults(cls) -> "SignalGatewayServiceConfig":
        return cls()


class SignalGatewayServiceConfigBuilder:
    """链式构建 SignalGateway 配置的辅助类。

    设计目标是让调用端可以用连续的 `.with_xxx(...).add_xxx(...).build()`
    写法组织配置，同时保留较好的 IDE 自动补全体验。
    """

    def __init__(self, base_config: Optional[SignalGatewayServiceConfig] = None):
        self._config = (base_config or SignalGatewayServiceConfig.defaults()).model_copy(deep=True)

    @classmethod
    def defaults(cls) -> "SignalGatewayServiceConfigBuilder":
        """从默认配置创建一个新的 builder。"""
        return cls()

    def _apply_model_updates(self, model: BaseModel, **candidate_updates: Any) -> BaseModel:
        updates = {
            key: value for key, value in candidate_updates.items() if not isinstance(value, _UnsetType)
        }
        return model.model_copy(update=updates)

    def with_service(
        self,
        *,
        session_id: str | None | _UnsetType = _UNSET,
        mode: Literal["paper", "live"] | _UnsetType = _UNSET,
        price_lookback_days: int | _UnsetType = _UNSET,
        max_candidates: int | _UnsetType = _UNSET,
        auto_start: bool | _UnsetType = _UNSET,
        frequency: Frequency | str | _UnsetType = _UNSET,
        price_slippage: float | _UnsetType = _UNSET,
        interval_seconds: int | _UnsetType = _UNSET,
        cron_expression: str | None | _UnsetType = _UNSET,
        timezone: str | _UnsetType = _UNSET,
        restore_persisted_state: bool | _UnsetType = _UNSET,
    ) -> "SignalGatewayServiceConfigBuilder":
        """更新服务运行参数。

        常用参数说明：
        - `session_id`：本次运行的会话标识，用于关联持久化状态和交易记录。
        - `mode`：运行模式，`paper` 为模拟盘，`live` 为实盘。
        - `price_lookback_days`：拉取行情和指标时向前回看的天数。
        - `max_candidates`：每轮交易最多处理的候选标的数量。
        - `auto_start`：服务初始化后是否自动启动调度线程。
        - `frequency`：交易频率枚举，可传 `Frequency` 或其字符串值。
        - `price_slippage`：成交滑点比例，例如 `0.001` 表示千分之一。
        - `interval_seconds`：按固定间隔调度时，两次执行之间的秒数。
        - `cron_expression`：按 cron 表达式调度时的规则；设置后通常优先于固定间隔。
        - `timezone`：cron 调度所使用的时区。
        - `restore_persisted_state`：启动时是否从持久化存储恢复上一次保存的服务状态。

        未传入的参数会保持原值不变；显式传入 `None` 的字段会被更新为 `None`。
        """
        self._config.service = self._apply_model_updates(
            self._config.service,
            session_id=session_id,
            mode=mode,
            price_lookback_days=price_lookback_days,
            max_candidates=max_candidates,
            auto_start=auto_start,
            frequency=frequency,
            price_slippage=price_slippage,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            timezone=timezone,
            restore_persisted_state=restore_persisted_state,
        )
        return self

    def with_selection(
        self,
        *,
        name: str,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SignalGatewayServiceConfigBuilder":
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
    ) -> "SignalGatewayServiceConfigBuilder":
        """直接替换完整的选股器配置对象。"""
        self._config.selection_spec = selection_spec
        return self

    def with_strategies(
        self,
        strategy_specs: List[StrategySpec],
    ) -> "SignalGatewayServiceConfigBuilder":
        """一次性替换全部策略配置列表。"""
        self._config.strategy_specs = list(strategy_specs)
        return self

    def add_strategy(
        self,
        *,
        name: str,
        weight: float = 1.0,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SignalGatewayServiceConfigBuilder":
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
    ) -> "SignalGatewayServiceConfigBuilder":
        """更新组合优化与调仓参数。

        常用参数说明：
        - `enabled`：是否启用组合优化/调仓流程。
        - `optimizer`：优化器名称，当前默认是 `riskfolio`。
        - `objective`：优化目标，例如 `Sharpe`。
        - `risk_measure`：风险度量方式，例如 `MV` 表示均值方差。
        - `model`：优化模型名称，例如 `Classic`。
        - `covariance_method`：协方差估计方法，例如 `ledoit`。
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
    ) -> "SignalGatewayServiceConfigBuilder":
        """直接替换完整的组合配置对象。"""
        self._config.portfolio_spec = portfolio_spec
        return self

    def build(self) -> SignalGatewayServiceConfig:
        """生成最终配置对象。"""
        return self._config.model_copy(deep=True)


def default_service_config() -> SignalGatewayServiceConfig:
    return SignalGatewayServiceConfig.defaults()


def build_service_config(
    base_config: Optional[SignalGatewayServiceConfig] = None,
) -> SignalGatewayServiceConfigBuilder:
    return SignalGatewayServiceConfigBuilder(base_config=base_config)
