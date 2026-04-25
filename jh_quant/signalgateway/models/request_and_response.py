"""
Request and Response models for signalgateway service API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="服务健康状态，通常为 ok")


class SchedulerStatus(BaseModel):
    interval_seconds: int = Field(description="轮询调度间隔，单位为秒")
    cron_expression: Optional[str] = Field(default=None, description="Cron 调度表达式，为空表示使用固定间隔调度")
    timezone: str = Field(description="调度器使用的时区")
    schedule_type: str = Field(default="interval", description="当前调度模式")
    next_run_at: Optional[str] = Field(default=None, description="下一次预计触发时间")
    next_run_in_seconds: Optional[float] = Field(default=None, description="距离下一次触发的秒数")
    next_runs: List[str] = Field(default_factory=list, description="未来几次预计触发时间")


class TradingCycleResultResponse(BaseModel):
    session_id: str = Field(description="Current service session ID")
    mode: str = Field(description="Service running mode, such as paper or live")
    cycle_time: str = Field(description="Completed time for the latest trading cycle")
    selection_count: int = Field(description="Number of selected securities in the latest cycle")
    long_candidate_count: int = Field(description="Number of long candidates identified in the latest cycle")
    short_candidate_count: int = Field(description="Number of short or sell candidates identified in the latest cycle")
    executed_buy_count: int = Field(description="Number of buy orders executed in the latest cycle")
    executed_sell_count: int = Field(description="Number of sell orders executed in the latest cycle")
    selected_symbols: List[str] = Field(default_factory=list, description="Selected symbols in the latest cycle")
    long_symbols: List[str] = Field(default_factory=list, description="Long candidate symbols in the latest cycle")
    short_symbols: List[str] = Field(default_factory=list, description="Short candidate symbols in the latest cycle")
    status: str = Field(default="success", description="Execution status for the latest trading cycle")
    error: Optional[str] = Field(default=None, description="Error text when the latest trading cycle fails")


class ServiceStatusResponse(BaseModel):
    session_id: str = Field(description="Current service session ID")
    mode: str = Field(description="Service running mode")
    running: bool = Field(description="Whether the scheduler is currently running")
    scheduler: SchedulerStatus = Field(description="Scheduler configuration and status summary")
    last_error: Optional[str] = Field(default=None, description="Most recent runtime error")
    last_result: Optional[TradingCycleResultResponse] = Field(
        default=None,
        description="Most recent trading cycle result",
    )


class RuntimeSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the runtime snapshot")
    generated_at: str = Field(description="Snapshot generation time")
    positions: Dict[str, Any] = Field(description="Current positions and runtime state")
    oms_state: Optional[Dict[str, Any]] = Field(default=None, description="Full OMS exported state")


class PerformanceSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the performance snapshot")
    generated_at: str = Field(description="Snapshot generation time")
    summary: Dict[str, Any] = Field(description="Summary performance metrics")
    holding_returns: List[Dict[str, Any]] = Field(default_factory=list, description="Latest holding return rows")
    turnover: List[Dict[str, Any]] = Field(default_factory=list, description="Turnover rows grouped by trade date")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="Equity curve rows grouped by trade date")
    trade_activity: List[Dict[str, Any]] = Field(default_factory=list, description="Trade activity rows grouped by trade date")
    position_exposure: Dict[str, Any] = Field(default_factory=dict, description="Position exposure analysis")
    latest_portfolio: Dict[str, Any] = Field(default_factory=dict, description="Latest portfolio snapshot")


class ServiceConfigResponse(BaseModel):
    session_id: str = Field(description="Session ID for the service configuration snapshot")
    service: Dict[str, Any] = Field(description="Service-level configuration")
    selection_provider: Dict[str, Any] = Field(default_factory=dict, description="Selection provider configuration")
    strategies: List[Any] = Field(default_factory=list, description="Configured strategies")


class AnalyticsSnapshotResponse(BaseModel):
    session_id: str = Field(description="Session ID for the analytics snapshot")
    generated_at: str = Field(description="Snapshot generation time")
    status: ServiceStatusResponse = Field(description="Service status snapshot")
    runtime: RuntimeSnapshotResponse = Field(description="Runtime snapshot")
    performance: PerformanceSnapshotResponse = Field(description="Performance snapshot")
    config: ServiceConfigResponse = Field(description="Config snapshot")


class ServiceActionResponse(BaseModel):
    status: str = Field(description="Result of the service action")
    session_id: Optional[str] = Field(default=None, description="Related session ID for the service action")


class StrategyConfigUpdateResponse(BaseModel):
    status: str = Field(description="Strategy configuration update result")
    count: int = Field(description="Number of strategy configs applied")


class SchedulerConfigUpdateRequest(BaseModel):
    interval_seconds: Optional[int] = Field(default=None, ge=1)
    cron_expression: Optional[str] = Field(default=None)
    timezone: Optional[str] = Field(default=None)
    auto_start: Optional[bool] = Field(default=None)


class SchedulerConfigUpdateResponse(BaseModel):
    status: str = Field(description="Scheduler configuration update result")
    running: bool = Field(description="Whether the scheduler is running after the update")
    scheduler: SchedulerStatus = Field(description="Updated scheduler configuration")
    auto_start: bool = Field(description="Updated auto-start configuration")


class SelectionConfigUpdateResponse(BaseModel):
    status: str = Field(description="Selection provider configuration update result")
    name: str = Field(description="Updated selection provider name")
    alias: Optional[str] = Field(default=None, description="Alias if provided")


@dataclass
class SelectionSnapshot:
    top_selections: List[str]
    bottom_selections: Optional[List[str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


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