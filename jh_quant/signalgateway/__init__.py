from importlib import import_module


_EXPORTS = {
    "BacktestEngine": ".backtest_engine",
    "buildStrategyGrid": ".strategy",
    "Strategy": ".strategy",
    "StockHoldRecord": ".models",
    "Positions": ".models",
    "Order": ".models",
    "Trade": ".models",
    "DailyPerformance": ".models",
    "PositionSnapshot": ".models",
    "SignalGateway": ".signalgateway",
    "PositionSizer": ".position_sizer",
    "ATRPositionSizer": ".position_sizer",
    "FixedWeightPositionSizer": ".position_sizer",
    "OMS": ".oms",
    "MockOMS": ".oms",
    "MarketDataProvider": ".market_data",
    "JHMarketData": ".market_data",
    "OrderRecorder": ".order_recorder",
    "TortoiseOrderRecorder": ".order_recorder",
    "SQLiteOrderRecorder": ".order_recorder",
    "PostgresOrderRecorder": ".order_recorder",
    "MemFireCloudRecorder": ".order_recorder",
    "calculate_holding_returns": ".performance",
    "calculate_turnover": ".performance",
    "get_performance_summary": ".performance",
    "ServiceConfig": ".service",
    "StrategySpec": ".service",
    "FixedUniverseSelectionConfig": ".service",
    "DummySelectionConfig": ".service",
    "SignalGatewayService": ".service",
    "LLMCommandRequest": ".service",
    "register_strategy": ".service",
    "create_service_app": ".service_api",
    "run_service_app": ".service_api",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
