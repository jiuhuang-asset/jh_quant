"""Demo entrypoint with two paper sessions for side-by-side strategy comparison.

Optional environment variables:
- PAPER_INITIAL_CAPITAL
- PAPER_BACKFILL_FROM
- PAPER_ENABLE_BACKFILL
- TRADING_AUTO_START
- PAPER_DEMO_DB_PATH
- TRADING_CRON
- TRADING_HOST
- TRADING_PORT
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
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
    register_selection_provider,
    run_trading_app,
)
from jh_quant.trading.config import (
    ATRTrailingStopRuleConfig,
    ClockMode,
    DualThrustStrategyConfig,
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
    "688981",
    "688041",
    "688256",
    "002371",
    "688012",
    "603986",
    "688008",
    "603501",
    "300604",
    "002049",
    "600460",
    "300782",
]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def build_manager() -> MultiSessionService:
    db_path = os.getenv("PAPER_DEMO_DB_PATH", "trade_paper_demo.db")
    recorder = SQLiteOrderRecorder(db_path=db_path)
    persistence = PersistenceCoordinator(recorder=recorder)
    try:
        md_provider = AkShareJHMarketDataService(default_symbols=DEMO_SYMBOLS)
        print("run_paper: using AkShareJHMarketDataService")
    except Exception as exc:
        print(
            "run_paper: failed to initialize AkShareJHMarketDataService, "
            f"falling back to synthetic demo data. reason={type(exc).__name__}: {exc}"
        )
        md_provider = DemoSyntheticMarketDataProvider(default_symbols=DEMO_SYMBOLS)
    return MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )


def build_base_config() -> SessionServiceConfigBuilder:
    cron_expression = os.getenv("TRADING_CRON", "0 16 * * 1-5")
    backfill_from = os.getenv("PAPER_BACKFILL_FROM", (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d"))
    auto_start = _env_flag("TRADING_AUTO_START", True)
    enable_backfill = _env_flag("PAPER_ENABLE_BACKFILL", True)
    clock_mode = ClockMode.BACKFILL if enable_backfill else ClockMode.REALTIME

    builder = (
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
        .add_risk_rule(
            name="atr_trailing_stop",
            params=ATRTrailingStopRuleConfig(multiplier=3.0, window=20),
        )
    )
    return builder


def build_momentum_config() -> SessionServiceConfig:
    return (
        build_base_config()
        .with_session(session_id="demo-paper-momentum")
        .add_strategy(
            name="momentum",
            alias="momentum",
            weight=1.0,
            params=MomentumStrategyConfig(),
        )
        .build()
    )


def build_dual_thrust_config() -> SessionServiceConfig:
    return (
        build_base_config()
        .with_session(session_id="demo-paper-dual-thrust")
        .add_strategy(
            name="dual_thrust",
            alias="dual_thrust",
            weight=1.0,
            params=DualThrustStrategyConfig(),
        )
        .build()
    )


def run_service() -> None:
    host = os.getenv("TRADING_HOST", "127.0.0.1")
    port = int(os.getenv("TRADING_PORT", "8000"))
    initial_capital = float(os.getenv("PAPER_INITIAL_CAPITAL", "100000"))

    manager = build_manager()
    momentum_config = build_momentum_config()
    dual_thrust_config = build_dual_thrust_config()

    manager.create_session(config=momentum_config, initial_capital=initial_capital)
    manager.create_session(config=dual_thrust_config, initial_capital=initial_capital)

    run_trading_app(manager=manager, host=host, port=port)


if __name__ == "__main__":
    run_service()
