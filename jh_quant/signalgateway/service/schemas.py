"""
Request and response models for the signalgateway service API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from ..config import SelectionSpec, StrategySpec


class HealthResponse(BaseModel):
    status: str = Field(description="Service health status.")


class SchedulerStatus(BaseModel):
    interval_seconds: int = Field(description="Scheduler interval in seconds.")
    cron_expression: Optional[str] = Field(
        default=None,
        description="Cron expression when cron scheduling is enabled.",
    )
    timezone: str = Field(description="Scheduler timezone.")
    schedule_type: str = Field(default="interval", description="Current schedule mode.")
    next_run_at: Optional[str] = Field(default=None, description="Next scheduled run time.")
    next_run_in_seconds: Optional[float] = Field(
        default=None,
        description="Seconds until the next run.",
    )
    next_runs: List[str] = Field(default_factory=list, description="Next scheduled run times.")


class TradingCycleResultResponse(BaseModel):
    session_id: str = Field(description="Current service session ID.")
    mode: str = Field(description="Service running mode.")
    cycle_time: str = Field(description="Completed time for the latest trading cycle.")
    selection_count: int = Field(description="Number of selected securities in the latest cycle.")
    long_candidate_count: int = Field(
        description="Number of long candidates identified in the latest cycle."
    )
    short_candidate_count: int = Field(
        description="Number of short candidates identified in the latest cycle."
    )
    executed_buy_count: int = Field(description="Number of buy orders executed in the latest cycle.")
    executed_sell_count: int = Field(description="Number of sell orders executed in the latest cycle.")
    selected_symbols: List[str] = Field(default_factory=list, description="Selected symbols.")
    long_symbols: List[str] = Field(default_factory=list, description="Long candidate symbols.")
    short_symbols: List[str] = Field(default_factory=list, description="Short candidate symbols.")
    status: str = Field(default="success", description="Execution status.")
    error: Optional[str] = Field(default=None, description="Error text when execution fails.")


class ServiceStatusResponse(BaseModel):
    session_id: str = Field(description="Current service session ID.")
    mode: str = Field(description="Service running mode.")
    running: bool = Field(description="Whether the scheduler is currently running.")
    scheduler: SchedulerStatus = Field(description="Scheduler configuration and status summary.")
    last_error: Optional[str] = Field(default=None, description="Most recent runtime error.")
    last_result: Optional[TradingCycleResultResponse] = Field(
        default=None,
        description="Most recent trading cycle result.",
    )


class RuntimeSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the runtime snapshot.")
    generated_at: str = Field(description="Snapshot generation time.")
    positions: Dict[str, Any] = Field(description="Current positions and runtime state.")
    oms_state: Optional[Dict[str, Any]] = Field(default=None, description="Full OMS exported state.")


class PerformanceSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the performance snapshot.")
    generated_at: str = Field(description="Snapshot generation time.")
    summary: Dict[str, Any] = Field(description="Summary performance metrics.")
    holding_returns: List[Dict[str, Any]] = Field(default_factory=list, description="Latest holding return rows.")
    turnover: List[Dict[str, Any]] = Field(default_factory=list, description="Turnover rows grouped by trade date.")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="Equity curve rows grouped by trade date.")
    trade_activity: List[Dict[str, Any]] = Field(default_factory=list, description="Trade activity rows grouped by trade date.")
    position_exposure: Dict[str, Any] = Field(default_factory=dict, description="Position exposure analysis.")
    latest_portfolio: Dict[str, Any] = Field(default_factory=dict, description="Latest portfolio snapshot.")


class ServiceConfigResponse(BaseModel):
    session_id: str = Field(description="Session ID for the service configuration snapshot.")
    service: Dict[str, Any] = Field(description="Service-level configuration.")
    selection_spec: Optional[Dict[str, Any]] = Field(default=None, description="Current selection spec.")
    selection_provider: Dict[str, Any] = Field(default_factory=dict, description="Selection provider configuration.")
    strategy_specs: List[Dict[str, Any]] = Field(default_factory=list, description="Configured strategy specs.")


class ConfigurableComponentDefinition(BaseModel):
    name: str = Field(description="Registered component name.")
    params_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema for user-editable params.")
    runtime_dependencies: List[str] = Field(
        default_factory=list,
        description="Dependencies injected by the service at runtime and not expected from the API caller.",
    )


class AnalyticsSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the analytics snapshot.")
    generated_at: str = Field(description="Snapshot generation time.")
    status: ServiceStatusResponse = Field(description="Service status snapshot.")
    runtime: RuntimeSnapshotResponse = Field(description="Runtime snapshot.")
    performance: PerformanceSnapshotResponse = Field(description="Performance snapshot.")
    config: ServiceConfigResponse = Field(description="Config snapshot.")


class ServiceActionResponse(BaseModel):
    status: str = Field(description="Result of the service action.")
    session_id: Optional[str] = Field(default=None, description="Related session ID.")


class StrategyConfigUpdateResponse(BaseModel):
    status: str = Field(description="Strategy configuration update result.")
    count: int = Field(description="Number of strategy configs applied.")
    strategy_specs: List[StrategySpec] = Field(default_factory=list, description="Current strategy specs.")


class StrategyConfigUpdateRequest(BaseModel):
    strategy_specs: List[StrategySpec] = Field(default_factory=list, description="Strategy specs to replace the current set.")


class StrategyConfigSnapshotResponse(BaseModel):
    strategy_specs: List[StrategySpec] = Field(default_factory=list, description="Current strategy specs.")
    available_strategies: List[ConfigurableComponentDefinition] = Field(
        default_factory=list,
        description="Available registered strategies and their editable params schema.",
    )


class SchedulerConfigUpdateRequest(BaseModel):
    interval_seconds: Optional[int] = Field(default=None, ge=1, description="Interval in seconds.")
    cron_expression: Optional[str] = Field(default=None, description="Cron expression.")
    timezone: Optional[str] = Field(default=None, description="Scheduler timezone.")
    auto_start: Optional[bool] = Field(default=None, description="Whether to auto start the scheduler.")


class SchedulerConfigUpdateResponse(BaseModel):
    status: str = Field(description="Scheduler configuration update result.")
    running: bool = Field(description="Whether the scheduler is running after the update.")
    scheduler: SchedulerStatus = Field(description="Updated scheduler configuration.")
    auto_start: bool = Field(description="Updated auto-start configuration.")


class SelectionConfigUpdateResponse(BaseModel):
    status: str = Field(description="Selection provider configuration update result.")
    name: str = Field(description="Updated selection provider name.")
    alias: Optional[str] = Field(default=None, description="Alias if provided.")
    selection_spec: SelectionSpec = Field(description="Current selection spec.")


class SelectionConfigUpdateRequest(BaseModel):
    selection_spec: SelectionSpec = Field(description="Selection spec to use.")


class SelectionConfigSnapshotResponse(BaseModel):
    selection_spec: Optional[SelectionSpec] = Field(default=None, description="Current selection spec.")
    active_selection_config: Dict[str, Any] = Field(default_factory=dict, description="Resolved active selection config.")
    available_selections: List[ConfigurableComponentDefinition] = Field(
        default_factory=list,
        description="Available registered selection providers and their editable params schema.",
    )


@dataclass
class TradingCycleResult:
    session_id: str
    mode: str
    cycle_time: str
    selection_count: int
    long_candidate_count: int
    short_candidate_count: int
    executed_buy_count: int
    executed_sell_count: int
    selected_symbols: List[str] = field(default_factory=list)
    long_symbols: List[str] = field(default_factory=list)
    short_symbols: List[str] = field(default_factory=list)
    status: str = "success"
    error: Optional[str] = None

    def serialize(self) -> TradingCycleResultResponse:
        return TradingCycleResultResponse(**asdict(self))


class CloseAllPositionsRequest(BaseModel):
    slippage: float = Field(default=0.0, description="Slippage ratio for batch closeout.")


class CloseAllPositionsResponse(BaseModel):
    status: str = Field(description="Operation result.")
    closed_count: int = Field(description="Number of closed positions.")
    executed_trades: List[Dict[str, Any]] = Field(default_factory=list, description="Executed trades.")


class SingleSymbolTradeRequest(BaseModel):
    symbol: str = Field(description="Ticker symbol.")
    target_qty: Optional[int] = Field(default=None, description="Target quantity to trade.")
    slippage: float = Field(default=0.0, description="Per-trade slippage ratio.")


class SingleSymbolTradeResponse(BaseModel):
    status: str = Field(description="Operation result.")
    action: str = Field(description="Operation type.")
    symbol: str = Field(description="Ticker symbol.")
    executed: bool = Field(description="Whether the trade was executed.")
    trade: Optional[Dict[str, Any]] = Field(default=None, description="Executed trade details.")
    message: str = Field(description="Result description.")
