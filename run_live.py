"""Demo entrypoint with one paper session and one xtquant live session.

Expected environment variables for the live broker:
- MINIQMT_USERDATA_DIR
- MINIQMT_STOCK_ACCOUNT

Optional:
- MINIQMT_TRADER_SESSION_ID
- PAPER_INITIAL_CAPITAL
- PAPER_BACKFILL_FROM
- PAPER_ENABLE_BACKFILL
- TRADING_AUTO_START
- RUN_LIVE_SESSION
- LIVE_DEMO_DB_PATH
- TRADING_CRON
- TRADING_HOST
- TRADING_PORT
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from demo_market_data import DemoSyntheticMarketDataProvider
from jh_quant.trading import (
    AkShareJHMarketDataService,
    MultiSessionService,
    PersistenceCoordinator,
    SelectionProvider,
    SelectionSnapshot,
    SQLiteOrderRecorder,
    XtQuantAkShareMarketDataService,
    register_selection_provider,
    run_trading_app,
)
from jh_quant.trading.config import (
    ATRTrailingStopRuleConfig,
    ClockMode,
    ExecutionMode,
    MomentumStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    SessionServiceConfig,
    SessionServiceConfigBuilder,
)


@dataclass
class DemoWatchlistConfig:
    symbols: List[str] = field(default_factory=list)


class DemoWatchlistSelectionProvider(SelectionProvider):
    def __init__(self, config: DemoWatchlistConfig):
        self._symbols = list(config.symbols)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self._symbols),
            metadata={"as_of_date": as_of_date, "provider": "demo_watchlist"},
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


register_selection_provider(
    name="demo_watchlist",
    provider_cls=DemoWatchlistSelectionProvider,
    config_model=DemoWatchlistConfig,
)


DEMO_SYMBOLS = [
    "600519",
    "000001",
    "000858",
    "002594",
    "600036",
    "601318",
    "300750",
    "600276",
]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "See run_live.py for the expected MiniQMT / xtquant settings."
        )
    return value


def _has_live_broker_env() -> bool:
    return bool(os.getenv("MINIQMT_USERDATA_DIR", "").strip()) and bool(
        os.getenv("MINIQMT_STOCK_ACCOUNT", "").strip()
    )


def build_manager() -> MultiSessionService:
    db_path = os.getenv("LIVE_DEMO_DB_PATH", "trade_live_demo.db")
    recorder = SQLiteOrderRecorder(db_path=db_path)
    persistence = PersistenceCoordinator(recorder=recorder)
    try:
        md_provider = XtQuantAkShareMarketDataService(default_symbols=DEMO_SYMBOLS)
        print("run_live: using XtQuantAkShareMarketDataService")
    except Exception as xt_exc:
        try:
            md_provider = AkShareJHMarketDataService(default_symbols=DEMO_SYMBOLS)
            print(
                "run_live: xtquant market data unavailable, falling back to "
                f"AkShareJHMarketDataService. reason={type(xt_exc).__name__}: {xt_exc}"
            )
        except Exception as jh_exc:
            print(
                "run_live: failed to initialize xtquant/JH market data, falling "
                "back to synthetic demo data. "
                f"xtquant_reason={type(xt_exc).__name__}: {xt_exc}; "
                f"jh_reason={type(jh_exc).__name__}: {jh_exc}"
            )
            md_provider = DemoSyntheticMarketDataProvider(default_symbols=DEMO_SYMBOLS)
    return MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )


def manager_supports_live_quotes(manager: MultiSessionService) -> bool:
    provider = getattr(manager, "_shared_md_provider", None)
    return isinstance(provider, XtQuantAkShareMarketDataService)


def build_base_config() -> SessionServiceConfigBuilder:
    cron_expression = os.getenv("TRADING_CRON", "0 14 * * 1-5")
    backfill_from = os.getenv("PAPER_BACKFILL_FROM", "2025-10-01")
    auto_start = _env_flag("TRADING_AUTO_START", True)
    enable_backfill = _env_flag("PAPER_ENABLE_BACKFILL", True)
    clock_mode = ClockMode.BACKFILL if enable_backfill else ClockMode.REALTIME

    return (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            execution_mode=ExecutionMode.PAPER,
            clock_mode=clock_mode,
            auto_start=auto_start,
            cron_expression=cron_expression,
            price_slippage=0.001,
            backfill_start=backfill_from if enable_backfill else None,
        )
        .with_selection(
            name="demo_watchlist",
            params=DemoWatchlistConfig(symbols=DEMO_SYMBOLS),
        )
        .with_portfolio(
            enabled=True,
            objective="MinRisk",
            rebalance_policy=RebalancePolicySpec(
                mode=RebalanceMode.DRIFT_THRESHOLD,
                drift_threshold=0.10,
            ),
        )
        .add_strategy(
            name="momentum",
            alias="momentum",
            weight=1.0,
            params=MomentumStrategyConfig(),
        )
        .add_risk_rule(
            name="atr_trailing_stop",
            params=ATRTrailingStopRuleConfig(multiplier=3.0, window=20),
        )
    )


def build_paper_config() -> SessionServiceConfig:
    return (
        build_base_config()
        .with_session(
            session_id="demo-paper-compare",
            execution_mode=ExecutionMode.PAPER,
        )
        .build()
    )


def build_live_config() -> SessionServiceConfig:
    miniqmt_path = _require_env("MINIQMT_USERDATA_DIR")
    stock_account = _require_env("MINIQMT_STOCK_ACCOUNT")
    trader_session_id = os.getenv("MINIQMT_TRADER_SESSION_ID", "").strip()

    broker_params: Dict[str, Any] = {
        "miniqmt_path": miniqmt_path,
        "stock_account": stock_account,
    }
    if trader_session_id:
        broker_params["trader_session_id"] = int(trader_session_id)

    return (
        build_base_config()
        .with_session(
            session_id="demo-live-xtquant",
            execution_mode=ExecutionMode.LIVE,
            clock_mode=ClockMode.REALTIME,
        )
        .with_broker(
            name="xtquant",
            params=broker_params,
            alias="miniqmt-live",
        )
        .build()
    )


def run_service() -> None:
    host = os.getenv("TRADING_HOST", "127.0.0.1")
    port = int(os.getenv("TRADING_PORT", "8000"))
    paper_initial_capital = float(os.getenv("PAPER_INITIAL_CAPITAL", "100000"))

    manager = build_manager()
    paper_config = build_paper_config()

    manager.create_session(config=paper_config, initial_capital=paper_initial_capital)

    live_enabled = _env_flag("RUN_LIVE_SESSION", True)
    if live_enabled and _has_live_broker_env() and manager_supports_live_quotes(manager):
        live_config = build_live_config()
        manager.create_session(config=live_config)
        print("run_live: live xtquant session enabled")
    elif live_enabled and _has_live_broker_env():
        print(
            "run_live: MiniQMT broker env is present, but xtquant realtime market "
            "data is unavailable. Starting in paper-only mode instead."
        )
    elif live_enabled:
        print(
            "run_live: MiniQMT environment variables are missing, starting in "
            "paper-only comparison mode. Set MINIQMT_USERDATA_DIR and "
            "MINIQMT_STOCK_ACCOUNT to enable the live session."
        )
    else:
        print("run_live: RUN_LIVE_SESSION is disabled, starting paper-only mode")

    run_trading_app(manager=manager, host=host, port=port)


if __name__ == "__main__":
    run_service()
