from __future__ import annotations

from typing import Any, Dict, List

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - optional dependency at runtime
    FastAPI = None

try:
    import uvicorn
except ImportError:  # pragma: no cover - optional dependency at runtime
    uvicorn = None

from dataclasses import asdict

from .service import (
    FactorSelectionConfig,
    FixedUniverseSelectionConfig,
    LLMCommandRequest,
    ServiceConfig,
    SignalGatewayService,
    StrategySpec,
)


def create_service_app(service: SignalGatewayService):
    if FastAPI is None:
        raise ImportError("fastapi is required to create the service API")

    app = FastAPI(title="jh-quant SignalGateway Service")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/service/status")
    def service_status():
        return service.get_status()

    @app.get("/service/config")
    def service_config():
        return {
            "service_config": service.config.model_dump(),
            "selection_config": service.selection_config.model_dump(),
            "strategy_specs": [spec.model_dump() for spec in service.strategy_specs],
        }

    @app.post("/service/start")
    def service_start():
        service.start()
        return {"status": "started"}

    @app.post("/service/stop")
    def service_stop():
        service.stop()
        return {"status": "stopped"}

    @app.post("/service/run-once")
    def run_once():
        result = service.run_once()
        return asdict(result)

    @app.post("/service/strategy-config")
    def update_strategy_config(strategy_specs: List[StrategySpec]):
        service.configure_strategies(strategy_specs)
        return {"status": "updated", "count": len(strategy_specs)}

    @app.post("/service/selection-config/fixed")
    def update_fixed_selection(config: FixedUniverseSelectionConfig):
        service.configure_selection(config)
        return {"status": "updated", "mode": config.mode}

    @app.post("/service/selection-config/factor")
    def update_factor_selection(config: FactorSelectionConfig):
        service.configure_selection(config)
        return {"status": "updated", "mode": config.mode}

    @app.post("/service/llm/command")
    def llm_command(request: LLMCommandRequest):
        return service.handle_llm_command(request.command, request.context)

    return app


def run_service_app(
    service: SignalGatewayService,
    host: str = "127.0.0.1",
    port: int = 8000,
):
    if uvicorn is None:
        raise ImportError("uvicorn is required to run the service API")
    app = create_service_app(service)
    uvicorn.run(app, host=host, port=port)
