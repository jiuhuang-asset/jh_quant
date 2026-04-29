from __future__ import annotations

from dataclasses import asdict
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

from ..utils import print_service_startup_summary
from .core import SignalGatewayService
from .schemas import (
    AnalyticsSnapshotResponse,
    CloseAllPositionsRequest,
    CloseAllPositionsResponse,
    DataCountRequest,
    DataCountResponse,
    DataQueryRequest,
    DataQueryResponse,
    DataSchemaResponse,
    DataTypesListResponse,
    HealthResponse,
    PerformanceSnapshotResponse,
    PortfolioAnalysisResponse,
    PortfolioConfigSnapshotResponse,
    PortfolioConfigUpdateRequest,
    PortfolioConfigUpdateResponse,
    PortfolioHistoryResponse,
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
    PortfolioRebalanceRequest,
    PortfolioRebalanceResponse,
    RiskManagementConfigResponse,
    RiskManagementConfigUpdateRequest,
    RiskManagementConfigUpdateResponse,
    RuntimeSnapshotResponse,
    SchedulerConfigSnapshotResponse,
    SchedulerConfigUpdateRequest,
    SchedulerConfigUpdateResponse,
    SelectionConfigUpdateResponse,
    SelectionConfigUpdateRequest,
    SelectionConfigSnapshotResponse,
    ServiceActionResponse,
    ServiceConfigResponse,
    ServiceConfigUpdateRequest,
    ServiceConfigUpdateResponse,
    ServiceEventHistoryResponse,
    ServiceStatusResponse,
    SingleSymbolTradeRequest,
    SingleSymbolTradeResponse,
    StrategyConfigSnapshotResponse,
    StrategyConfigUpdateRequest,
    StrategyConfigUpdateResponse,
    StrategyEvaluateRequest,
    StrategyEvaluateResponse,
    TradingCycleResultResponse,
)


def _mount_mcp_server(app) -> None:
    if FastApiMCP is None:
        return

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

    @app.put("/service/config", response_model=ServiceConfigUpdateResponse, operation_id="replace_service_config")
    def replace_service_config(request: ServiceConfigUpdateRequest):
        return service.replace_service_config(request.config_bundle)

    @app.get("/service/events", response_model=ServiceEventHistoryResponse, operation_id="get_service_events")
    def get_service_events():
        return service.get_service_event_history()

    @app.post(
        "/service/scheduler/start",
        response_model=ServiceActionResponse,
        operation_id="start_service_scheduler",
    )
    def service_start():
        service.start_scheduler()
        return ServiceActionResponse(status="started", session_id=service.config.session_id)

    @app.post(
        "/service/scheduler/stop",
        response_model=ServiceActionResponse,
        operation_id="stop_service_scheduler",
    )
    def service_stop():
        service.stop_scheduler()
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
    def update_strategy_config(request: StrategyConfigUpdateRequest):
        service.configure_strategies(request.strategy_specs)
        return StrategyConfigUpdateResponse(
            status="updated",
            count=len(request.strategy_specs),
            strategy_specs=service.strategy_specs,
        )

    @app.get(
        "/service/strategy-config",
        response_model=StrategyConfigSnapshotResponse,
        operation_id="get_strategy_config",
    )
    def get_strategy_config():
        return service.get_strategy_config_snapshot()

    @app.post(
        "/service/selection-config",
        response_model=SelectionConfigUpdateResponse,
        operation_id="update_selection_config",
    )
    def update_selection_config(request: SelectionConfigUpdateRequest):
        selection_spec = request.selection_spec
        service.configure_selection(selection_spec)
        return SelectionConfigUpdateResponse(
            status="updated",
            name=selection_spec.name,
            alias=selection_spec.alias,
            selection_spec=service.selection_specs,
        )

    @app.get(
        "/service/selection-config",
        response_model=SelectionConfigSnapshotResponse,
        operation_id="get_selection_config",
    )
    def get_selection_config():
        return service.get_selection_config_snapshot()

    @app.get(
        "/service/portfolio/config",
        response_model=PortfolioConfigSnapshotResponse,
        operation_id="get_portfolio_config",
    )
    def get_portfolio_config():
        return service.get_portfolio_config_snapshot()

    @app.post(
        "/service/portfolio/config",
        response_model=PortfolioConfigUpdateResponse,
        operation_id="update_portfolio_config",
    )
    def update_portfolio_config(request: PortfolioConfigUpdateRequest):
        service.configure_portfolio(request.portfolio_spec)
        return PortfolioConfigUpdateResponse(
            status="updated",
            portfolio_spec=service.portfolio_spec,
        )

    @app.post(
        "/service/portfolio/optimize",
        response_model=PortfolioOptimizeResponse,
        operation_id="optimize_portfolio",
    )
    def optimize_portfolio(request: PortfolioOptimizeRequest):
        return service.optimize_portfolio(
            as_of_date=request.as_of_date,
            preview_only=request.preview_only,
            symbols=request.symbols,
        )

    @app.get(
        "/service/portfolio/analysis",
        response_model=PortfolioAnalysisResponse,
        operation_id="get_portfolio_analysis",
    )
    def get_portfolio_analysis():
        return service.get_portfolio_analysis_snapshot()

    @app.get(
        "/service/portfolio/history",
        response_model=PortfolioHistoryResponse,
        operation_id="get_portfolio_history",
    )
    def get_portfolio_history():
        return service.get_portfolio_history()

    @app.post(
        "/service/portfolio/rebalance",
        response_model=PortfolioRebalanceResponse,
        operation_id="rebalance_portfolio",
    )
    def rebalance_portfolio(request: PortfolioRebalanceRequest):
        return service.rebalance_portfolio(
            as_of_date=request.as_of_date,
            preview_only=request.preview_only,
            symbols=request.symbols,
            force=request.force,
        )

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

    @app.get(
        "/service/scheduler-config",
        response_model=SchedulerConfigSnapshotResponse,
        operation_id="get_scheduler_config",
    )
    def get_scheduler_config():
        return service.get_scheduler_config_snapshot()

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

    @app.post(
        "/service/strategy-evaluate",
        response_model=StrategyEvaluateResponse,
        operation_id="evaluate_strategies",
    )
    def evaluate_strategies(request: StrategyEvaluateRequest):
        return service.evaluate_strategies(
            symbol_source=request.symbol_source,
            as_of_date=request.as_of_date,
            lookback_days=request.lookback_days,
            commission_rate=request.commission_rate,
            stamp_tax_rate=request.stamp_tax_rate,
        )

    @app.get(
        "/service/risk-management",
        response_model=RiskManagementConfigResponse,
        operation_id="get_risk_management_config",
    )
    def get_risk_management_config():
        return service.get_risk_management_config()

    @app.put(
        "/service/risk-management",
        response_model=RiskManagementConfigUpdateResponse,
        operation_id="update_risk_management_config",
    )
    def update_risk_management_config(request: RiskManagementConfigUpdateRequest):
        return service.update_risk_management_config(request.risk_management_specs)

    # ── Data API ──────────────────────────────────────────────

    @app.post("/data/count", response_model=DataCountResponse, operation_id="get_data_count")
    def data_count(request: DataCountRequest):
        return service.get_data_count(
            data_type=request.data_type,
            symbol=request.symbol,
            ts_code=request.ts_code,
            start=request.start,
            end=request.end,
        )

    @app.post("/data/query", response_model=DataQueryResponse, operation_id="get_data_query")
    def data_query(request: DataQueryRequest):
        return service.get_data_query(
            data_type=request.data_type,
            symbol=request.symbol,
            ts_code=request.ts_code,
            start=request.start,
            end=request.end,
            remote=request.remote,
        )

    @app.get("/data/types", response_model=DataTypesListResponse, operation_id="list_data_types")
    def data_types():
        return service.list_data_types()

    @app.get("/data/schema/{data_type}", response_model=DataSchemaResponse, operation_id="get_data_schema")
    def data_schema(data_type: str):
        return service.get_data_schema(data_type)

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
