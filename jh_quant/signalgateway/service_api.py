from __future__ import annotations

from typing import List

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - optional dependency at runtime
    FastAPI = None

try:
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:  # pragma: no cover - optional dependency at runtime
    CORSMiddleware = None

try:
    import uvicorn
except ImportError:  # pragma: no cover - optional dependency at runtime
    uvicorn = None

from dataclasses import asdict

from .config import StrategySpec, SelectionSpec
from .models import (
    AnalyticsSnapshotResponse,
    HealthResponse,
    PerformanceSnapshotResponse,
    RuntimeSnapshotResponse,
    SchedulerConfigUpdateRequest,
    SchedulerConfigUpdateResponse,
    SelectionConfigUpdateResponse,
    SelectionSpec,
    ServiceActionResponse,
    ServiceConfigResponse,
    ServiceStatusResponse,
    StrategyConfigUpdateResponse,
    TradingCycleResultResponse,
)
from .service import SignalGatewayService
from .utils import print_service_startup_summary


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

    @app.get("/health", response_model=HealthResponse)
    def health():
        return HealthResponse(status="ok")

    @app.get("/service/status", response_model=ServiceStatusResponse)
    def service_status():
        return service.get_status()

    @app.get("/service/runtime", response_model=RuntimeSnapshotResponse)
    def service_runtime():
        return service.get_runtime_snapshot()

    @app.get("/service/performance", response_model=PerformanceSnapshotResponse)
    def service_performance():
        return service.get_performance_snapshot()

    @app.get("/service/analytics", response_model=AnalyticsSnapshotResponse)
    def service_analytics():
        return service.get_analysis_snapshot()

    @app.get("/service/config", response_model=ServiceConfigResponse)
    def service_config():
        return service.get_config_snapshot()

    @app.post("/service/start", response_model=ServiceActionResponse)
    def service_start():
        service.start()
        return ServiceActionResponse(status="started", session_id=service.config.session_id)

    @app.post("/service/stop", response_model=ServiceActionResponse)
    def service_stop():
        service.stop()
        return ServiceActionResponse(status="stopped", session_id=service.config.session_id)

    @app.post("/service/run-once", response_model=TradingCycleResultResponse)
    def run_once():
        result = service.run_once()
        return TradingCycleResultResponse(**asdict(result))

    @app.post("/service/strategy-config", response_model=StrategyConfigUpdateResponse)
    def update_strategy_config(strategy_specs: List[StrategySpec]):
        service.configure_strategies(strategy_specs)
        return StrategyConfigUpdateResponse(status="updated", count=len(strategy_specs))

    @app.post("/service/selection-config", response_model=SelectionConfigUpdateResponse)
    def update_selection_config(selection_spec: SelectionSpec):
        service.configure_selection(selection_spec)
        return SelectionConfigUpdateResponse(
            status="updated",
            name=selection_spec.name,
            alias=selection_spec.alias,
        )

    @app.get("/service/selection-config")
    def get_selection_config():
        """Get current selection provider configuration"""
        return {
            "selection_provider": getattr(service.selection_provider, "config", {}),
        }

    @app.post("/service/scheduler-config", response_model=SchedulerConfigUpdateResponse)
    def update_scheduler_config(request: SchedulerConfigUpdateRequest):
        return service.update_scheduler_config(
            interval_seconds=request.interval_seconds,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            auto_start=request.auto_start,
        )



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
