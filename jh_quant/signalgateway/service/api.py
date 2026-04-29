from __future__ import annotations

from dataclasses import asdict
from typing import Optional
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

from ..utils import print_service_startup_summary, rprint
from .core import MultiServiceManager, SignalGatewayService
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
    PerformanceComparisonResponse,
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
    ServiceComparisonResponse,
    ServiceConfigResponse,
    ServiceConfigUpdateRequest,
    ServiceConfigUpdateResponse,
    ServiceCreateRequest,
    ServiceCreateResponse,
    ServiceEventHistoryResponse,
    ServiceInfoResponse,
    ServiceListResponse,
    ServiceRemoveResponse,
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


# ── Multi-service API ──────────────────────────────────────────


def _register_multi_service_routes(app, manager: MultiServiceManager):
    """Register multi-service management endpoints on an existing FastAPI app."""

    @app.get("/services", response_model=ServiceListResponse, operation_id="list_services")
    def list_services():
        return manager.list_services()

    @app.post("/services", response_model=ServiceCreateResponse, operation_id="create_service")
    def create_service(request: ServiceCreateRequest):
        sid = manager.create_service(
            config=request.config_bundle,
            initial_capital=request.initial_capital,
        )
        return ServiceCreateResponse(status="created", session_id=sid)

    @app.delete("/services/{session_id}", response_model=ServiceRemoveResponse, operation_id="remove_service")
    def remove_service(session_id: str):
        manager.remove_service(session_id)
        return ServiceRemoveResponse(status="removed", session_id=session_id)

    @app.get("/services/{session_id}/status", response_model=ServiceStatusResponse, operation_id="get_service_status_multi")
    def service_status(session_id: str):
        return manager.get_service(session_id).get_status()

    @app.post("/services/{session_id}/scheduler/start", response_model=ServiceActionResponse, operation_id="start_service_scheduler_multi")
    def service_start(session_id: str):
        svc = manager.get_service(session_id)
        svc.start_scheduler()
        return ServiceActionResponse(status="started", session_id=session_id)

    @app.post("/services/{session_id}/scheduler/stop", response_model=ServiceActionResponse, operation_id="stop_service_scheduler_multi")
    def service_stop(session_id: str):
        svc = manager.get_service(session_id)
        svc.stop_scheduler()
        return ServiceActionResponse(status="stopped", session_id=session_id)

    @app.post("/services/{session_id}/run-once", response_model=TradingCycleResultResponse, operation_id="run_service_once_multi")
    def run_once(session_id: str):
        result = manager.get_service(session_id).run_once()
        return TradingCycleResultResponse(**asdict(result))

    @app.get("/services/{session_id}/performance", response_model=PerformanceSnapshotResponse, operation_id="get_service_performance_multi")
    def service_performance(session_id: str):
        return manager.get_service(session_id).get_performance_snapshot()

    @app.get("/services/{session_id}/runtime", response_model=RuntimeSnapshotResponse, operation_id="get_service_runtime_multi")
    def service_runtime(session_id: str):
        return manager.get_service(session_id).get_runtime_snapshot()

    @app.get("/services/{session_id}/config", response_model=ServiceConfigResponse, operation_id="get_service_config_multi")
    def service_config(session_id: str):
        return manager.get_service(session_id).get_config_snapshot()

    @app.get("/services/compare", response_model=ServiceComparisonResponse, operation_id="compare_services")
    def compare_services():
        return manager.get_comparison()

    @app.get(
        "/services/performance/compare",
        response_model=PerformanceComparisonResponse,
        operation_id="compare_performance",
    )
    def compare_performance(
        session_ids: Optional[str] = None,
        limit: int = 8,
    ):
        ids = (
            [s.strip() for s in session_ids.split(",") if s.strip()]
            if session_ids
            else None
        )
        return manager.get_performance_comparison(session_ids=ids, limit=limit)


def create_multi_service_app(manager: MultiServiceManager):
    """Create a FastAPI app that manages multiple SignalGatewayService instances."""
    if FastAPI is None:
        raise ImportError("fastapi is required to create the service API")

    app = FastAPI(title="jh-quant Multi-Service Manager")
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

    _register_multi_service_routes(app, manager)
    _mount_mcp_server(app)

    return app


def run_service_app(
    service: Optional[SignalGatewayService] = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    manager: Optional[MultiServiceManager] = None,
):
    if uvicorn is None:
        raise ImportError("uvicorn is required to run the service API")

    if manager is not None:
        app = create_multi_service_app(manager)
        services = manager.list_services()
        rprint(label="Multi-Service", content=f"Managing {services.count} service(s), max={services.max_services}")
        for svc_info in services.services:
            rprint(label=f"  [{svc_info.session_id}]", content=f"mode={svc_info.mode}, running={svc_info.running}")
        uvicorn.run(app, host=host, port=port)
        return

    if service is None:
        raise ValueError("Either 'service' or 'manager' must be provided")

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
