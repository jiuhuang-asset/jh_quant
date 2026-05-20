"""Demo entrypoint with one paper session and one xtquant live session.

Expected environment variables for the live broker:
- MINIQMT_USERDATA_DIR
- MINIQMT_STOCK_ACCOUNT

Optional:
- MINIQMT_TRADER_SESSION_ID
- PAPER_INITIAL_CAPITAL
- PAPER_BACKFILL_FROM
- TRADING_CRON
- TRADING_HOST
- TRADING_PORT
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from jh_quant.trading import (
    MultiSessionService,
    PersistenceCoordinator,
    SelectionProvider,
    SelectionSnapshot,
    SQLiteOrderRecorder,
    XtQuantJHMarketDataProvider,
    register_selection_provider,
    run_trading_app,
)
from jh_quant.trading.config import (
    ATRTrailingStopRuleConfig,
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


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "See run_live.py for the expected MiniQMT / xtquant settings."
        )
    return value


def build_manager() -> MultiSessionService:
    recorder = SQLiteOrderRecorder(db_path="trade_live_demo.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    md_provider = XtQuantJHMarketDataProvider()
    return MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )


def build_base_config() -> SessionServiceConfigBuilder:
    cron_expression = os.getenv("TRADING_CRON", "0 14 * * 1-5")
    backfill_from = os.getenv("PAPER_BACKFILL_FROM", "2025-10-01")

    return (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            auto_start=True,
            cron_expression=cron_expression,
            price_slippage=0.001,
            enable_backfill=True,
            backfill_from=backfill_from,
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
            mode="paper",
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
            mode="live",
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
    live_config = build_live_config()

    manager.create_session(config=paper_config, initial_capital=paper_initial_capital)
    manager.create_session(config=live_config)

    run_trading_app(manager=manager, host=host, port=port)


if __name__ == "__main__":
    run_service()
