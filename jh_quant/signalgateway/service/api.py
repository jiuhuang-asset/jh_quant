from __future__ import annotations

from dataclasses import asdict
from typing import List

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - optional dependency at runtime
    FastAPI = None

try:
    from fastapi_mcp import FastApiMCP
except ImportError:  # pragma: no cover - optional dependency at runtime
    FastApiMCP = None

try:
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:  # pragma: no cover - optional dependency at runtime
    CORSMiddleware = None

try:
    import uvicorn
except ImportError:  # pragma: no cover - optional dependency at runtime
    uvicorn = None

from ..config import SelectionSpec, StrategySpec
from ..utils import print_service_startup_summary
from .core import SignalGatewayService
from .schemas import (
    AnalyticsSnapshotResponse,
    CloseAllPositionsRequest,
    CloseAllPositionsResponse,
    HealthResponse,
    PerformanceSnapshotResponse,
    RuntimeSnapshotResponse,
    SchedulerConfigUpdateRequest,
    SchedulerConfigUpdateResponse,
    SelectionConfigUpdateResponse,
    ServiceActionResponse,
    ServiceConfigResponse,
    ServiceStatusResponse,
    SingleSymbolTradeRequest,
    SingleSymbolTradeResponse,
    StrategyConfigUpdateResponse,
    TradingCycleResultResponse,
)


def _mount_mcp_server(app) -> None:
    if FastApiMCP is None:
        raise ImportError("fastapi-mcp is required to expose the service API as MCP")

    mcp = FastApiMCP(app)
    mount_http = getattr(mcp, "mount_http", None)
    if callable(mount_http):
        mount_http()
    else:  # pragma: no cover
        mcp.mount()


def create_service_app(service: SignalGatewayService):
    if FastAPI is None:
        raise ImportError("fastapi is required to create the service API")

    app = FastAPI(title="jh-quant SignalGateway Service")
    if CORSMiddleware is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health", response_model=HealthResponse, operation_id="health_check")
    def health():
        return HealthResponse(status="ok")

    @app.get("/service/status", response_model=ServiceStatusResponse, operation_id="get_service_status")
    def service_status():
        return service.get_status()

    @app.get("/service/runtime", response_model=RuntimeSnapshotResponse, operation_id="get_service_runtime")
    def service_runtime():
        return service.get_runtime_snapshot()

    @app.get(
        "/service/performance",
        response_model=PerformanceSnapshotResponse,
        operation_id="get_service_performance",
    )
    def service_performance():
        return service.get_performance_snapshot()

    @app.get(
        "/service/analytics",
        response_model=AnalyticsSnapshotResponse,
        operation_id="get_service_analytics",
    )
    def service_analytics():
        return service.get_analysis_snapshot()

    @app.get("/service/config", response_model=ServiceConfigResponse, operation_id="get_service_config")
    def service_config():
        return service.get_config_snapshot()

    @app.post("/service/start", response_model=ServiceActionResponse, operation_id="start_service")
    def service_start():
        service.start()
        return ServiceActionResponse(status="started", session_id=service.config.session_id)

    @app.post("/service/stop", response_model=ServiceActionResponse, operation_id="stop_service")
    def service_stop():
        service.stop()
        return ServiceActionResponse(status="stopped", session_id=service.config.session_id)

    @app.post("/service/run-once", response_model=TradingCycleResultResponse, operation_id="run_service_once")
    def run_once():
        result = service.run_once()
        return TradingCycleResultResponse(**asdict(result))

    @app.post(
        "/service/strategy-config",
        response_model=StrategyConfigUpdateResponse,
        operation_id="update_strategy_config",
    )
    def update_strategy_config(strategy_specs: List[StrategySpec]):
        service.configure_strategies(strategy_specs)
        return StrategyConfigUpdateResponse(status="updated", count=len(strategy_specs))

    @app.post(
        "/service/selection-config",
        response_model=SelectionConfigUpdateResponse,
        operation_id="update_selection_config",
    )
    def update_selection_config(selection_spec: SelectionSpec):
        service.configure_selection(selection_spec)
        return SelectionConfigUpdateResponse(
            status="updated",
            name=selection_spec.name,
            alias=selection_spec.alias,
        )

    @app.get("/service/selection-config", operation_id="get_selection_config")
    def get_selection_config():
        return {
            "selection_provider": getattr(service.selection_provider, "config", {}),
        }

    @app.post(
        "/service/scheduler-config",
        response_model=SchedulerConfigUpdateResponse,
        operation_id="update_scheduler_config",
    )
    def update_scheduler_config(request: SchedulerConfigUpdateRequest):
        return service.update_scheduler_config(
            interval_seconds=request.interval_seconds,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            auto_start=request.auto_start,
        )

    @app.post(
        "/service/close-all-positions",
        response_model=CloseAllPositionsResponse,
        operation_id="close_all_positions",
    )
    def close_all_positions(request: CloseAllPositionsRequest):
        return service.close_all_positions(slippage=request.slippage)

    @app.post(
        "/service/signal-buy",
        response_model=SingleSymbolTradeResponse,
        operation_id="signal_buy_symbol",
    )
    def signal_buy_symbol(request: SingleSymbolTradeRequest):
        return service.signal_buy_symbol(
            symbol=request.symbol,
            target_qty=request.target_qty,
            slippage=request.slippage,
        )

    @app.post(
        "/service/signal-sell",
        response_model=SingleSymbolTradeResponse,
        operation_id="signal_sell_symbol",
    )
    def signal_sell_symbol(request: SingleSymbolTradeRequest):
        return service.signal_sell_symbol(
            symbol=request.symbol,
            target_qty=request.target_qty,
            slippage=request.slippage,
        )

    _mount_mcp_server(app)

    return app


def run_service_app(
    service: SignalGatewayService,
    host: str = "127.0.0.1",
    port: int = 8000,
):
    if uvicorn is None:
        raise ImportError("uvicorn is required to run the service API")
    app = create_service_app(service)
    print_service_startup_summary(
        session_id=service.config.session_id or "unknown",
        mode=service.config.mode,
        host=host,
        port=port,
        timezone=service.config.timezone,
        auto_start=service.config.auto_start,
        interval_seconds=service.config.interval_seconds,
        cron_expression=service.config.cron_expression,
    )
    uvicorn.run(app, host=host, port=port)
