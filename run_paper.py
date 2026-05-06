from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from jh_quant.gateway import (
    JHMarketDataProvider,
    MultiSessionService,
    PersistenceCoordinator,
    SelectionProvider,
    SelectionSnapshot,
    SQLiteOrderRecorder,
    register_selection_provider,
    run_gateway_app,
)
from jh_quant.gateway.config import (
    ATRTrailingStopRuleConfig,
    MomentumStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    SessionServiceConfigBuilder,
    DualThrustStrategyConfig
)


# ── 自定义选股器：A股市值最高的 50 只半导体 ──────────────────────────────

@dataclass
class SemiConductorSelectionConfig:
    """半导体静态选股器参数。"""
    symbols: List[str] = field(default_factory=list)


class SemiConductorSelectionProvider(SelectionProvider):
    """返回 A 股市值最高的 50 只半导体股票代码"""

    def __init__(self, config: SemiConductorSelectionConfig):
        self._symbols = list(config.symbols)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self._symbols),
            metadata={"as_of_date": as_of_date, "provider": "semiconductor_static"},
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


# 注册到系统，名称为 "半导体自选"，方便后面引用
register_selection_provider(
    name="半导体自选",
    provider_cls=SemiConductorSelectionProvider,
    config_model=SemiConductorSelectionConfig,
)

# 自定义选股池(半导体)
SEMI_SYMBOLS = [
    "688981", "688041", "688256", "002371", "688795", "688012", "688802", "688347",
    "603986", "688008", "688820", "603501", "301308", "688521", "688072", "688783",
    "600584", "688525", "300604", "688702", "688498", "688082", "002156", "688729",
    "603893", "688385", "688396", "688126", "002049", "688120", "688249", "688361",
    "688469", "300223", "001309", "688047", "688110", "688172", "301611", "600460",
    "002185", "300782", "300373", "002409", "688809", "688037", "688234", "300666",
    "300661", "688728",
]


def run_service() -> None:
    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8000"))
    recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    md_provider = JHMarketDataProvider()

    manager = MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )

    config = (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id="semi-momentum-001",
            mode="paper",
            price_slippage=0.001,  # 价格滑点
            cron_expression="0 16 * * 1-5",
            enable_backfill=True,
            backfill_from="2025-10-01"
        )
        .with_selection(
            name="半导体自选",
            params=SemiConductorSelectionConfig(
                symbols=SEMI_SYMBOLS,
            ),
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
        .build()
    )

    config_b = (
        SessionServiceConfigBuilder(base_config=config)
        .with_session(
            session_id="semi-dualthrust-002",  
        )
        .with_strategy(
            name="dual_thrust",
            weight=1.0,
            params=DualThrustStrategyConfig(),
        )
        .build()
    ) 

    _ = manager.create_session(config=config, initial_capital=100000)
    _ = manager.create_session(config=config_b, initial_capital=100000)


    run_gateway_app(manager=manager, host=host, port=port)


if __name__ == "__main__":
    run_service()
