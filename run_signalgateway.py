from __future__ import annotations

import os

from jh_quant.gateway import (
    JHMarketDataProvider,
    MultiSessionService,
    PersistenceCoordinator,
    SQLiteOrderRecorder,
    run_gateway_app,
)
from jh_quant.gateway.config import (
    ATRTrailingStopRuleConfig,
    FactorSelectionConfig,
    MomentumStrategyConfig,
    SessionServiceConfigBuilder,
)

def run_service(run_once=False) -> None:
    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8000"))
    auto_start = os.getenv("GATEWAY_AUTO_START", "0") == "1"

    recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    md_provider = JHMarketDataProvider()

    manager = MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )

    # Session D
    config = (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id="SESSION_D",
            mode="paper",
            interval_seconds=300,
            price_lookback_days=200,
            max_candidates=30,
            auto_start=auto_start,
            cron_expression="0 9 * * 1-5",
        )
        .with_selection(
            name="factor_selector",
            params=FactorSelectionConfig(
                factor="ch3",
                start="2020-01-01",
                top_n=30,
            ),
        )
        .with_portfolio(
            enabled=True,
            objective="MinRisk",
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
        .build()
    )
    session_id = manager.create_session(config=config, initial_capital=100000)
    svc = manager.get_session(session_id)
    if run_once:
        svc.run_once()

    run_gateway_app(manager=manager, host=host, port=port)



if __name__ == "__main__":
    run_service(True)