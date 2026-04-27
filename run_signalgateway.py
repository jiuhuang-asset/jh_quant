"""
Manual smoke runner for the SignalGateway service.

This file is intentionally lightweight so it does not interfere with pytest
collection. Use `tests/test_signalgateway.py` for automated coverage.
Set `SIGNALGATEWAY_RUN_SERVER=1` to launch the HTTP service manually.
"""

from __future__ import annotations

import os
from jh_quant.signalgateway.config import *

from jh_quant.signalgateway import (
    JHMarketDataProvider,
    SQLiteOrderRecorder,
    SignalGateway,
    SignalGatewayService,
    PersistenceCoordinator,
    MockOMS,
    create_service_app,
    run_service_app,
)
def main() -> None:
    session_id = "TEST_SESSION_001"
    initial_capital = 100000.0
    host = os.getenv("SIGNALGATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("SIGNALGATEWAY_PORT", "8000"))
    auto_start_scheduler = os.getenv("SIGNALGATEWAY_AUTO_START", "0") == "1"
    # register_selection_provider("demo_selector", DemoSelectionProvider, config_model="")

    recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    oms = MockOMS(
        session_id=session_id,
        initial_capital=initial_capital,
    )
    gateway = SignalGateway(
        oms=oms,
        market_data_provider=JHMarketDataProvider(),
    )
    service_config = (
        SignalGatewayServiceConfigBuilder.defaults()
        .with_service(
            session_id=session_id,
            mode="paper",
            interval_seconds=300,
            price_lookback_days=200,
            max_candidates=50,
            auto_start=auto_start_scheduler,
            cron_expression="0 9 * * 1-5",
            restore_persisted_state=False,
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
        .build()
    )
    service = SignalGatewayService(
        gateway=gateway,
        config=service_config,
        persistence=persistence,
    )
    results = service.run_once()
    print(results)
    # service.start()
    # try:
    #     if os.getenv("SIGNALGATEWAY_RUN_SERVER", "0") == "1":
    #         run_service_app(service, host=host, port=port)
    #         return

    #     app = create_service_app(service)
    #     print("service_status", service.get_status())
    #     print("app_title", app.title)
    #     print("route_count", len(app.routes))
    # finally:
    #     service.close()


if __name__ == "__main__":
    main()
