"""
Manual smoke runner for the Gateway service.

Set ``GATEWAY_RUN_SERVER=1`` to launch the HTTP service.
Set ``GATEWAY_MULTI_SESSION=1`` to launch in multi-session mode.
"""

from __future__ import annotations

import os

from jh_quant.gateway import (
    JHMarketDataProvider,
    MockOMS,
    MultiSessionService,
    PersistenceCoordinator,
    SessionService,
    SignalGateway,
    SQLiteOrderRecorder,
    run_gateway_app,
)
from jh_quant.gateway.config import (
    FactorSelectionConfig,
    MomentumStrategyConfig,
    MovingAverageCrossoverStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    SessionServiceConfig,
    SessionServiceConfigBuilder,
    TurtleStrategyConfig,
    VolumeDivergenceStrategyConfig,
)


def build_default_config(session_id: str, auto_start: bool = False) -> SessionServiceConfig:
    return (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id=session_id,
            mode="paper",
            interval_seconds=300,
            price_lookback_days=200,
            max_candidates=50,
            auto_start=auto_start,
            cron_expression="0 9 * * 1-5",
            restore_persisted_state=True,
        )
        .with_selection(
            name="factor_selector",
            params=FactorSelectionConfig(
                factor="ch3",
                start="2020-01-01",
                top_n=50,
            ),
        )
        .add_strategy(
            name="turtle",
            alias="turtle",
            weight=1.0,
            params=TurtleStrategyConfig(),
        )
        .add_strategy(
            name="moving_average_crossover",
            alias="sma",
            weight=1.0,
            params=MovingAverageCrossoverStrategyConfig(short_window=12, long_window=24),
        )
        .add_strategy(
            name="volume_divergence",
            alias="volume_divergence",
            weight=1.0,
            params=VolumeDivergenceStrategyConfig(),
        )
        .with_portfolio(
            enabled=True,
            max_assets=5,
            max_weight=0.5,
            cash_reserve_ratio=0.05,
            rebalance_policy=RebalancePolicySpec(
                mode=RebalanceMode.EVERY_CYCLE,
                drift_threshold=0.10,
            ),
        )
        .build()
    )




def main_multi() -> None:
    """Multi-session mode — run multiple configs side by side."""
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

    # Session C
    config_c = build_default_config("SESSION_C", auto_start=auto_start)
    sid_c = manager.create_session(config=config_c, initial_capital=100000)
    print(f"Created session A: {sid_c}")

    # Session D
    config_d = (
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
        .add_strategy(
            name="momentum",
            alias="momentum",
            weight=1.0,
            params=MomentumStrategyConfig(),
        )
        .build()
    )
    sid_d = manager.create_session(config=config_d, initial_capital=100000)
    print(f"Created session B: {sid_d}")

    # Run one demo cycle for each
    svc_c = manager.get_session(sid_c)
    svc_d = manager.get_session(sid_d)
    print("--- Session C run_once ---")
    print(svc_c.run_once())
    print("--- Session D run_once ---")
    print(svc_d.run_once())

    os.environ["GATEWAY_RUN_SERVER"] = "1"
    if os.getenv("GATEWAY_RUN_SERVER", "0") == "1":
        run_gateway_app(manager=manager, host=host, port=port)
    else:
        print("Set GATEWAY_RUN_SERVER=1 to launch the HTTP server.")


def main() -> None:
    os.environ["GATEWAY_MULTI_SESSION"] = "1"
    if os.getenv("GATEWAY_MULTI_SESSION", "0") == "1":
        main_multi()
    else:
        main_single()


if __name__ == "__main__":
    main()
