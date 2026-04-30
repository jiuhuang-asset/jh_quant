from __future__ import annotations

import json as _json
from dataclasses import asdict
from typing import Optional

try:
    from fastapi import FastAPI, File, Response, UploadFile
except ImportError:  # pragma: no cover - optional dependency at runtime
    FastAPI = None
    File = None
    Response = None
    UploadFile = None

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

from ..config.io import (
    export_config_to_json_string,
    import_config_from_dict,
)
from ..utils import rprint
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


# ── helpers for data endpoints (app-level, no session_id) ──────

_MAX_DATA_QUERY_ROWS = 10_000


def _validate_data_type(data_type_str: str):
    from jh_quant.data import DataTypes

    try:
        return DataTypes(data_type_str)
    except ValueError:
        raise ValueError(
            f"Unknown data_type '{data_type_str}'. "
            f"Use GET /data/types to list available types."
        )


# ── unified route registration ─────────────────────────────────


def _register_service_routes(app, manager: MultiServiceManager):
    """Register all service endpoints on a FastAPI app.

    All session-scoped endpoints live under ``/services/{session_id}/*``.
    Data endpoints are app-level (shared data provider).
    """

    # ── app-level endpoints ─────────────────────────────────

    @app.get("/health", response_model=HealthResponse, operation_id="health_check")
    def health():
        return HealthResponse(status="ok")

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

    # ── data endpoints ─────────────────────────────────────

    @app.post("/data/count", response_model=DataCountResponse, operation_id="get_data_count")
    def data_count(request: DataCountRequest):
        jhd = manager._resolve_jhdata()
        dt = _validate_data_type(request.data_type)
        kwargs = {}
        if request.symbol:
            kwargs["symbol"] = request.symbol
        if request.ts_code:
            kwargs["ts_code"] = request.ts_code
        if request.start:
            kwargs["start"] = request.start
        if request.end:
            kwargs["end"] = request.end
        count = jhd.get_data_total(dt, **kwargs)
        return DataCountResponse(data_type=request.data_type, count=count).model_dump()

    @app.post("/data/query", response_model=DataQueryResponse, operation_id="get_data_query")
    def data_query(request: DataQueryRequest):
        jhd = manager._resolve_jhdata()
        dt = _validate_data_type(request.data_type)
        kwargs = {}
        if request.symbol:
            kwargs["symbol"] = request.symbol
        if request.ts_code:
            kwargs["ts_code"] = request.ts_code
        if request.start:
            kwargs["start"] = request.start
        if request.end:
            kwargs["end"] = request.end

        total = jhd.get_data_total(dt, **kwargs)
        if total == 0:
            return DataQueryResponse(
                status="empty",
                data_type=request.data_type,
                count=0,
                message="No data available for the given parameters.",
            ).model_dump()

        if total > _MAX_DATA_QUERY_ROWS:
            return DataQueryResponse(
                status="too_large",
                data_type=request.data_type,
                count=total,
                message=f"Data count ({total}) exceeds the maximum direct-return threshold ({_MAX_DATA_QUERY_ROWS}).",
                suggestion="Please narrow your query by providing one or more of: symbol, ts_code, start, end.",
            ).model_dump()

        df = jhd.get_data(dt, remote=request.remote, **kwargs)
        if df is None or (hasattr(df, "empty") and df.empty):
            return DataQueryResponse(
                status="empty",
                data_type=request.data_type,
                count=0,
                message="No data returned after fetch.",
            ).model_dump()

        if hasattr(df, "to_df"):
            df = df.to_df()
        records = df.to_dict(orient="records")
        return DataQueryResponse(
            status="ok",
            data_type=request.data_type,
            count=len(records),
            data=records,
            message=f"Returned {len(records)} rows.",
        ).model_dump()

    @app.get("/data/types", response_model=DataTypesListResponse, operation_id="list_data_types")
    def data_types():
        from jh_quant.data import DataTypes

        types = [
            {"value": dt.value, "name": dt.name}
            for dt in DataTypes
        ]
        return DataTypesListResponse(types=types, count=len(types)).model_dump()

    @app.get("/data/schema/{data_type}", response_model=DataSchemaResponse, operation_id="get_data_schema")
    def data_schema(data_type: str):
        from jh_quant.data.data_types import get_table_fields, get_table_unique_keys, get_table_dt_field

        dt = _validate_data_type(data_type)
        fields = get_table_fields(dt)
        unique_keys = get_table_unique_keys(dt)
        dt_field = get_table_dt_field(dt)
        return DataSchemaResponse(
            data_type=data_type,
            fields=fields,
            unique_keys=unique_keys,
            dt_field=dt_field,
        ).model_dump()

    # ── session-scoped endpoints ────────────────────────────

    @app.delete("/services/{session_id}", response_model=ServiceRemoveResponse, operation_id="remove_service")
    def remove_service(session_id: str):
        manager.remove_service(session_id)
        return ServiceRemoveResponse(status="removed", session_id=session_id)

    @app.get("/services/{session_id}/status", response_model=ServiceStatusResponse, operation_id="get_service_status")
    def service_status(session_id: str):
        return manager.get_service(session_id).get_status()

    @app.get("/services/{session_id}/runtime", response_model=RuntimeSnapshotResponse, operation_id="get_service_runtime")
    def service_runtime(session_id: str):
        return manager.get_service(session_id).get_runtime_snapshot()

    @app.get("/services/{session_id}/performance", response_model=PerformanceSnapshotResponse, operation_id="get_service_performance")
    def service_performance(session_id: str):
        return manager.get_service(session_id).get_performance_snapshot()

    @app.get("/services/{session_id}/analytics", response_model=AnalyticsSnapshotResponse, operation_id="get_service_analytics")
    def service_analytics(session_id: str):
        return manager.get_service(session_id).get_analysis_snapshot()

    @app.get("/services/{session_id}/config", response_model=ServiceConfigResponse, operation_id="get_service_config")
    def service_config(session_id: str):
        return manager.get_service(session_id).get_config_snapshot()

    @app.put("/services/{session_id}/config", response_model=ServiceConfigUpdateResponse, operation_id="replace_service_config")
    def replace_service_config(session_id: str, request: ServiceConfigUpdateRequest):
        return manager.get_service(session_id).replace_service_config(request.config_bundle)

    @app.post("/services/{session_id}/config/import", response_model=ServiceConfigUpdateResponse, operation_id="import_service_config")
    async def import_service_config(session_id: str, file: UploadFile = File(...)):
        payload = await file.read()
        config_dict = _json.loads(payload)
        config_bundle = import_config_from_dict(config_dict)
        return manager.get_service(session_id).replace_service_config(config_bundle)

    @app.get("/services/{session_id}/config/export", operation_id="export_service_config")
    def export_service_config(session_id: str):
        svc = manager.get_service(session_id)
        json_str = export_config_to_json_string(svc.service_config)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=service-config-{session_id}.json"
            },
        )

    @app.get("/services/{session_id}/events", response_model=ServiceEventHistoryResponse, operation_id="get_service_events")
    def get_service_events(session_id: str):
        return manager.get_service(session_id).get_service_event_history()

    @app.post("/services/{session_id}/scheduler/start", response_model=ServiceActionResponse, operation_id="start_service_scheduler")
    def service_start(session_id: str):
        svc = manager.get_service(session_id)
        svc.start_scheduler()
        return ServiceActionResponse(status="started", session_id=session_id)

    @app.post("/services/{session_id}/scheduler/stop", response_model=ServiceActionResponse, operation_id="stop_service_scheduler")
    def service_stop(session_id: str):
        svc = manager.get_service(session_id)
        svc.stop_scheduler()
        return ServiceActionResponse(status="stopped", session_id=session_id)

    @app.post("/services/{session_id}/run-once", response_model=TradingCycleResultResponse, operation_id="run_service_once")
    def run_once(session_id: str):
        result = manager.get_service(session_id).run_once()
        return TradingCycleResultResponse(**asdict(result))

    @app.get("/services/{session_id}/strategy-config", response_model=StrategyConfigSnapshotResponse, operation_id="get_strategy_config")
    def get_strategy_config(session_id: str):
        return manager.get_service(session_id).get_strategy_config_snapshot()

    @app.post("/services/{session_id}/strategy-config", response_model=StrategyConfigUpdateResponse, operation_id="update_strategy_config")
    def update_strategy_config(session_id: str, request: StrategyConfigUpdateRequest):
        svc = manager.get_service(session_id)
        svc.configure_strategies(request.strategy_specs)
        return StrategyConfigUpdateResponse(
            status="updated",
            count=len(request.strategy_specs),
            strategy_specs=svc.strategy_specs,
        )

    @app.get("/services/{session_id}/selection-config", response_model=SelectionConfigSnapshotResponse, operation_id="get_selection_config")
    def get_selection_config(session_id: str):
        return manager.get_service(session_id).get_selection_config_snapshot()

    @app.post("/services/{session_id}/selection-config", response_model=SelectionConfigUpdateResponse, operation_id="update_selection_config")
    def update_selection_config(session_id: str, request: SelectionConfigUpdateRequest):
        svc = manager.get_service(session_id)
        selection_spec = request.selection_spec
        svc.configure_selection(selection_spec)
        return SelectionConfigUpdateResponse(
            status="updated",
            name=selection_spec.name,
            alias=selection_spec.alias,
            selection_spec=svc.selection_specs,
        )

    @app.get("/services/{session_id}/portfolio/config", response_model=PortfolioConfigSnapshotResponse, operation_id="get_portfolio_config")
    def get_portfolio_config(session_id: str):
        return manager.get_service(session_id).get_portfolio_config_snapshot()

    @app.post("/services/{session_id}/portfolio/config", response_model=PortfolioConfigUpdateResponse, operation_id="update_portfolio_config")
    def update_portfolio_config(session_id: str, request: PortfolioConfigUpdateRequest):
        svc = manager.get_service(session_id)
        svc.configure_portfolio(request.portfolio_spec)
        return PortfolioConfigUpdateResponse(
            status="updated",
            portfolio_spec=svc.portfolio_spec,
        )

    @app.post("/services/{session_id}/portfolio/optimize", response_model=PortfolioOptimizeResponse, operation_id="optimize_portfolio")
    def optimize_portfolio(session_id: str, request: PortfolioOptimizeRequest):
        return manager.get_service(session_id).optimize_portfolio(
            as_of_date=request.as_of_date,
            preview_only=request.preview_only,
            symbols=request.symbols,
        )

    @app.get("/services/{session_id}/portfolio/analysis", response_model=PortfolioAnalysisResponse, operation_id="get_portfolio_analysis")
    def get_portfolio_analysis(session_id: str):
        return manager.get_service(session_id).get_portfolio_analysis_snapshot()

    @app.get("/services/{session_id}/portfolio/history", response_model=PortfolioHistoryResponse, operation_id="get_portfolio_history")
    def get_portfolio_history(session_id: str):
        return manager.get_service(session_id).get_portfolio_history()

    @app.post("/services/{session_id}/portfolio/rebalance", response_model=PortfolioRebalanceResponse, operation_id="rebalance_portfolio")
    def rebalance_portfolio(session_id: str, request: PortfolioRebalanceRequest):
        return manager.get_service(session_id).rebalance_portfolio(
            as_of_date=request.as_of_date,
            preview_only=request.preview_only,
            symbols=request.symbols,
            force=request.force,
        )

    @app.get("/services/{session_id}/scheduler-config", response_model=SchedulerConfigSnapshotResponse, operation_id="get_scheduler_config")
    def get_scheduler_config(session_id: str):
        return manager.get_service(session_id).get_scheduler_config_snapshot()

    @app.post("/services/{session_id}/scheduler-config", response_model=SchedulerConfigUpdateResponse, operation_id="update_scheduler_config")
    def update_scheduler_config(session_id: str, request: SchedulerConfigUpdateRequest):
        return manager.get_service(session_id).update_scheduler_config(
            interval_seconds=request.interval_seconds,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            auto_start=request.auto_start,
        )

    @app.post("/services/{session_id}/close-all-positions", response_model=CloseAllPositionsResponse, operation_id="close_all_positions")
    def close_all_positions(session_id: str, request: CloseAllPositionsRequest):
        return manager.get_service(session_id).close_all_positions(slippage=request.slippage)

    @app.post("/services/{session_id}/signal-buy", response_model=SingleSymbolTradeResponse, operation_id="signal_buy_symbol")
    def signal_buy_symbol(session_id: str, request: SingleSymbolTradeRequest):
        return manager.get_service(session_id).signal_buy_symbol(
            symbol=request.symbol,
            target_qty=request.target_qty,
            slippage=request.slippage,
        )

    @app.post("/services/{session_id}/signal-sell", response_model=SingleSymbolTradeResponse, operation_id="signal_sell_symbol")
    def signal_sell_symbol(session_id: str, request: SingleSymbolTradeRequest):
        return manager.get_service(session_id).signal_sell_symbol(
            symbol=request.symbol,
            target_qty=request.target_qty,
            slippage=request.slippage,
        )

    @app.post("/services/{session_id}/strategy-evaluate", response_model=StrategyEvaluateResponse, operation_id="evaluate_strategies")
    def evaluate_strategies(session_id: str, request: StrategyEvaluateRequest):
        return manager.get_service(session_id).evaluate_strategies(
            symbol_source=request.symbol_source,
            as_of_date=request.as_of_date,
            lookback_days=request.lookback_days,
            commission_rate=request.commission_rate,
            stamp_tax_rate=request.stamp_tax_rate,
        )

    @app.get("/services/{session_id}/risk-management", response_model=RiskManagementConfigResponse, operation_id="get_risk_management_config")
    def get_risk_management_config(session_id: str):
        return manager.get_service(session_id).get_risk_management_config()

    @app.put("/services/{session_id}/risk-management", response_model=RiskManagementConfigUpdateResponse, operation_id="update_risk_management_config")
    def update_risk_management_config(session_id: str, request: RiskManagementConfigUpdateRequest):
        return manager.get_service(session_id).update_risk_management_config(request.risk_management_specs)


# ── app factory ──────────────────────────────────────────────


def _create_base_app(title: str):
    """Create a FastAPI app with CORS middleware."""
    if FastAPI is None:
        raise ImportError("fastapi is required to create the service API")

    app = FastAPI(title=title)
    if CORSMiddleware is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return app


def create_service_app(service: SignalGatewayService):
    """Create a FastAPI app for a single service.

    Internally wraps the service in a :class:`MultiServiceManager` so all
    routes follow the ``/services/{session_id}/*`` pattern.
    """
    manager = MultiServiceManager(max_services=1)
    manager.wrap_service(service)
    return create_unified_app(manager)


def create_unified_app(manager: MultiServiceManager):
    """Create a FastAPI app with all unified routes registered."""
    app = _create_base_app(title="jh-quant SignalGateway Service")
    _register_service_routes(app, manager)
    _mount_mcp_server(app)
    return app


# Backward-compatible alias (used by tests / external callers)
create_multi_service_app = create_unified_app


def run_service_app(
    service: Optional[SignalGatewayService] = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    manager: Optional[MultiServiceManager] = None,
):
    """Launch the service API via uvicorn.

    Prefer passing *manager* directly. When *service* is provided instead,
    it is automatically wrapped in a single-service manager.
    """
    if uvicorn is None:
        raise ImportError("uvicorn is required to run the service API")

    if manager is None:
        if service is None:
            raise ValueError("Either 'service' or 'manager' must be provided")
        manager = MultiServiceManager(max_services=1)
        manager.wrap_service(service)

    services = manager.list_services()
    rprint(
        label="Service",
        content=f"Managing {services.count} service(s), max={services.max_services}",
    )
    for svc_info in services.services:
        rprint(
            label=f"  [{svc_info.session_id}]",
            content=f"mode={svc_info.mode}, running={svc_info.running}",
        )

    app = create_unified_app(manager)
    uvicorn.run(app, host=host, port=port)
