"""
美股 Gateway 运行脚本 — 基于 yfinance 数据源的实盘/模拟盘交易。

核心差异（对比 A 股 run_signalgateway.py）：
- 使用 YFinanceProvider 获取美股数据
- 使用静态选股列表（美股不依赖因子选股器）
- 启用风控规则（StopLoss + TrailingStop）
- 支持 portfolio 调仓与纯信号两种模式

用法::

    # 单次执行（查看信号与风控输出）
    python run_us_gateway.py

    # 启动 HTTP 服务
    GATEWAY_RUN_SERVER=1 python run_us_gateway.py

    # 多 session 模式
    GATEWAY_MULTI_SESSION=1 python run_us_gateway.py

    # Session 自动启动调度
    GATEWAY_AUTO_START=1 python run_us_gateway.py
"""

from __future__ import annotations

import os
import sys
from typing import List

from jh_quant.gateway import (
    MockOMS,
    MultiSessionService,
    PersistenceCoordinator,
    SessionService,
    SelectionSnapshot,
    SignalGateway,
    SQLiteOrderRecorder,
    YFinanceProvider,
    run_gateway_app,
)
from jh_quant.gateway.config import (
    MomentumStrategyConfig,
    MovingAverageCrossoverStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    RiskRuleSpec,
    RSIStrategyConfig,
    SessionServiceConfig,
    SessionServiceConfigBuilder,
    VolumeDivergenceStrategyConfig,
)


# ── 美股蓝筹选股池 ──────────────────────────────────────────────────────────

US_MEGA_CAP = [
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "GOOGL",  # Alphabet
    "AMZN",  # Amazon
    "NVDA",  # NVIDIA
    "META",  # Meta
    "TSLA",  # Tesla
    "BRK-B",  # Berkshire Hathaway
    "JPM",  # JPMorgan Chase
    "V",  # Visa
    "MA",  # Mastercard
    "JNJ",  # Johnson & Johnson
    "WMT",  # Walmart
    "PG",  # Procter & Gamble
    "XOM",  # Exxon Mobil
    "UNH",  # UnitedHealth
    "HD",  # Home Depot
    "BAC",  # Bank of America
    "DIS",  # Disney
    "ADBE",  # Adobe
]

US_TECH = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "ADBE",
    "CRM",
    "NFLX",
    "INTC",
]


class StaticSelectionProvider:
    """静态选股器 — 返回固定美股列表，供 session 使用。"""

    def __init__(self, symbols: List[str]):
        self._symbols = list(symbols)

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self._symbols),
            metadata={"as_of_date": as_of_date, "provider": "static_us"},
        )


# ── 配置构建 ────────────────────────────────────────────────────────────────


def build_us_config(
    session_id: str,
    *,
    symbols: List[str] = None,
    auto_start: bool = False,
    use_portfolio: bool = True,
    enable_risk_rules: bool = True,
) -> SessionServiceConfig:
    """构建美股 session 配置。

    Args:
        session_id: 会话 ID
        symbols: 美股代码列表，默认使用 US_TECH
        auto_start: 是否自动启动调度器
        use_portfolio: 是否启用组合优化调仓
        enable_risk_rules: 是否启用风控规则
    """
    symbols = symbols or US_TECH

    builder = (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id=session_id,
            mode="paper",
            interval_seconds=86400,  # 美股日线，每天执行一次
            price_lookback_days=365,
            max_candidates=len(symbols),
            auto_start=auto_start,
            cron_expression="30 16 * * 1-5",  # 美东 16:30 (收盘后)
            timezone="US/Eastern",
            restore_persisted_state=True,
        )
        # 美股策略
        .add_strategy(
            name="momentum",
            alias="momentum_20",
            weight=1.0,
            params=MomentumStrategyConfig(momentum_window=20),
        )
        .add_strategy(
            name="moving_average_crossover",
            alias="ma_cross",
            weight=1.0,
            params=MovingAverageCrossoverStrategyConfig(
                short_window=20, long_window=60
            ),
        )
        .add_strategy(
            name="rsi",
            alias="rsi",
            weight=1.0,
            params=RSIStrategyConfig(
                rsi_window=14,
                rsi_oversold=30,
                rsi_overbought=70,
            ),
        )
    )

    if enable_risk_rules:
        builder.add_risk_rule(
            name="stop_loss",
            alias="hard_stop",
            params={"pct": 0.05},  # 5% 止损
        )
        builder.add_risk_rule(
            name="trailing_stop",
            alias="trail",
            params={"pct": 0.08},  # 8% 移动止损
        )
        builder.add_risk_rule(
            name="take_profit",
            alias="tp",
            params={"pct": 0.20},  # 20% 止盈
        )

    if use_portfolio:
        builder.with_portfolio(
            enabled=True,
            max_assets=8,
            max_weight=0.25,
            min_weight=0.02,
            cash_reserve_ratio=0.05,
            lot_size=1,  # 美股最小交易单位为 1 股
            allow_partial_rebalance=True,
            historical_lookback_days=252,  # 一年交易日
            rebalance_policy=RebalancePolicySpec(
                mode=RebalanceMode.EVERY_CYCLE,
                drift_threshold=0.10,
            ),
        )
    else:
        builder.with_portfolio(enabled=False)

    return builder.build()


# ── 主流程 ───────────────────────────────────────────────────────────────────


def main_single() -> None:
    """单 session 模式 — 1 个美股策略组合。"""
    session_id = "US_SESSION"
    auto_start = os.getenv("GATEWAY_AUTO_START", "0") == "1"
    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8000"))

    config = build_us_config(session_id, auto_start=auto_start)

    # 美股数据源
    all_symbols = US_MEGA_CAP
    md_provider = YFinanceProvider(
        default_symbols=all_symbols,
        frequency=config.session.frequency,
    )

    # 静态选股器
    selection = StaticSelectionProvider(US_TECH)

    # OMS + 持久化
    oms = MockOMS(initial_capital=100000, session_id=session_id)
    recorder = SQLiteOrderRecorder(db_path="us_mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)

    gateway = SignalGateway(
        oms=oms,
        market_data_provider=md_provider,
    )

    gs = SessionService(
        gateway=gateway,
        config=config,
        selection_provider=selection,
        persistence=persistence,
    )

    print(f"\n{'='*60}")
    print(f"  US Gateway Session: {session_id}")
    print(f"  Symbols: {US_TECH}")
    print(f"  Portfolio: {config.portfolio_spec.enabled}")
    risk_names = [s.name for s in config.risk_rule_specs]
    print(f"  Risk Rules: {risk_names if risk_names else 'disabled'}")
    print(f"{'='*60}\n")

    # 执行一个周期
    print(">>> run_once 开始 ...")
    result = gs.run_once()
    print(f"\n>>> 执行结果: {result}")

    if os.getenv("GATEWAY_RUN_SERVER", "0") == "1":
        print(f"\n启动 HTTP 服务: {host}:{port}")
        run_gateway_app(service=gs, host=host, port=port)
    else:
        print("\n设置 GATEWAY_RUN_SERVER=1 以启动 HTTP 服务。")


def main_multi() -> None:
    """多 session 模式 — 对比不同策略组合。"""
    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8000"))
    auto_start = os.getenv("GATEWAY_AUTO_START", "0") == "1"

    recorder = SQLiteOrderRecorder(db_path="us_mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)
    md_provider = YFinanceProvider(default_symbols=US_MEGA_CAP)

    manager = MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )

    # Session A: 科技股 + 风控 + portfolio
    config_a = build_us_config("US_TECH_RISK", symbols=US_TECH, auto_start=auto_start)
    sid_a = manager.create_session(
        config=config_a,
        initial_capital=100000,
        selection_provider=StaticSelectionProvider(US_TECH),
    )
    print(f"Created session A (tech + risk + portfolio): {sid_a}")

    # Session B: 科技股 + 纯信号（无 portfolio，无风控）
    config_b = build_us_config(
        "US_TECH_SIGNAL",
        symbols=US_TECH,
        auto_start=auto_start,
        use_portfolio=False,
        enable_risk_rules=False,
    )
    sid_b = manager.create_session(
        config=config_b,
        initial_capital=100000,
        selection_provider=StaticSelectionProvider(US_TECH),
    )
    print(f"Created session B (tech + signal-only): {sid_b}")

    # 各执行一次
    for sid in [sid_a, sid_b]:
        svc = manager.get_session(sid)
        print(f"\n--- {sid} run_once ---")
        try:
            result = svc.run_once()
            print(
                f"  buys={result.executed_buy_count}, sells={result.executed_sell_count}"
            )
        except Exception as exc:
            print(f"  Error: {exc}")

    if os.getenv("GATEWAY_RUN_SERVER", "0") == "1":
        run_gateway_app(manager=manager, host=host, port=port)
    else:
        print("\n设置 GATEWAY_RUN_SERVER=1 以启动 HTTP 服务。")


def main() -> None:
    os.environ.setdefault("GATEWAY_MULTI_SESSION", "0")
    if os.getenv("GATEWAY_MULTI_SESSION", "0") == "1":
        main_multi()
    else:
        main_single()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGracefully shutting down...")
