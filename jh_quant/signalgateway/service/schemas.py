"""
Request and response models for the signalgateway service API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from ..config import PortfolioSpec, SelectionSpec, SignalGatewayServiceConfig, StrategySpec
from ..config.risk_management import RiskManagementParamsConfig


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
    config_bundle: SignalGatewayServiceConfig = Field(description="Unified service configuration bundle.")
    service: Dict[str, Any] = Field(description="Service-level configuration.")
    selection_spec: Optional[Dict[str, Any]] = Field(default=None, description="Current selection spec.")
    selection_provider: Dict[str, Any] = Field(default_factory=dict, description="Selection provider configuration.")
    strategy_specs: List[Dict[str, Any]] = Field(default_factory=list, description="Configured strategy specs.")
    portfolio_spec: Optional[Dict[str, Any]] = Field(default=None, description="Current portfolio spec.")
    config_source: str = Field(default="bootstrap", description="Where the active config bundle was loaded from.")
    persisted_user_config_available: bool = Field(
        default=False,
        description="Whether a dedicated persisted user config exists for the current session.",
    )
    persisted_user_config_updated_at: Optional[str] = Field(
        default=None,
        description="Last update time of the dedicated persisted user config record.",
    )


class ServiceConfigUpdateRequest(BaseModel):
    config_bundle: SignalGatewayServiceConfig = Field(description="Unified service configuration bundle to apply.")


class ServiceConfigUpdateResponse(BaseModel):
    status: str = Field(description="Unified service config update result.")
    session_id: str = Field(description="Session ID for the updated service.")
    config_bundle: SignalGatewayServiceConfig = Field(description="Current unified service configuration bundle.")


class ConfigurableComponentDefinition(BaseModel):
    name: str = Field(description="Registered component name.")
    params_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema for user-editable params.")
    runtime_dependencies: List[str] = Field(
        default_factory=list,
        description="Dependencies injected by the service at runtime and not expected from the API caller.",
    )


class PortfolioOptimizerDefinitionResponse(BaseModel):
    name: str = Field(description="Portfolio optimizer name.")
    params_schema: Dict[str, Any] = Field(default_factory=dict)
    optional_dependency: Optional[str] = Field(default=None)
    notes: List[str] = Field(default_factory=list)


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


class SchedulerConfigSnapshotResponse(BaseModel):
    running: bool = Field(description="Whether the scheduler is currently running.")
    auto_start: bool = Field(description="Current auto-start configuration.")
    scheduler: SchedulerStatus = Field(description="Current scheduler configuration and status.")


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


class PortfolioConfigUpdateRequest(BaseModel):
    portfolio_spec: PortfolioSpec = Field(description="Portfolio configuration spec.")


class PortfolioConfigUpdateResponse(BaseModel):
    status: str = Field(description="Portfolio config update result.")
    portfolio_spec: PortfolioSpec = Field(description="Current portfolio spec.")


class PortfolioConfigSnapshotResponse(BaseModel):
    portfolio_spec: PortfolioSpec = Field(description="Current portfolio spec.")
    available_optimizers: List[PortfolioOptimizerDefinitionResponse] = Field(
        default_factory=list,
        description="Available portfolio optimizers and config schema.",
    )


class PortfolioOptimizeRequest(BaseModel):
    as_of_date: Optional[str] = Field(default=None, description="Optimization end date in YYYY-MM-DD format.")
    preview_only: bool = Field(default=True, description="Whether to only preview optimization results.")
    symbols: Optional[List[str]] = Field(default=None, description="Optional explicit symbol override.")


class PortfolioOptimizeResponse(BaseModel):
    status: str = Field(description="Optimization result status.")
    optimizer: str = Field(description="Optimizer name.")
    as_of_date: str = Field(description="Optimization date.")
    symbols: List[str] = Field(default_factory=list, description="Final symbol universe actually used in optimization.")
    weights: List[Dict[str, Any]] = Field(default_factory=list, description="Target portfolio weights.")
    diagnostics: Dict[str, Any] = Field(default_factory=dict, description="Optimization diagnostics.")
    preview_only: bool = Field(default=True, description="Whether the result is preview-only.")


class PortfolioAnalysisResponse(BaseModel):
    portfolio_spec: PortfolioSpec = Field(description="Current portfolio spec.")
    current_portfolio: Dict[str, Any] = Field(default_factory=dict, description="Current holding snapshot.")
    drift: Dict[str, Any] = Field(default_factory=dict, description="Current vs target drift snapshot.")
    latest_optimization: Optional[Dict[str, Any]] = Field(default=None, description="Latest optimization payload.")
    latest_rebalance: Optional[Dict[str, Any]] = Field(default=None, description="Latest rebalance payload.")


class PortfolioHistoryResponse(BaseModel):
    weight_history: List[Dict[str, Any]] = Field(default_factory=list)
    portfolio_value_history: List[Dict[str, Any]] = Field(default_factory=list)


class ServiceEventRecordResponse(BaseModel):
    event_type: str = Field(description="Persisted service event type.")
    event_time: Optional[str] = Field(default=None, description="Persisted event timestamp.")
    export_time: Optional[str] = Field(default=None, description="Snapshot export timestamp.")
    state_data: Dict[str, Any] = Field(default_factory=dict, description="Persisted service state payload.")


class ServiceEventHistoryResponse(BaseModel):
    session_id: str = Field(description="Session ID for the service event history.")
    count: int = Field(description="Number of returned service events.")
    events: List[ServiceEventRecordResponse] = Field(default_factory=list, description="Persisted service events.")


class PortfolioRebalanceRequest(BaseModel):
    as_of_date: Optional[str] = Field(default=None, description="Rebalance date in YYYY-MM-DD format.")
    preview_only: bool = Field(default=True, description="Whether to only preview rebalance orders.")
    symbols: Optional[List[str]] = Field(default=None, description="Optional explicit symbol override.")
    force: bool = Field(default=False, description="Whether to bypass rebalance policy checks.")


class PortfolioRebalanceResponse(BaseModel):
    status: str = Field(description="Rebalance result status.")
    as_of_date: str = Field(description="Rebalance date.")
    preview_only: bool = Field(default=True, description="Whether the response is a preview.")
    should_rebalance: bool = Field(default=False, description="Whether rebalance policy allows execution.")
    reason: str = Field(default="", description="Reason for the rebalance decision.")
    execution_path: Optional[str] = Field(
        default=None,
        description="Execution path used for this rebalance, e.g. strategy-driven portfolio overlay.",
    )
    target_allocations: List[Dict[str, Any]] = Field(default_factory=list, description="Target allocation plan.")
    buy_orders: List[Dict[str, Any]] = Field(default_factory=list, description="Buy order plan.")
    sell_orders: List[Dict[str, Any]] = Field(default_factory=list, description="Sell order plan.")
    blocked_buy_orders: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Buy orders blocked or capped by runtime cash constraints.",
    )
    blocked_sell_orders: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Sell orders blocked or capped by executable holdings constraints such as A-share T+1.",
    )
    projected_buy_cost: float = Field(default=0.0)
    projected_sell_value: float = Field(default=0.0)
    projected_cash_after: float = Field(default=0.0)
    drift: Dict[str, Any] = Field(default_factory=dict)
    executed_buy_count: int = Field(default=0)
    executed_sell_count: int = Field(default=0)


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


class StrategyEvaluateRequest(BaseModel):
    """Request model for strategy evaluation."""

    symbol_source: str = Field(
        default="selection",
        description="Source of symbols: 'selection' (from SelectionProvider) or 'holdings' (from OMS positions).",
    )
    as_of_date: Optional[str] = Field(
        default=None,
        description="Evaluation end date in YYYY-MM-DD format. Defaults to today.",
    )
    lookback_days: Optional[int] = Field(
        default=None, ge=1,
        description="Override for price lookback days. Falls back to service config value.",
    )
    commission_rate: float = Field(
        default=0.0002, ge=0.0,
        description="Commission rate (e.g. 0.0002 = 0.02%).",
    )
    stamp_tax_rate: float = Field(
        default=0.0005, ge=0.0,
        description="Stamp tax rate for sells (e.g. 0.0005 = 0.05%).",
    )


class StrategyEvaluateResponse(BaseModel):
    """Response model for strategy evaluation results."""

    status: str = Field(description="Evaluation result status.")
    as_of_date: str = Field(description="Evaluation end date.")
    symbol_source: str = Field(description="Source of symbols used.")
    symbols: List[str] = Field(default_factory=list, description="Symbols evaluated.")
    strategy_count: int = Field(description="Number of strategies evaluated.")
    metrics: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-strategy, per-symbol performance metrics records.",
    )
    trading_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Trading history rows with strategy_return, cumulative_return, drawdown, etc.",
    )


class RiskManagementConfigResponse(BaseModel):
    """Response model for risk management configuration."""

    risk_management_specs: Dict[str, RiskManagementParamsConfig] = Field(
        default_factory=dict,
        description="Current per-strategy risk management params.",
    )


class RiskManagementConfigUpdateRequest(BaseModel):
    """Request model for updating risk management configuration."""

    risk_management_specs: Dict[str, RiskManagementParamsConfig] = Field(
        default_factory=dict,
        description="Complete replacement of per-strategy risk management params.",
    )


class RiskManagementConfigUpdateResponse(BaseModel):
    """Response model for risk management configuration update."""

    status: str = Field(description="Update result status.")
    risk_management_specs: Dict[str, RiskManagementParamsConfig] = Field(
        default_factory=dict,
        description="Updated per-strategy risk management params.",
    )


# ── Data API models ──────────────────────────────────────────────

MAX_DATA_QUERY_ROWS = 10_000


class DataCountRequest(BaseModel):
    """Request to count data rows for a given data type and optional filters."""

    data_type: str = Field(description="Data type identifier (e.g. 'ak_stock_zh_a_hist').")
    symbol: Optional[str] = Field(default=None, description="Stock symbol filter (comma-separated for multiple).")
    ts_code: Optional[str] = Field(default=None, description="Tushare code filter (comma-separated for multiple).")
    start: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD).")
    end: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD).")


class DataCountResponse(BaseModel):
    """Response with row count for the requested data type."""

    data_type: str = Field(description="Queried data type identifier.")
    count: int = Field(description="Total row count matching the filters.")
    max_query_rows: int = Field(default=MAX_DATA_QUERY_ROWS, description="Threshold for direct data return.")


class DataQueryRequest(BaseModel):
    """Request to query data with automatic size checking."""

    data_type: str = Field(description="Data type identifier (e.g. 'ak_stock_zh_a_hist').")
    symbol: Optional[str] = Field(default=None, description="Stock symbol filter (comma-separated for multiple).")
    ts_code: Optional[str] = Field(default=None, description="Tushare code filter (comma-separated for multiple).")
    start: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD).")
    end: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD).")
    remote: bool = Field(default=False, description="Force fetch from remote API (bypass cache).")


class DataQueryResponse(BaseModel):
    """Response with queried data, or a signal that filters are required."""

    status: str = Field(description="Query status: 'ok', 'too_large', or 'empty'.")
    data_type: str = Field(description="Queried data type identifier.")
    count: int = Field(default=0, description="Total matching rows (0 for empty).")
    max_query_rows: int = Field(default=MAX_DATA_QUERY_ROWS, description="Threshold for direct data return.")
    message: str = Field(default="", description="Human-readable status message.")
    suggestion: Optional[str] = Field(default=None, description="Suggestion for narrowing the query (when too_large).")
    data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Result records (only when status='ok').")


class DataTypeInfo(BaseModel):
    """Metadata for a single available data type."""

    value: str = Field(description="Enum value string (e.g. 'ak_stock_zh_a_hist').")
    name: str = Field(description="Enum member name (e.g. 'AK_STOCK_ZH_A_HIST').")


class DataTypesListResponse(BaseModel):
    """Response listing all available data types."""

    types: List[DataTypeInfo] = Field(default_factory=list, description="Available data types.")
    count: int = Field(description="Total number of available data types.")


class DataSchemaResponse(BaseModel):
    """Response with table schema for a data type."""

    data_type: str = Field(description="Data type identifier.")
    fields: List[str] = Field(default_factory=list, description="Ordered table column names.")
    unique_keys: List[str] = Field(default_factory=list, description="Unique constraint key columns.")
    dt_field: Optional[str] = Field(default=None, description="Date/time column name (for time-series ordering).")
