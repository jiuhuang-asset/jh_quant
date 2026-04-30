"""
Manual smoke runner for the SignalGateway service.

Set ``SIGNALGATEWAY_RUN_SERVER=1`` to launch the HTTP service.
Set ``SIGNALGATEWAY_MULTI_SERVICE=1`` to launch in multi-service mode.
"""

from __future__ import annotations

import os

from jh_quant.signalgateway import (
    JHMarketDataProvider,
    MockOMS,
    MultiServiceManager,
    PersistenceCoordinator,
    SignalGateway,
    SignalGatewayService,
    SQLiteOrderRecorder,
    run_service_app,
)
from jh_quant.signalgateway.config import (
    FactorSelectionConfig,
    MomentumStrategyConfig,
    MovingAverageCrossoverStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    SignalGatewayServiceConfig,
    SignalGatewayServiceConfigBuilder,
    TurtleStrategyConfig,
    VolumeDivergenceStrategyConfig,
)


def build_default_config(session_id: str, auto_start: bool = False) -> SignalGatewayServiceConfig:
    return (
        SignalGatewayServiceConfigBuilder.defaults()
        .with_service(
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


def main_single() -> None:
    """Single-service mode."""
    session_id = "TEST_SESSION_001"
    initial_capital = 100000.0
    host = os.getenv("SIGNALGATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("SIGNALGATEWAY_PORT", "8000"))
    auto_start_scheduler = os.getenv("SIGNALGATEWAY_AUTO_START", "0") == "1"

    recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    oms = MockOMS(session_id=session_id, initial_capital=initial_capital)
    gateway = SignalGateway(oms=oms, market_data_provider=JHMarketDataProvider())
    service_config = build_default_config(session_id, auto_start=auto_start_scheduler)
    service = SignalGatewayService(
        gateway=gateway,
        config=service_config,
        persistence=persistence,
    )

    # Run one demo cycle
    result = service.run_once()
    print(result)

    try:
        if os.getenv("SIGNALGATEWAY_RUN_SERVER", "0") == "1":
            run_service_app(service=service, host=host, port=port)
        else:
            print("service_status", service.get_status())
            print("Set SIGNALGATEWAY_RUN_SERVER=1 to launch the HTTP server.")
    finally:
        service.shutdown_service()


def main_multi() -> None:
    """Multi-service mode — run multiple configs side by side."""
    host = os.getenv("SIGNALGATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("SIGNALGATEWAY_PORT", "8000"))
    auto_start = os.getenv("SIGNALGATEWAY_AUTO_START", "0") == "1"

    recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    md_provider = JHMarketDataProvider()

    manager = MultiServiceManager(
        max_services=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )

    # Service A
    config_a = build_default_config("SESSION_A", auto_start=auto_start)
    sid_a = manager.create_service(config=config_a, initial_capital=100000)
    print(f"Created service A: {sid_a}")

    # Service B
    config_b = (
        SignalGatewayServiceConfigBuilder.defaults()
        .with_service(
            session_id="SESSION_B",
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
    sid_b = manager.create_service(config=config_b, initial_capital=100000)
    print(f"Created service B: {sid_b}")

    # Run one demo cycle for each
    # svc_a = manager.get_service(sid_a)
    # svc_b = manager.get_service(sid_b)
    # print("--- Service A run_once ---")
    # print(svc_a.run_once())
    # print("--- Service B run_once ---")
    # print(svc_b.run_once())

    # # Show comparison
    # print("--- Comparison ---")
    # comparison = manager.get_comparison()
    # for s in comparison.services:
    #     print(
    #         f"  {s.session_id}: value={s.current_value}, "
    #         f"return={s.total_return_pct}%, "
    #         f"positions={s.position_count}, "
    #         f"strategies={s.strategy_names}"
    #     )
    os.environ["SIGNALGATEWAY_RUN_SERVER"] = "1"
    if os.getenv("SIGNALGATEWAY_RUN_SERVER", "0") == "1":
        run_service_app(manager=manager, host=host, port=port)
    else:
        print("Set SIGNALGATEWAY_RUN_SERVER=1 to launch the HTTP server.")


def main() -> None:
    os.environ["SIGNALGATEWAY_MULTI_SERVICE"] = "1"
    if os.getenv("SIGNALGATEWAY_MULTI_SERVICE", "0") == "1":
        main_multi()
    else:
        main_single()


if __name__ == "__main__":
    main()
