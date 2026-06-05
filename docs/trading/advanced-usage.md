# 高级自定义运行

本页展示不使用 bootstrap 的完整运行方式。适合需要精确控制行情源、选股器、策略、组合优化、风控规则、持久化、实盘 broker 和 Dashboard 的用户。

## 1. 手动运行模拟盘

下面示例会创建两个并行模拟盘 session：

- `paper-turtle`：海龟策略基准场景。
- `paper-rsi`：用户自定义策略场景。

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from jh_quant.trading import (
    MultiSessionService,
    PersistenceCoordinator,
    SelectionProvider,
    SelectionSnapshot,
    SQLiteOrderRecorder,
    create_market_data_service,
    register_selection_provider,
    run_trading_app,
)
from jh_quant.trading.config import (
    ATRTrailingStopRuleConfig,
    ClockMode,
    ExecutionMode,
    RSIStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    SessionServiceConfigBuilder,
    TurtleStrategyConfig,
)


SYMBOLS = ["688041", "688256", "688981", "603986"]


@dataclass
class WatchlistConfig:
    symbols: List[str] = field(default_factory=list)


class WatchlistSelectionProvider(SelectionProvider):
    def __init__(self, config: WatchlistConfig):
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self._config.symbols),
            metadata={"provider": "manual_watchlist", "as_of_date": as_of_date},
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


register_selection_provider(
    name="manual_watchlist",
    provider_cls=WatchlistSelectionProvider,
    config_model=WatchlistConfig,
)


def base_config(session_id: str):
    return (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id=session_id,
            execution_mode=ExecutionMode.PAPER,
            clock_mode=ClockMode.BACKFILL,
            auto_start=True,
            cron_expression="0 14 * * 1-5",
            price_slippage=0.001,
            backfill_start="2025-01-01",
        )
        .with_selection(
            name="manual_watchlist",
            params=WatchlistConfig(symbols=SYMBOLS),
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


market_data = create_market_data_service("tushare", default_symbols=SYMBOLS)
persistence = PersistenceCoordinator(
    recorder=SQLiteOrderRecorder(db_path="trade_manual_paper.db")
)
manager = MultiSessionService(
    max_sessions=4,
    persistence=persistence,
    market_data_provider=market_data,
)

turtle_config = (
    base_config("paper-turtle")
    .with_strategy(name="turtle", alias="turtle", weight=1.0, params=TurtleStrategyConfig())
    .build()
)
rsi_config = (
    base_config("paper-rsi")
    .with_strategy(name="rsi", alias="rsi", weight=1.0, params=RSIStrategyConfig())
    .build()
)

manager.create_session(config=turtle_config, initial_capital=100_000)
manager.create_session(config=rsi_config, initial_capital=100_000)
run_trading_app(manager=manager, host="127.0.0.1", port=8000)
```

## 2. 手动打开 Dashboard

`run_trading_app()` 会阻塞当前进程。如果不使用 bootstrap，但仍希望一次启动 API 和 Dashboard，可以用后台线程启动 API：

```python
import threading
import time

from jh_quant.dashboard import display_trading
from jh_quant.trading import run_trading_app

api_thread = threading.Thread(
    target=run_trading_app,
    kwargs={"manager": manager, "host": "127.0.0.1", "port": 8000},
    daemon=True,
)
api_thread.start()
time.sleep(1.5)

display_trading(host="127.0.0.1", port=8000)
```

bootstrap 默认已经内置了这段逻辑。只有在高级手动运行时才需要自己处理。

## 3. 手动运行实盘

实盘 session 需要显式配置 broker。下面示例使用 xtquant / MiniQMT：

```python
import os

from jh_quant.trading import (
    MultiSessionService,
    PersistenceCoordinator,
    SQLiteOrderRecorder,
    create_market_data_service,
    run_trading_app,
)
from jh_quant.trading.config import (
    ClockMode,
    ExecutionMode,
    MomentumStrategyConfig,
    SessionServiceConfigBuilder,
)

SYMBOLS = ["688041", "688256", "688981", "603986"]

market_data = create_market_data_service("xquant", default_symbols=SYMBOLS)
persistence = PersistenceCoordinator(
    recorder=SQLiteOrderRecorder(db_path="trade_manual_live.db")
)
manager = MultiSessionService(
    max_sessions=2,
    persistence=persistence,
    market_data_provider=market_data,
)

broker_params = {
    "miniqmt_path": os.environ["MINIQMT_USERDATA_DIR"],
    "stock_account": os.environ["MINIQMT_STOCK_ACCOUNT"],
}

config = (
    SessionServiceConfigBuilder.defaults()
    .with_session(
        session_id="live-momentum",
        execution_mode=ExecutionMode.LIVE,
        clock_mode=ClockMode.REALTIME,
        auto_start=True,
        cron_expression="0 14 * * 1-5",
        backfill_start=None,
    )
    .with_broker(name="xtquant", params=broker_params, alias="miniqmt-live")
    .with_strategy(
        name="momentum",
        alias="momentum",
        weight=1.0,
        params=MomentumStrategyConfig(),
    )
    .build()
)

manager.create_session(config=config)
run_trading_app(manager=manager, host="127.0.0.1", port=8000)
```

实盘注意事项：

- `ExecutionMode.LIVE` 必须绑定真实 broker。
- `ClockMode.REALTIME` 是实盘唯一推荐时钟。
- 不要给实盘 session 设置 `backfill_start`。
- MiniQMT 环境变量必须在启动前配置好。
