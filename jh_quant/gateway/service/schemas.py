"""
Request and response models for the gateway session API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from ..config import PortfolioSpec, SelectionSpec, SessionServiceConfig, StrategySpec


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
    next_run_at: Optional[str] = Field(
        default=None, description="Next scheduled run time."
    )
    next_run_in_seconds: Optional[float] = Field(
        default=None,
        description="Seconds until the next run.",
    )
    next_runs: List[str] = Field(
        default_factory=list, description="Next scheduled run times."
    )


class TradingCycleResultResponse(BaseModel):
    session_id: str = Field(description="Current session ID.")
    mode: str = Field(description="Session running mode.")
    cycle_time: str = Field(description="Completed time for the latest trading cycle.")
    selection_count: int = Field(
        description="Number of selected securities in the latest cycle."
    )
    long_candidate_count: int = Field(
        description="Number of long candidates identified in the latest cycle."
    )
    short_candidate_count: int = Field(
        description="Number of short candidates identified in the latest cycle."
    )
    executed_buy_count: int = Field(
        description="Number of buy orders executed in the latest cycle."
    )
    executed_sell_count: int = Field(
        description="Number of sell orders executed in the latest cycle."
    )
    selected_symbols: List[str] = Field(
        default_factory=list, description="Selected symbols."
    )
    long_symbols: List[str] = Field(
        default_factory=list, description="Long candidate symbols."
    )
    short_symbols: List[str] = Field(
        default_factory=list, description="Short candidate symbols."
    )
    status: str = Field(default="success", description="Execution status.")
    error: Optional[str] = Field(
        default=None, description="Error text when execution fails."
    )


class SessionStatusResponse(BaseModel):
    session_id: str = Field(description="Current session ID.")
    mode: str = Field(description="Session running mode.")
    running: bool = Field(description="Whether the scheduler is currently running.")
    scheduler: SchedulerStatus = Field(
        description="Scheduler configuration and status summary."
    )
    last_error: Optional[str] = Field(
        default=None, description="Most recent runtime error."
    )
    last_result: Optional[TradingCycleResultResponse] = Field(
        default=None,
        description="Most recent trading cycle result.",
    )


class RuntimeSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the runtime snapshot.")
    generated_at: str = Field(description="Snapshot generation time.")
    positions: Dict[str, Any] = Field(
        description="Current positions and runtime state."
    )
    oms_state: Optional[Dict[str, Any]] = Field(
        default=None, description="Full OMS exported state."
    )


class PerformanceSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the performance snapshot.")
    generated_at: str = Field(description="Snapshot generation time.")
    summary: Dict[str, Any] = Field(description="Summary performance metrics.")
    holding_returns: List[Dict[str, Any]] = Field(
        default_factory=list, description="Latest holding return rows."
    )
    turnover: List[Dict[str, Any]] = Field(
        default_factory=list, description="Turnover rows grouped by trade date."
    )
    equity_curve: List[Dict[str, Any]] = Field(
        default_factory=list, description="Equity curve rows grouped by trade date."
    )
    trade_activity: List[Dict[str, Any]] = Field(
        default_factory=list, description="Trade activity rows grouped by trade date."
    )
    position_exposure: Dict[str, Any] = Field(
        default_factory=dict, description="Position exposure analysis."
    )
    latest_portfolio: Dict[str, Any] = Field(
        default_factory=dict, description="Latest portfolio snapshot."
    )


class SessionConfigResponse(BaseModel):
    session_id: str = Field(
        description="Session ID for the session configuration snapshot."
    )
    config_bundle: SessionServiceConfig = Field(
        description="Unified session configuration bundle."
    )
    session: Dict[str, Any] = Field(description="Session-level configuration.")
    selection_spec: Optional[Dict[str, Any]] = Field(
        default=None, description="Current selection spec."
    )
    selection_provider: Dict[str, Any] = Field(
        default_factory=dict, description="Selection provider configuration."
    )
    strategy_specs: List[Dict[str, Any]] = Field(
        default_factory=list, description="Configured strategy specs."
    )
    portfolio_spec: Optional[Dict[str, Any]] = Field(
        default=None, description="Current portfolio spec."
    )
    config_source: str = Field(
        default="bootstrap",
        description="Where the active config bundle was loaded from.",
    )
    persisted_session_config_available: bool = Field(
        default=False,
        description="Whether a dedicated persisted session config exists for the current session.",
    )
    persisted_session_config_updated_at: Optional[str] = Field(
        default=None,
        description="Last update time of the dedicated persisted session config record.",
    )


class SessionConfigUpdateRequest(BaseModel):
    config_bundle: SessionServiceConfig = Field(
        description="Unified session configuration bundle to apply."
    )


class SessionConfigUpdateResponse(BaseModel):
    status: str = Field(description="Unified service config update result.")
    session_id: str = Field(description="Session ID for the updated service.")
    config_bundle: SessionServiceConfig = Field(
        description="Current unified service configuration bundle."
    )


class ConfigurableComponentDefinition(BaseModel):
    name: str = Field(description="Registered component name.")
    params_schema: Dict[str, Any] = Field(
        default_factory=dict, description="JSON schema for user-editable params."
    )
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
    status: SessionStatusResponse = Field(description="Service status snapshot.")
    runtime: RuntimeSnapshotResponse = Field(description="Runtime snapshot.")
    performance: PerformanceSnapshotResponse = Field(
        description="Performance snapshot."
    )
    config: SessionConfigResponse = Field(description="Config snapshot.")


class SessionActionResponse(BaseModel):
    status: str = Field(description="Result of the service action.")
    session_id: Optional[str] = Field(default=None, description="Related session ID.")


class StrategyConfigUpdateResponse(BaseModel):
    status: str = Field(description="Strategy configuration update result.")
    count: int = Field(description="Number of strategy configs applied.")
    strategy_specs: List[StrategySpec] = Field(
        default_factory=list, description="Current strategy specs."
    )


class StrategyConfigUpdateRequest(BaseModel):
    strategy_specs: List[StrategySpec] = Field(
        default_factory=list, description="Strategy specs to replace the current set."
    )


class StrategyConfigSnapshotResponse(BaseModel):
    strategy_specs: List[StrategySpec] = Field(
        default_factory=list, description="Current strategy specs."
    )
    available_strategies: List[ConfigurableComponentDefinition] = Field(
        default_factory=list,
        description="Available registered strategies and their editable params schema.",
    )


class SchedulerConfigUpdateRequest(BaseModel):
    interval_seconds: Optional[int] = Field(
        default=None, ge=1, description="Interval in seconds."
    )
    cron_expression: Optional[str] = Field(default=None, description="Cron expression.")
    timezone: Optional[str] = Field(default=None, description="Scheduler timezone.")
    auto_start: Optional[bool] = Field(
        default=None, description="Whether to auto start the scheduler."
    )


class SchedulerConfigUpdateResponse(BaseModel):
    status: str = Field(description="Scheduler configuration update result.")
    running: bool = Field(
        description="Whether the scheduler is running after the update."
    )
    scheduler: SchedulerStatus = Field(description="Updated scheduler configuration.")
    auto_start: bool = Field(description="Updated auto-start configuration.")


class SchedulerConfigSnapshotResponse(BaseModel):
    running: bool = Field(description="Whether the scheduler is currently running.")
    auto_start: bool = Field(description="Current auto-start configuration.")
    scheduler: SchedulerStatus = Field(
        description="Current scheduler configuration and status."
    )


class SelectionConfigUpdateResponse(BaseModel):
    status: str = Field(description="Selection provider configuration update result.")
    name: str = Field(description="Updated selection provider name.")
    alias: Optional[str] = Field(default=None, description="Alias if provided.")
    selection_spec: SelectionSpec = Field(description="Current selection spec.")


class SelectionConfigUpdateRequest(BaseModel):
    selection_spec: SelectionSpec = Field(description="Selection spec to use.")


class SelectionConfigSnapshotResponse(BaseModel):
    selection_spec: Optional[SelectionSpec] = Field(
        default=None, description="Current selection spec."
    )
    active_selection_config: Dict[str, Any] = Field(
        default_factory=dict, description="Resolved active selection config."
    )
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
    as_of_date: Optional[str] = Field(
        default=None, description="Optimization end date in YYYY-MM-DD format."
    )
    preview_only: bool = Field(
        default=True, description="Whether to only preview optimization results."
    )
    symbols: Optional[List[str]] = Field(
        default=None, description="Optional explicit symbol override."
    )


class PortfolioOptimizeResponse(BaseModel):
    status: str = Field(description="Optimization result status.")
    optimizer: str = Field(description="Optimizer name.")
    as_of_date: str = Field(description="Optimization date.")
    symbols: List[str] = Field(
        default_factory=list,
        description="Final symbol universe actually used in optimization.",
    )
    weights: List[Dict[str, Any]] = Field(
        default_factory=list, description="Target portfolio weights."
    )
    diagnostics: Dict[str, Any] = Field(
        default_factory=dict, description="Optimization diagnostics."
    )
    preview_only: bool = Field(
        default=True, description="Whether the result is preview-only."
    )


class PortfolioAnalysisResponse(BaseModel):
    portfolio_spec: PortfolioSpec = Field(description="Current portfolio spec.")
    current_portfolio: Dict[str, Any] = Field(
        default_factory=dict, description="Current holding snapshot."
    )
    drift: Dict[str, Any] = Field(
        default_factory=dict, description="Current vs target drift snapshot."
    )
    latest_optimization: Optional[Dict[str, Any]] = Field(
        default=None, description="Latest optimization payload."
    )
    latest_rebalance: Optional[Dict[str, Any]] = Field(
        default=None, description="Latest rebalance payload."
    )


class PortfolioHistoryResponse(BaseModel):
    weight_history: List[Dict[str, Any]] = Field(default_factory=list)
    portfolio_value_history: List[Dict[str, Any]] = Field(default_factory=list)


class SessionEventRecordResponse(BaseModel):
    event_type: str = Field(description="Persisted service event type.")
    event_time: Optional[str] = Field(
        default=None, description="Persisted event timestamp."
    )
    export_time: Optional[str] = Field(
        default=None, description="Snapshot export timestamp."
    )
    state_data: Dict[str, Any] = Field(
        default_factory=dict, description="Persisted service state payload."
    )


class SessionEventHistoryResponse(BaseModel):
    session_id: str = Field(description="Session ID for the service event history.")
    count: int = Field(description="Number of returned service events.")
    events: List[SessionEventRecordResponse] = Field(
        default_factory=list, description="Persisted service events."
    )


class PortfolioRebalanceRequest(BaseModel):
    as_of_date: Optional[str] = Field(
        default=None, description="Rebalance date in YYYY-MM-DD format."
    )
    preview_only: bool = Field(
        default=True, description="Whether to only preview rebalance orders."
    )
    symbols: Optional[List[str]] = Field(
        default=None, description="Optional explicit symbol override."
    )
    force: bool = Field(
        default=False, description="Whether to bypass rebalance policy checks."
    )


class PortfolioRebalanceResponse(BaseModel):
    status: str = Field(description="Rebalance result status.")
    as_of_date: str = Field(description="Rebalance date.")
    preview_only: bool = Field(
        default=True, description="Whether the response is a preview."
    )
    should_rebalance: bool = Field(
        default=False, description="Whether rebalance policy allows execution."
    )
    reason: str = Field(default="", description="Reason for the rebalance decision.")
    execution_path: Optional[str] = Field(
        default=None,
        description="Execution path used for this rebalance, e.g. strategy-driven portfolio overlay.",
    )
    target_allocations: List[Dict[str, Any]] = Field(
        default_factory=list, description="Target allocation plan."
    )
    buy_orders: List[Dict[str, Any]] = Field(
        default_factory=list, description="Buy order plan."
    )
    sell_orders: List[Dict[str, Any]] = Field(
        default_factory=list, description="Sell order plan."
    )
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
    slippage: float = Field(
        default=0.0, description="Slippage ratio for batch closeout."
    )


class CloseAllPositionsResponse(BaseModel):
    status: str = Field(description="Operation result.")
    closed_count: int = Field(description="Number of closed positions.")
    executed_trades: List[Dict[str, Any]] = Field(
        default_factory=list, description="Executed trades."
    )


class SingleSymbolTradeRequest(BaseModel):
    symbol: str = Field(description="Ticker symbol.")
    target_qty: Optional[int] = Field(
        default=None, description="Target quantity to trade."
    )
    slippage: float = Field(default=0.0, description="Per-trade slippage ratio.")


class SingleSymbolTradeResponse(BaseModel):
    status: str = Field(description="Operation result.")
    action: str = Field(description="Operation type.")
    symbol: str = Field(description="Ticker symbol.")
    executed: bool = Field(description="Whether the trade was executed.")
    trade: Optional[Dict[str, Any]] = Field(
        default=None, description="Executed trade details."
    )
    message: str = Field(description="Result description.")


# ── Data API models ───────────────────────────────────────────────


class OHLCVRecord(BaseModel):
    """Single OHLCV data point returned by data endpoints."""

    symbol: str = Field(description="Ticker symbol or index code.")
    date: str = Field(description="Trade date in YYYY-MM-DD format.")
    open: float = Field(description="Opening price.")
    high: float = Field(description="Highest price.")
    low: float = Field(description="Lowest price.")
    close: float = Field(description="Closing price.")
    volume: float = Field(default=0.0, description="Trading volume.")
    amount: float = Field(default=0.0, description="Trading amount.")
    chg: Optional[float] = Field(
        default=None, description="Change rate (%). Present for index data."
    )


class DataListResponse(BaseModel):
    """Generic paginated data response."""

    data: List[Dict[str, Any]] = Field(
        default_factory=list, description="OHLCV data records."
    )
    count: int = Field(description="Number of records returned.")


# ── Multi-Session API models ────────────────────────────────────────


class SessionInfoResponse(BaseModel):
    """Summary metadata for a single managed session instance.

    Includes key performance metrics for dashboard overview cards.
    """

    session_id: str = Field(description="Service session ID.")
    mode: str = Field(description="Running mode: paper or live.")
    running: bool = Field(description="Whether the scheduler is currently running.")
    strategy_count: int = Field(description="Number of configured strategies.")
    strategy_names: List[str] = Field(
        default_factory=list, description="Configured strategy names/aliases."
    )
    selection_name: Optional[str] = Field(
        default=None, description="Selection provider name or alias."
    )
    portfolio_enabled: bool = Field(
        default=False, description="Whether portfolio optimization is enabled."
    )
    initial_capital: float = Field(description="Initial capital for this session.")
    current_value: Optional[float] = Field(
        default=None, description="Current portfolio total value."
    )
    total_return_pct: Optional[float] = Field(
        default=None, description="Total return percentage."
    )
    daily_pnl: Optional[float] = Field(default=None, description="Current daily PnL.")
    position_count: int = Field(default=0, description="Number of current positions.")
    max_drawdown: float = Field(
        default=0.0, description="Maximum historical drawdown (negative)."
    )
    win_rate: Optional[float] = Field(default=None, description="Win rate (0.0-1.0).")
    total_trades: int = Field(default=0, description="Total number of trades.")
    total_pnl: float = Field(
        default=0.0, description="Total realized + unrealized PnL."
    )
    last_error: Optional[str] = Field(
        default=None, description="Most recent runtime error."
    )
    last_result: Optional[TradingCycleResultResponse] = Field(
        default=None, description="Most recent trading cycle result."
    )
    created_at: Optional[str] = Field(
        default=None, description="Service creation time."
    )


class SessionListResponse(BaseModel):
    """Response listing all managed session instances."""

    sessions: List[SessionInfoResponse] = Field(
        default_factory=list, description="Managed session instances."
    )
    count: int = Field(description="Current number of sessions.")
    max_sessions: int = Field(description="Maximum allowed sessions.")


class SessionCreateRequest(BaseModel):
    """Request to create a new service under multi-service management."""

    config_bundle: SessionServiceConfig = Field(
        description="Full service configuration bundle."
    )
    initial_capital: float = Field(
        default=100000.0, ge=0, description="Initial capital for paper trading."
    )
    auto_start: Optional[bool] = Field(
        default=None, description="Override auto_start from config."
    )


class SessionCreateResponse(BaseModel):
    """Response after creating a new service."""

    status: str = Field(description="Creation result.")
    session_id: str = Field(description="Assigned session ID for the new service.")


class SessionRemoveResponse(BaseModel):
    """Response after removing a service."""

    status: str = Field(description="Removal result.")
    session_id: str = Field(description="Session ID of the removed service.")


# ── Multi-Session Trends API models ──────────────────────────────────


DEFAULT_TRENDS_LIMIT = 8


class SessionTrendPoint(BaseModel):
    """A single data point in a session's trend series."""

    trade_date: str = Field(description="Trade date in YYYY-MM-DD format.")
    portfolio_value: float = Field(description="Total portfolio value on this date.")
    cumulative_return: Optional[float] = Field(
        default=None, description="Cumulative return from inception."
    )
    drawdown: float = Field(
        default=0.0, description="Drawdown from peak portfolio value."
    )
    daily_pnl: Optional[float] = Field(default=None, description="Daily PnL.")
    num_positions: int = Field(
        default=0, description="Number of open positions on this date."
    )


class SessionTrendItem(BaseModel):
    """Trend series for a single session."""

    session_id: str = Field(description="Session ID.")
    mode: str = Field(description="Running mode (paper/live).")
    initial_capital: float = Field(description="Initial capital.")
    strategy_names: List[str] = Field(
        default_factory=list, description="Strategy names/aliases."
    )
    selection_name: Optional[str] = Field(
        default=None, description="Selection provider name."
    )
    trends: List[SessionTrendPoint] = Field(
        default_factory=list, description="Daily trend data points."
    )


class SessionTrendsResponse(BaseModel):
    """Multi-session trend data for chart overlay."""

    generated_at: str = Field(description="Trends generation time.")
    count: int = Field(description="Number of sessions included.")
    sessions: List[SessionTrendItem] = Field(
        default_factory=list, description="Per-session trend series."
    )
    note: Optional[str] = Field(
        default=None,
        description="Informational message (e.g. when sessions were auto-limited).",
    )


# ── Trade History models ───────────────────────────────────────────


class TradeRecordItem(BaseModel):
    """Single executed trade record."""

    trade_id: str = Field(description="Unique trade identifier.")
    session_id: str = Field(description="Session ID.")
    trade_date: str = Field(description="Trade execution timestamp.")
    symbol: str = Field(description="Ticker symbol.")
    trade_type: str = Field(description="BUY or SELL.")
    price: float = Field(description="Execution price.")
    quantity: int = Field(description="Number of shares.")
    amount: float = Field(description="Trade amount (price * quantity).")
    commission: float = Field(default=0.0, description="Commission fee.")
    slippage: float = Field(default=0.0, description="Slippage applied.")
    total_cost: float = Field(description="Total cost including commission.")
    signal_reason: Optional[str] = Field(
        default=None, description="Signal reason or strategy name."
    )
    order_id: Optional[str] = Field(default=None, description="Associated order ID.")


class TradeHistoryResponse(BaseModel):
    """Trade history for a session, optionally filtered by symbol."""

    session_id: str = Field(description="Session ID.")
    symbol: Optional[str] = Field(
        default=None, description="Filtered symbol, if any."
    )
    count: int = Field(description="Number of trade records returned.")
    trades: List[TradeRecordItem] = Field(
        default_factory=list, description="Executed trade records."
    )


# ── Position Detail models ─────────────────────────────────────────


class PositionDetail(BaseModel):
    """Current holding detail for a single symbol."""

    symbol: str = Field(description="Ticker symbol.")
    quantity: int = Field(description="Number of shares held.")
    avg_cost: float = Field(description="Average cost per share.")
    market_value: float = Field(description="Current market value.")
    entry_time: Optional[str] = Field(
        default=None, description="When this position was first established."
    )


class PositionsResponse(BaseModel):
    """Current positions for a session."""

    session_id: str = Field(description="Session ID.")
    portfolio_value: float = Field(description="Total portfolio value.")
    cash_balance: float = Field(description="Available cash balance.")
    num_positions: int = Field(description="Number of current positions.")
    positions: List[PositionDetail] = Field(
        default_factory=list, description="Current holding details."
    )


class PositionSnapshotItem(BaseModel):
    """Historical position snapshot for a single symbol on a single date."""

    trade_date: str = Field(description="Snapshot date.")
    symbol: str = Field(description="Ticker symbol.")
    quantity: int = Field(description="Number of shares held.")
    avg_cost: float = Field(description="Average cost per share.")
    current_price: float = Field(description="Closing price on this date.")
    market_value: float = Field(description="Market value on this date.")
    pnl: Optional[float] = Field(default=None, description="PnL on this date.")
    pnl_pct: Optional[float] = Field(default=None, description="PnL percentage.")


class PositionHistoryResponse(BaseModel):
    """Historical position snapshots for a session, optionally filtered by symbol."""

    session_id: str = Field(description="Session ID.")
    symbol: Optional[str] = Field(
        default=None, description="Filtered symbol, if any."
    )
    count: int = Field(description="Number of snapshot records returned.")
    snapshots: List[PositionSnapshotItem] = Field(
        default_factory=list, description="Position snapshot records."
    )
