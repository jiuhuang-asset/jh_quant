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

from .config import StrategySpec, SelectionSpec
from .models import (
    AnalyticsSnapshotResponse,
    CloseAllPositionsRequest,
    CloseAllPositionsResponse,
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
    SingleSymbolTradeRequest,
    SingleSymbolTradeResponse,
    StrategyConfigUpdateResponse,
    TradingCycleResultResponse,
)
from .service import SignalGatewayService
from .utils import print_service_startup_summary


def _mount_mcp_server(app) -> None:
    if FastApiMCP is None:
        raise ImportError("fastapi-mcp is required to expose the service API as MCP")

    mcp = FastApiMCP(app)
    mount_http = getattr(mcp, "mount_http", None)
    if callable(mount_http):
        mount_http()
    else:  # pragma: no cover - compatibility with older fastapi-mcp releases
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

    @app.get(
        "/health",
        response_model=HealthResponse,
        operation_id="health_check",
        summary="检查服务健康状态",
        description="返回基础健康检查结果，用于确认 HTTP 服务可访问。",
    )
    def health():
        return HealthResponse(status="ok")

    @app.get(
        "/service/status",
        response_model=ServiceStatusResponse,
        operation_id="get_service_status",
        summary="查看服务状态",
        description="返回调度器运行状态、最近一次执行结果以及最近错误信息。",
    )
    def service_status():
        return service.get_status()

    @app.get(
        "/service/runtime",
        response_model=RuntimeSnapshotResponse,
        operation_id="get_service_runtime",
        summary="查看运行时持仓快照",
        description="返回当前持仓、账户状态以及 OMS 导出的运行时信息。",
    )
    def service_runtime():
        return service.get_runtime_snapshot()

    @app.get(
        "/service/performance",
        response_model=PerformanceSnapshotResponse,
        operation_id="get_service_performance",
        summary="查看绩效快照",
        description="返回收益、换手率、净值曲线和持仓暴露等绩效分析结果。",
    )
    def service_performance():
        return service.get_performance_snapshot()

    @app.get(
        "/service/analytics",
        response_model=AnalyticsSnapshotResponse,
        operation_id="get_service_analytics",
        summary="查看综合分析快照",
        description="聚合返回服务状态、运行时、绩效和配置快照，适合 agent 一次性读取全局状态。",
    )
    def service_analytics():
        return service.get_analysis_snapshot()

    @app.get(
        "/service/config",
        response_model=ServiceConfigResponse,
        operation_id="get_service_config",
        summary="查看当前服务配置",
        description="返回服务配置、选股器配置和已启用策略配置。",
    )
    def service_config():
        return service.get_config_snapshot()

    @app.post(
        "/service/start",
        response_model=ServiceActionResponse,
        operation_id="start_service",
        summary="启动调度服务",
        description="启动 SignalGateway 调度器。该操作有副作用，会开始按当前调度配置自动执行交易周期。",
    )
    def service_start():
        service.start()
        return ServiceActionResponse(status="started", session_id=service.config.session_id)

    @app.post(
        "/service/stop",
        response_model=ServiceActionResponse,
        operation_id="stop_service",
        summary="停止调度服务",
        description="停止 SignalGateway 调度器。该操作有副作用，会终止后续自动调度。",
    )
    def service_stop():
        service.stop()
        return ServiceActionResponse(status="stopped", session_id=service.config.session_id)

    @app.post(
        "/service/run-once",
        response_model=TradingCycleResultResponse,
        operation_id="run_service_once",
        summary="执行一次交易周期",
        description="立即执行一次选股、信号生成和订单处理流程，但不会改变调度器是否持续运行。",
    )
    def run_once():
        result = service.run_once()
        return TradingCycleResultResponse(**asdict(result))

    @app.post(
        "/service/strategy-config",
        response_model=StrategyConfigUpdateResponse,
        operation_id="update_strategy_config",
        summary="更新策略配置",
        description="使用新的策略列表替换当前策略配置。该操作有副作用，会影响后续交易周期的信号生成。",
    )
    def update_strategy_config(strategy_specs: List[StrategySpec]):
        service.configure_strategies(strategy_specs)
        return StrategyConfigUpdateResponse(status="updated", count=len(strategy_specs))

    @app.post(
        "/service/selection-config",
        response_model=SelectionConfigUpdateResponse,
        operation_id="update_selection_config",
        summary="更新选股器配置",
        description="切换或更新选股器配置。该操作有副作用，会影响后续候选标的集合。",
    )
    def update_selection_config(selection_spec: SelectionSpec):
        service.configure_selection(selection_spec)
        return SelectionConfigUpdateResponse(
            status="updated",
            name=selection_spec.name,
            alias=selection_spec.alias,
        )

    @app.get(
        "/service/selection-config",
        operation_id="get_selection_config",
        summary="查看选股器配置",
        description="返回当前选股器的配置快照。",
    )
    def get_selection_config():
        return {
            "selection_provider": getattr(service.selection_provider, "config", {}),
        }

    @app.post(
        "/service/scheduler-config",
        response_model=SchedulerConfigUpdateResponse,
        operation_id="update_scheduler_config",
        summary="更新调度配置",
        description="更新轮询间隔、cron 表达式、时区或自动启动配置。该操作有副作用，会影响后续自动执行时间。",
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
        summary="一键平掉全部持仓",
        description="按当前持仓批量发出卖出指令。该操作有强副作用，会尝试清空全部仓位。",
    )
    def close_all_positions(request: CloseAllPositionsRequest):
        return service.close_all_positions(slippage=request.slippage)

    @app.post(
        "/service/signal-buy",
        response_model=SingleSymbolTradeResponse,
        operation_id="signal_buy_symbol",
        summary="对单个标的执行买入信号",
        description="针对指定标的发出买入指令。该操作有副作用，会触发实际下单或模拟下单。",
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
        summary="对单个标的执行卖出信号",
        description="针对指定标的发出卖出指令。该操作有副作用，会触发实际下单或模拟下单。",
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
