from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from .broker import BrokerSpec
from .enums import ClockMode, ExecutionMode, Frequency
from .portfolio import PortfolioAnalysisSpec, PortfolioSpec, RebalancePolicySpec
from .risk_rules import RiskRuleSpec
from .selection import SelectionSpec
from .strategy import StrategySpec


class _UnsetType:
    pass


_UNSET = _UnsetType()


class SessionConfig(BaseModel):
    """Runtime settings for a trading session."""

    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier used for persistence and runtime records.",
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.PAPER,
        description="Order execution mode: paper or live.",
    )
    clock_mode: ClockMode = Field(
        default=ClockMode.REALTIME,
        description="Clock mode: realtime or historical backfill replay.",
    )
    price_lookback_days: int = Field(
        default=180,
        description="Historical lookback window used by selection and strategy logic.",
    )
    max_candidates: int = Field(
        default=20,
        description="Maximum number of candidate symbols processed per cycle.",
    )
    auto_start: bool = Field(
        default=True,
        description="Whether to auto-start scheduling after service initialization.",
    )
    frequency: Frequency = Field(
        default=Frequency.DAILY,
        description="Trading cadence used by the session scheduler.",
    )
    price_slippage: float = Field(
        default=0,
        description="Execution slippage ratio used by simulated trading.",
    )
    cron_expression: Optional[str] = Field(
        default=None,
        description="Optional cron schedule for the session.",
    )
    timezone: str = Field(
        default="Asia/Shanghai",
        description="Timezone used by cron scheduling.",
    )
    restore_persisted_state: bool = Field(
        default=True,
        description="Whether to restore the most recent persisted session state on startup.",
    )
    backfill_start: Optional[str] = Field(
        default=None,
        description="Backfill start date in YYYY-MM-DD format when clock_mode=backfill.",
    )

    @field_validator("frequency", mode="before")
    @classmethod
    def _normalize_frequency(cls, value: Frequency | str) -> Frequency:
        return Frequency.from_value(value)

    @field_serializer("frequency")
    def _serialize_frequency(self, value: Frequency) -> str:
        return value.value


class SessionServiceConfig(BaseModel):
    """Top-level trading service configuration bundle."""

    session: SessionConfig = Field(
        default_factory=SessionConfig,
        description="Session runtime settings.",
    )
    broker_spec: Optional[BrokerSpec] = Field(
        default=None,
        description="Broker configuration. Required for live mode; optional for paper mode.",
    )
    selection_spec: Optional[SelectionSpec] = Field(
        default=None,
        description="Selection provider configuration.",
    )
    strategy_specs: List[StrategySpec] = Field(
        default_factory=list,
        description="Enabled strategy configurations.",
    )
    risk_rule_specs: List[RiskRuleSpec] = Field(
        default_factory=list,
        description="Enabled risk rule configurations.",
    )
    portfolio_spec: PortfolioSpec = Field(
        default_factory=PortfolioSpec,
        description="Portfolio optimization and rebalance settings.",
    )

    @classmethod
    def defaults(cls) -> "SessionServiceConfig":
        return cls()

    @model_validator(mode="after")
    def _validate_broker_mode_consistency(self) -> "SessionServiceConfig":
        is_live = self.session.execution_mode == ExecutionMode.LIVE
        is_backfill = self.session.clock_mode == ClockMode.BACKFILL

        if is_live and self.broker_spec is None:
            raise ValueError("live execution_mode requires an explicit broker_spec")

        if (
            self.session.execution_mode == ExecutionMode.PAPER
            and self.broker_spec is not None
            and self.broker_spec.name.lower() != "paper"
        ):
            raise ValueError(
                "paper execution_mode does not accept a live broker_spec. "
                "Leave broker_spec empty to auto-select PaperBroker."
            )

        if is_backfill and self.session.backfill_start is None:
            raise ValueError("backfill_start must be set when clock_mode=backfill")

        return self


class SessionServiceConfigBuilder:
    """Fluent builder for SessionServiceConfig."""

    def __init__(self, base_config: Optional[SessionServiceConfig] = None):
        self._config = (base_config or SessionServiceConfig.defaults()).model_copy(
            deep=True
        )

    @classmethod
    def defaults(cls) -> "SessionServiceConfigBuilder":
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
        execution_mode: ExecutionMode | str | _UnsetType = _UNSET,
        clock_mode: ClockMode | str | _UnsetType = _UNSET,
        price_lookback_days: int | _UnsetType = _UNSET,
        max_candidates: int | _UnsetType = _UNSET,
        auto_start: bool | _UnsetType = _UNSET,
        frequency: Frequency | str | _UnsetType = _UNSET,
        price_slippage: float | _UnsetType = _UNSET,
        cron_expression: str | None | _UnsetType = _UNSET,
        timezone: str | _UnsetType = _UNSET,
        restore_persisted_state: bool | _UnsetType = _UNSET,
        backfill_start: str | None | _UnsetType = _UNSET,
    ) -> "SessionServiceConfigBuilder":
        normalized_execution_mode = execution_mode
        if isinstance(normalized_execution_mode, str):
            normalized_execution_mode = ExecutionMode(normalized_execution_mode)

        normalized_clock_mode = clock_mode
        if isinstance(normalized_clock_mode, str):
            normalized_clock_mode = ClockMode(normalized_clock_mode)

        self._config.session = self._apply_model_updates(
            self._config.session,
            session_id=session_id,
            execution_mode=normalized_execution_mode,
            clock_mode=normalized_clock_mode,
            price_lookback_days=price_lookback_days,
            max_candidates=max_candidates,
            auto_start=auto_start,
            frequency=frequency,
            price_slippage=price_slippage,
            cron_expression=cron_expression,
            timezone=timezone,
            restore_persisted_state=restore_persisted_state,
            backfill_start=backfill_start,
        )
        return self

    def with_selection(
        self,
        *,
        name: str,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        self._config.selection_spec = SelectionSpec(
            name=name,
            params=params or {},
            alias=alias,
        )
        return self

    def with_broker(
        self,
        *,
        name: str,
        params: Optional[Dict[str, Any]] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
        self._config.broker_spec = BrokerSpec(
            name=name,
            params=params or {},
            alias=alias,
        )
        return self

    def with_broker_spec(
        self,
        broker_spec: Optional[BrokerSpec],
    ) -> "SessionServiceConfigBuilder":
        self._config.broker_spec = broker_spec
        return self

    def with_selection_spec(
        self,
        selection_spec: Optional[SelectionSpec],
    ) -> "SessionServiceConfigBuilder":
        self._config.selection_spec = selection_spec
        return self

    def with_strategies(
        self,
        strategy_specs: List[StrategySpec],
    ) -> "SessionServiceConfigBuilder":
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
        self._config.risk_rule_specs = list(risk_rule_specs)
        return self

    def with_risk_rule(
        self,
        *,
        name: str,
        params: Optional[Any] = None,
        alias: Optional[str] = None,
    ) -> "SessionServiceConfigBuilder":
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
        self._config.portfolio_spec = portfolio_spec
        return self

    def build(self) -> SessionServiceConfig:
        return SessionServiceConfig.model_validate(
            self._config.model_dump(exclude_none=False)
        )


def default_session_config() -> SessionServiceConfig:
    return SessionServiceConfig.defaults()


def build_session_config(
    base_config: Optional[SessionServiceConfig] = None,
) -> SessionServiceConfigBuilder:
    return SessionServiceConfigBuilder(base_config=base_config)
