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
from .core import MultiSessionService, SessionService
from .schemas import (
    AnalyticsSnapshotResponse,
    CloseAllPositionsRequest,
    CloseAllPositionsResponse,
    DataListResponse,
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
    RuntimeSnapshotResponse,
    SchedulerConfigSnapshotResponse,
    SchedulerConfigUpdateRequest,
    SchedulerConfigUpdateResponse,
    SelectionConfigUpdateResponse,
    SelectionConfigUpdateRequest,
    SelectionConfigSnapshotResponse,
    SessionActionResponse,
    SessionConfigResponse,
    SessionConfigUpdateRequest,
    SessionConfigUpdateResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionEventHistoryResponse,
    SessionListResponse,
    SessionRemoveResponse,
    SessionStatusResponse,
    SessionTrendsResponse,
    SingleSymbolTradeRequest,
    SingleSymbolTradeResponse,
    StrategyConfigSnapshotResponse,
    StrategyConfigUpdateRequest,
    StrategyConfigUpdateResponse,
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


def _resolve_md_provider(manager: MultiSessionService):
    """Resolve a JHMarketDataProvider from the manager or its sessions."""
    from ..market_data import JHMarketDataProvider

    if manager._shared_md_provider is not None and isinstance(
        manager._shared_md_provider, JHMarketDataProvider
    ):
        return manager._shared_md_provider

    with manager._lock:
        for svc in manager._sessions.values():
            provider = getattr(svc.gateway, "market_data_provider", None)
            if isinstance(provider, JHMarketDataProvider):
                return provider

    return JHMarketDataProvider()


def _df_to_records(df, date_col: str = "date") -> list:
    """Convert a DataFrame to a list of JSON-serializable dicts."""
    if df is None or df.empty:
        return []
    import pandas as pd

    normalized = df.copy()
    for col in normalized.columns:
        if pd.api.types.is_datetime64_any_dtype(normalized[col]):
            normalized[col] = normalized[col].apply(
                lambda v: v.strftime("%Y-%m-%d") if pd.notna(v) else None
            )
    records = normalized.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if isinstance(v, float) and (pd.isna(v) or v != v):
                r[k] = None
    return records


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


def _register_session_routes(app, manager: MultiSessionService):
    """Register all session endpoints on a FastAPI app.

    All session-scoped endpoints live under ``/sessions/{session_id}/*``.
    Data endpoints are app-level (shared data provider).
    """

    # ── app-level endpoints ─────────────────────────────────

    @app.get("/health", response_model=HealthResponse, operation_id="health_check")
    def health():
        return HealthResponse(status="ok")

    @app.get(
        "/sessions", response_model=SessionListResponse, operation_id="list_sessions"
    )
    def list_sessions():
        return manager.list_sessions()

    @app.post(
        "/sessions", response_model=SessionCreateResponse, operation_id="create_session"
    )
    def create_session(request: SessionCreateRequest):
        sid = manager.create_session(
            config=request.config_bundle,
            initial_capital=request.initial_capital,
        )
        return SessionCreateResponse(status="created", session_id=sid)

    @app.get(
        "/sessions/trends",
        response_model=SessionTrendsResponse,
        operation_id="get_session_trends",
    )
    def get_session_trends(
        session_ids: Optional[str] = None,
        limit: int = 8,
        days: Optional[int] = None,
    ):
        ids = (
            [s.strip() for s in session_ids.split(",") if s.strip()]
            if session_ids
            else None
        )
        return manager.get_session_trends(session_ids=ids, limit=limit, days=days)

    # ── data endpoints (app-level) ───────────────────────────

    @app.get(
        "/data/index/{symbol}",
        response_model=DataListResponse,
        operation_id="get_index_trends",
    )
    def get_index_trends(
        symbol: str,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
    ):
        from datetime import datetime as _dt

        md = _resolve_md_provider(manager)
        _end = end_date or _dt.now().strftime("%Y-%m-%d")
        df = md.get_index_trends(symbol=symbol, start_date=start_date, end_date=_end)
        records = _df_to_records(df)
        return DataListResponse(data=records, count=len(records))

    @app.get(
        "/data/stock",
        response_model=DataListResponse,
        operation_id="get_stock_price_data",
    )
    def get_stock_price_data(
        symbols: str,
        start_date: str = "2020-01-01",
        end_date: Optional[str] = None,
        frequency: Optional[str] = None,
    ):
        from datetime import datetime as _dt
        from ..config import Frequency

        md = _resolve_md_provider(manager)
        _end = end_date or _dt.now().strftime("%Y-%m-%d")
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        freq = Frequency(frequency) if frequency else Frequency.DAILY
        df = md.get_price_data(
            symbols=sym_list, start_date=start_date, end_date=_end, frequency=freq
        )
        records = _df_to_records(df)
        return DataListResponse(data=records, count=len(records))

    # ── session-scoped endpoints ────────────────────────────

    @app.delete(
        "/sessions/{session_id}",
        response_model=SessionRemoveResponse,
        operation_id="remove_service",
    )
    def remove_service(session_id: str):
        manager.remove_session(session_id)
        return SessionRemoveResponse(status="removed", session_id=session_id)

    @app.get(
        "/sessions/{session_id}/status",
        response_model=SessionStatusResponse,
        operation_id="get_session_status",
    )
    def session_status(session_id: str):
        return manager.get_session(session_id).get_status()

    @app.get(
        "/sessions/{session_id}/runtime",
        response_model=RuntimeSnapshotResponse,
        operation_id="get_session_runtime",
    )
    def session_runtime(session_id: str):
        return manager.get_session(session_id).get_runtime_snapshot()

    @app.get(
        "/sessions/{session_id}/performance",
        response_model=PerformanceSnapshotResponse,
        operation_id="get_session_performance",
    )
    def session_performance(session_id: str):
        return manager.get_session(session_id).get_performance_snapshot()

    @app.get(
        "/sessions/{session_id}/analytics",
        response_model=AnalyticsSnapshotResponse,
        operation_id="get_session_analytics",
    )
    def session_analytics(session_id: str):
        return manager.get_session(session_id).get_analysis_snapshot()

    @app.get(
        "/sessions/{session_id}/config",
        response_model=SessionConfigResponse,
        operation_id="get_session_config",
    )
    def session_config(session_id: str):
        return manager.get_session(session_id).get_config_snapshot()

    @app.put(
        "/sessions/{session_id}/config",
        response_model=SessionConfigUpdateResponse,
        operation_id="replace_session_config",
    )
    def replace_session_config(session_id: str, request: SessionConfigUpdateRequest):
        return manager.get_session(session_id).replace_session_config(
            request.config_bundle
        )

    @app.post(
        "/sessions/{session_id}/config/import",
        response_model=SessionConfigUpdateResponse,
        operation_id="import_session_config",
    )
    async def import_session_config(session_id: str, file: UploadFile = File(...)):
        payload = await file.read()
        config_dict = _json.loads(payload)
        config_bundle = import_config_from_dict(config_dict)
        return manager.get_session(session_id).replace_session_config(config_bundle)

    @app.get(
        "/sessions/{session_id}/config/export", operation_id="export_session_config"
    )
    def export_session_config(session_id: str):
        svc = manager.get_session(session_id)
        json_str = export_config_to_json_string(svc.session_config)
        return Response(
            content=json_str,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=service-config-{session_id}.json"
            },
        )

    @app.get(
        "/sessions/{session_id}/events",
        response_model=SessionEventHistoryResponse,
        operation_id="get_session_events",
    )
    def get_session_events(session_id: str):
        return manager.get_session(session_id).get_session_event_history()

    @app.post(
        "/sessions/{session_id}/scheduler/start",
        response_model=SessionActionResponse,
        operation_id="start_session_scheduler",
    )
    def session_start_schedule(session_id: str):
        svc = manager.get_session(session_id)
        svc.start_scheduler()
        return SessionActionResponse(status="started", session_id=session_id)

    @app.post(
        "/sessions/{session_id}/scheduler/stop",
        response_model=SessionActionResponse,
        operation_id="stop_session_scheduler",
    )
    def session_stop_schedule(session_id: str):
        svc = manager.get_session(session_id)
        svc.stop_scheduler()
        return SessionActionResponse(status="stopped", session_id=session_id)

    @app.post(
        "/sessions/{session_id}/run-once",
        response_model=TradingCycleResultResponse,
        operation_id="run_session_once",
    )
    def run_once(session_id: str):
        result = manager.get_session(session_id).run_once()
        return TradingCycleResultResponse(**asdict(result))

    @app.get(
        "/sessions/{session_id}/strategy-config",
        response_model=StrategyConfigSnapshotResponse,
        operation_id="get_strategy_config",
    )
    def get_strategy_config(session_id: str):
        return manager.get_session(session_id).get_strategy_config_snapshot()

    @app.post(
        "/sessions/{session_id}/strategy-config",
        response_model=StrategyConfigUpdateResponse,
        operation_id="update_strategy_config",
    )
    def update_strategy_config(session_id: str, request: StrategyConfigUpdateRequest):
        svc = manager.get_session(session_id)
        svc.configure_strategies(request.strategy_specs)
        return StrategyConfigUpdateResponse(
            status="updated",
            count=len(request.strategy_specs),
            strategy_specs=svc.strategy_specs,
        )

    @app.get(
        "/sessions/{session_id}/selection-config",
        response_model=SelectionConfigSnapshotResponse,
        operation_id="get_selection_config",
    )
    def get_selection_config(session_id: str):
        return manager.get_session(session_id).get_selection_config_snapshot()

    @app.post(
        "/sessions/{session_id}/selection-config",
        response_model=SelectionConfigUpdateResponse,
        operation_id="update_selection_config",
    )
    def update_selection_config(session_id: str, request: SelectionConfigUpdateRequest):
        svc = manager.get_session(session_id)
        selection_spec = request.selection_spec
        svc.configure_selection(selection_spec)
        return SelectionConfigUpdateResponse(
            status="updated",
            name=selection_spec.name,
            alias=selection_spec.alias,
            selection_spec=svc.selection_specs,
        )

    @app.get(
        "/sessions/{session_id}/portfolio/config",
        response_model=PortfolioConfigSnapshotResponse,
        operation_id="get_portfolio_config",
    )
    def get_portfolio_config(session_id: str):
        return manager.get_session(session_id).get_portfolio_config_snapshot()

    @app.post(
        "/sessions/{session_id}/portfolio/config",
        response_model=PortfolioConfigUpdateResponse,
        operation_id="update_portfolio_config",
    )
    def update_portfolio_config(session_id: str, request: PortfolioConfigUpdateRequest):
        svc = manager.get_session(session_id)
        svc.configure_portfolio(request.portfolio_spec)
        return PortfolioConfigUpdateResponse(
            status="updated",
            portfolio_spec=svc.portfolio_spec,
        )

    @app.post(
        "/sessions/{session_id}/portfolio/optimize",
        response_model=PortfolioOptimizeResponse,
        operation_id="optimize_portfolio",
    )
    def optimize_portfolio(session_id: str, request: PortfolioOptimizeRequest):
        return manager.get_session(session_id).optimize_portfolio(
            as_of_date=request.as_of_date,
            preview_only=request.preview_only,
            symbols=request.symbols,
        )

    @app.get(
        "/sessions/{session_id}/portfolio/analysis",
        response_model=PortfolioAnalysisResponse,
        operation_id="get_portfolio_analysis",
    )
    def get_portfolio_analysis(session_id: str):
        return manager.get_session(session_id).get_portfolio_analysis_snapshot()

    @app.get(
        "/sessions/{session_id}/portfolio/history",
        response_model=PortfolioHistoryResponse,
        operation_id="get_portfolio_history",
    )
    def get_portfolio_history(session_id: str):
        return manager.get_session(session_id).get_portfolio_history()

    @app.post(
        "/sessions/{session_id}/portfolio/rebalance",
        response_model=PortfolioRebalanceResponse,
        operation_id="rebalance_portfolio",
    )
    def rebalance_portfolio(session_id: str, request: PortfolioRebalanceRequest):
        return manager.get_session(session_id).rebalance_portfolio(
            as_of_date=request.as_of_date,
            preview_only=request.preview_only,
            symbols=request.symbols,
            force=request.force,
        )

    @app.get(
        "/sessions/{session_id}/scheduler-config",
        response_model=SchedulerConfigSnapshotResponse,
        operation_id="get_scheduler_config",
    )
    def get_scheduler_config(session_id: str):
        return manager.get_session(session_id).get_scheduler_config_snapshot()

    @app.post(
        "/sessions/{session_id}/scheduler-config",
        response_model=SchedulerConfigUpdateResponse,
        operation_id="update_scheduler_config",
    )
    def update_scheduler_config(session_id: str, request: SchedulerConfigUpdateRequest):
        return manager.get_session(session_id).update_scheduler_config(
            interval_seconds=request.interval_seconds,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            auto_start=request.auto_start,
        )

    @app.post(
        "/sessions/{session_id}/close-all-positions",
        response_model=CloseAllPositionsResponse,
        operation_id="close_all_positions",
    )
    def close_all_positions(session_id: str, request: CloseAllPositionsRequest):
        return manager.get_session(session_id).close_all_positions(
            slippage=request.slippage
        )

    @app.post(
        "/sessions/{session_id}/signal-buy",
        response_model=SingleSymbolTradeResponse,
        operation_id="signal_buy_symbol",
    )
    def signal_buy_symbol(session_id: str, request: SingleSymbolTradeRequest):
        return manager.get_session(session_id).signal_buy_symbol(
            symbol=request.symbol,
            target_qty=request.target_qty,
            slippage=request.slippage,
        )

    @app.post(
        "/sessions/{session_id}/signal-sell",
        response_model=SingleSymbolTradeResponse,
        operation_id="signal_sell_symbol",
    )
    def signal_sell_symbol(session_id: str, request: SingleSymbolTradeRequest):
        return manager.get_session(session_id).signal_sell_symbol(
            symbol=request.symbol,
            target_qty=request.target_qty,
            slippage=request.slippage,
        )


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


def create_session_app(session: SessionService):
    """Create a FastAPI app for a single session.

    Internally wraps the session in a :class:`MultiSessionService` so all
    routes follow the ``/sessions/{session_id}/*`` pattern.
    """
    manager = MultiSessionService(max_sessions=1)
    manager.wrap_session(session)
    return create_unified_app(manager)


def create_unified_app(manager: MultiSessionService):
    """Create a FastAPI app with all unified routes registered."""
    app = _create_base_app(title="jh-quant Gateway")
    _register_session_routes(app, manager)
    _mount_mcp_server(app)
    return app


# Backward-compatible alias (used by tests / external callers)
create_multi_session_app = create_unified_app


def run_gateway_app(
    session: Optional[SessionService] = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    manager: Optional[MultiSessionService] = None,
):
    """Launch the gateway API via uvicorn.

    Prefer passing *manager* directly. When *session* is provided instead,
    it is automatically wrapped in a single-session manager.

    On server exit (including ``KeyboardInterrupt``) all scheduler threads
    are stopped and persistence connections are closed.
    """
    if uvicorn is None:
        raise ImportError("uvicorn is required to run the gateway API")

    if manager is None:
        if session is None:
            raise ValueError("Either 'session' or 'manager' must be provided")
        manager = MultiSessionService(max_sessions=1)
        manager.wrap_session(session)

    sessions = manager.list_sessions()
    rprint(
        label="Session",
        content=f"Managing {sessions.count} session(s), max={sessions.max_sessions}",
    )
    for svc_info in sessions.sessions:
        rprint(
            label=f"  [{svc_info.session_id}]",
            content=f"mode={svc_info.mode}, running={svc_info.running}",
        )

    app = create_unified_app(manager)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        manager.shutdown()
