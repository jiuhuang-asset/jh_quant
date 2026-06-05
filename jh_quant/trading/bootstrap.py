from __future__ import annotations

import argparse
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence

from .config import (
    ATRTrailingStopRuleConfig,
    ClockMode,
    ExecutionMode,
    RebalanceMode,
    RebalancePolicySpec,
    SelectionProvider,
    SessionServiceConfig,
    SessionServiceConfigBuilder,
    STRATEGY_CONFIG_MODELS,
    STRATEGY_REGISTRY,
    register_selection_provider,
)
from .market_data import create_market_data_service
from .models import SelectionSnapshot
from .persistence import PersistenceCoordinator, SQLiteOrderRecorder
from .service import MultiSessionService, run_trading_app


DEFAULT_SYMBOLS = [
    "688041",
    "688256",
    "688981",
    "688012",
    "688008",
    "688347",
    "603986",
    "603501",
    "300604",
    "002371",
    "688072",
    "688525",
    "688126",
    "688521",
]
DEFAULT_PAPER_STRATEGIES = ["momentum"]
DEFAULT_COMPARE_STRATEGIES = ["turtle", "momentum"]
DEFAULT_LIVE_STRATEGIES = ["momentum"]
BASELINE_STRATEGY = "turtle"

STRATEGY_ALIASES = {
    "dual-thrust": "dual_thrust",
    "dual thrust": "dual_thrust",
    "buy-and-hold": "buy_and_hold",
    "buy hold": "buy_and_hold",
    "bollinger": "bollinger_bands",
    "ma": "moving_average_crossover",
    "moving-average-crossover": "moving_average_crossover",
    "turtule": "turtle",
}


@dataclass
class WatchlistSelectionConfig:
    symbols: List[str] = field(default_factory=list)


class WatchlistSelectionProvider(SelectionProvider):
    def __init__(self, config: WatchlistSelectionConfig):
        self._symbols = list(config.symbols)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self._symbols),
            metadata={"as_of_date": as_of_date, "provider": "watchlist"},
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


register_selection_provider(
    name="watchlist",
    provider_cls=WatchlistSelectionProvider,
    config_model=WatchlistSelectionConfig,
)


@dataclass
class TradingBootstrapConfig:
    template: str
    backend: str = "tushare"
    strategies: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    db_path: str = "trade_bootstrap.db"
    host: str = "127.0.0.1"
    port: int = 8000
    initial_capital: float = 100000.0
    cron_expression: str = "0 14 * * 1-5"
    auto_start: bool = True
    enable_backfill: bool = True
    backfill_start: str | None = None
    show_dashboard: bool = True
    dashboard_protocol: str = "http"
    dashboard_refresh_interval_ms: int = 15000


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def parse_symbols(raw: str | None, default: Sequence[str] = DEFAULT_SYMBOLS) -> List[str]:
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def registered_strategy_names() -> List[str]:
    return sorted(STRATEGY_REGISTRY.keys())


def parse_strategy_names(raw: str | None) -> List[str]:
    if not raw:
        return []
    names = []
    for item in raw.split(","):
        name = item.strip().lower()
        if not name:
            continue
        normalized = STRATEGY_ALIASES.get(name, name.replace("-", "_"))
        if normalized not in STRATEGY_REGISTRY:
            raise ValueError(
                f"Unknown strategy: {item}. Available strategies: "
                + ", ".join(registered_strategy_names())
            )
        names.append(normalized)
    return list(dict.fromkeys(names))


def resolve_strategy_names(config: TradingBootstrapConfig) -> List[str]:
    if config.strategies:
        names = parse_strategy_names(",".join(config.strategies))
        if config.template == "paper-compare" and BASELINE_STRATEGY not in names:
            names = [BASELINE_STRATEGY, *names]
        return names
    if config.template == "paper-compare":
        return list(DEFAULT_COMPARE_STRATEGIES)
    if config.template == "live-basic":
        return list(DEFAULT_LIVE_STRATEGIES)
    return list(DEFAULT_PAPER_STRATEGIES)


def build_market_data_service(backend: str, symbols: Sequence[str]):
    return create_market_data_service(
        backend=backend,
        default_symbols=list(symbols),
    )


def build_manager(config: TradingBootstrapConfig) -> MultiSessionService:
    recorder = SQLiteOrderRecorder(db_path=config.db_path)
    persistence = PersistenceCoordinator(recorder=recorder)
    market_data_provider = build_market_data_service(config.backend, config.symbols)
    return MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=market_data_provider,
    )


def base_config_builder(config: TradingBootstrapConfig) -> SessionServiceConfigBuilder:
    backfill_start = config.backfill_start
    if backfill_start is None and config.enable_backfill:
        backfill_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    clock_mode = ClockMode.BACKFILL if config.enable_backfill else ClockMode.REALTIME

    return (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            clock_mode=clock_mode,
            auto_start=config.auto_start,
            cron_expression=config.cron_expression,
            price_slippage=0.001,
            backfill_start=backfill_start if config.enable_backfill else None,
        )
        .with_selection(
            name="watchlist",
            params=WatchlistSelectionConfig(symbols=list(config.symbols)),
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


def add_strategy_specs(
    builder: SessionServiceConfigBuilder,
    strategy_names: Sequence[str],
) -> SessionServiceConfigBuilder:
    first = True
    weight = 1.0 / max(len(strategy_names), 1)
    for name in strategy_names:
        config_model = STRATEGY_CONFIG_MODELS.get(name)
        params = config_model() if config_model is not None else {}
        if first:
            builder = builder.with_strategy(
                name=name,
                alias=name,
                weight=weight,
                params=params,
            )
            first = False
        else:
            builder = builder.add_strategy(
                name=name,
                alias=name,
                weight=weight,
                params=params,
            )
    return builder


def build_paper_configs(config: TradingBootstrapConfig) -> List[SessionServiceConfig]:
    strategy_names = resolve_strategy_names(config)
    if config.template == "paper-compare":
        configs = []
        for strategy_name in strategy_names:
            builder = base_config_builder(config).with_session(
                session_id=f"paper-{strategy_name}",
                execution_mode=ExecutionMode.PAPER,
            )
            configs.append(add_strategy_specs(builder, [strategy_name]).build())
        return configs

    builder = (
        base_config_builder(config)
        .with_session(
            session_id="paper-momentum",
            execution_mode=ExecutionMode.PAPER,
        )
    )
    return [add_strategy_specs(builder, strategy_names).build()]


def build_live_config(config: TradingBootstrapConfig) -> SessionServiceConfig:
    miniqmt_path = _require_env("MINIQMT_USERDATA_DIR")
    stock_account = _require_env("MINIQMT_STOCK_ACCOUNT")
    trader_session_id = os.getenv("MINIQMT_TRADER_SESSION_ID", "").strip()
    broker_params: Dict[str, Any] = {
        "miniqmt_path": miniqmt_path,
        "stock_account": stock_account,
    }
    if trader_session_id:
        broker_params["trader_session_id"] = int(trader_session_id)

    builder = (
        base_config_builder(config)
        .with_session(
            session_id="live-xtquant",
            execution_mode=ExecutionMode.LIVE,
            clock_mode=ClockMode.REALTIME,
            backfill_start=None,
        )
        .with_broker(
            name="xtquant",
            params=broker_params,
            alias="miniqmt-live",
        )
    )
    return add_strategy_specs(builder, resolve_strategy_names(config)).build()


def build_paper_manager(config: TradingBootstrapConfig) -> MultiSessionService:
    manager = build_manager(config)
    for session_config in build_paper_configs(config):
        manager.create_session(
            config=session_config,
            initial_capital=config.initial_capital,
        )
    return manager


def build_live_manager(config: TradingBootstrapConfig) -> MultiSessionService:
    manager = build_manager(config)
    manager.create_session(config=build_live_config(config))
    return manager


def run_paper_from_cli(argv: Sequence[str] | None = None) -> None:
    config = parse_bootstrap_args(
        argv,
        default_template="paper-compare",
        default_db_path="trade_paper.db",
        default_port=8000,
    )
    run_trading_service(
        manager=build_paper_manager(config),
        config=config,
    )


def run_live_from_cli(argv: Sequence[str] | None = None) -> None:
    config = parse_bootstrap_args(
        argv,
        default_template="live-basic",
        default_db_path="trade_live.db",
        default_port=8000,
    )
    run_trading_service(
        manager=build_live_manager(config),
        config=config,
    )


def run_trading_service(
    manager: MultiSessionService,
    *,
    config: TradingBootstrapConfig,
) -> None:
    if not config.show_dashboard:
        run_trading_app(manager=manager, host=config.host, port=config.port)
        return

    api_thread = threading.Thread(
        target=run_trading_app,
        kwargs={"manager": manager, "host": config.host, "port": config.port},
        daemon=True,
    )
    api_thread.start()
    time.sleep(1.5)
    try:
        from jh_quant.dashboard import display_trading

        display_trading(
            host=config.host,
            port=config.port,
            protocol=config.dashboard_protocol,
            refresh_interval_ms=config.dashboard_refresh_interval_ms,
        )
    except Exception as exc:
        print(
            "bootstrap: Dashboard 启动失败，API 仍在运行："
            f"http://{config.host}:{config.port}/docs. "
            f"原因={type(exc).__name__}: {exc}"
        )
        api_thread.join()


def parse_bootstrap_args(
    argv: Sequence[str] | None,
    *,
    default_template: str,
    default_db_path: str,
    default_port: int,
) -> TradingBootstrapConfig:
    strategy_help = (
        "策略名，支持一个或多个；多个策略请用英文逗号分隔。"
        "可选策略: " + ", ".join(registered_strategy_names()) + "。"
        "示例: --strategy turtle 或 --strategy turtle,momentum。"
        "也可以通过环境变量 TRADING_STRATEGY 设置。"
    )
    parser = argparse.ArgumentParser(
        description=(
            "通过 bootstrap 模板启动 jh_quant trading 服务。"
            "默认使用 TuShare 历史行情，并用 AkShare 合并当天实时行情。"
        )
    )
    parser.add_argument(
        "--template",
        default=os.getenv("TRADING_TEMPLATE", default_template),
        help=(
            "Bootstrap 模板。可选: paper-basic, paper-compare, live-basic。"
            f"默认: {default_template}。环境变量: TRADING_TEMPLATE。"
        ),
    )
    parser.add_argument(
        "--backend",
        default=os.getenv("TRADING_BACKEND", "tushare"),
        help=(
            "行情 backend。可选: tushare, akshare, xquant。"
            "默认: tushare。环境变量: TRADING_BACKEND。"
        ),
    )
    parser.add_argument(
        "--strategy",
        dest="strategies",
        default=os.getenv("TRADING_STRATEGY"),
        help=strategy_help,
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        default=not env_flag("TRADING_SHOW_DASHBOARD", True),
        help=(
            "只启动 API，不自动打开 trading Dashboard 窗口。"
            "也可设置环境变量 TRADING_SHOW_DASHBOARD=0。"
        ),
    )
    parser.add_argument(
        "--dashboard-refresh-ms",
        type=int,
        default=int(os.getenv("TRADING_DASHBOARD_REFRESH_MS", "15000")),
        help="Dashboard 刷新间隔，单位毫秒。默认: 15000。",
    )
    parser.add_argument(
        "--symbols",
        default=os.getenv("TRADING_SYMBOLS"),
        help=(
            "股票池，使用 trading 纯代码格式，多个代码用英文逗号分隔。"
            "示例: 688041,688256,688981。"
            "默认使用半导体 / AI 芯片观察池。环境变量: TRADING_SYMBOLS。"
        ),
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("TRADING_DB_PATH", default_db_path),
        help=f"SQLite 数据库路径。默认: {default_db_path}。环境变量: TRADING_DB_PATH。",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("TRADING_HOST", "127.0.0.1"),
        help="API 服务绑定地址。默认: 127.0.0.1。环境变量: TRADING_HOST。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TRADING_PORT", str(default_port))),
        help=f"API 服务端口。默认: {default_port}。环境变量: TRADING_PORT。",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=float(os.getenv("TRADING_INITIAL_CAPITAL", "100000")),
        help=(
            "模拟盘初始资金；实盘模板会忽略该参数。默认: 100000。"
            "环境变量: TRADING_INITIAL_CAPITAL。"
        ),
    )
    parser.add_argument(
        "--cron",
        default=os.getenv("TRADING_CRON", "0 14 * * 1-5"),
        help="交易循环调度 cron 表达式。默认: 0 14 * * 1-5。",
    )
    parser.add_argument(
        "--backfill-start",
        default=os.getenv("TRADING_BACKFILL_START"),
        help=(
            "回填开始日期，例如 2025-01-01。"
            "若启用回填且未设置，则默认从 180 天前开始。"
        ),
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        default=not env_flag("TRADING_ENABLE_BACKFILL", True),
        help="关闭回填模式。也可设置环境变量 TRADING_ENABLE_BACKFILL=0。",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        default=not env_flag("TRADING_AUTO_START", True),
        help="只创建 session，不自动启动调度器。",
    )
    args = parser.parse_args(argv)

    return TradingBootstrapConfig(
        template=args.template,
        backend=args.backend,
        strategies=parse_strategy_names(args.strategies),
        symbols=parse_symbols(args.symbols),
        db_path=args.db_path,
        host=args.host,
        port=args.port,
        initial_capital=args.initial_capital,
        cron_expression=args.cron,
        auto_start=not args.no_auto_start,
        enable_backfill=not args.no_backfill,
        backfill_start=args.backfill_start,
        show_dashboard=not args.no_dashboard,
        dashboard_refresh_interval_ms=args.dashboard_refresh_ms,
    )


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"缺少必要环境变量: {name}。"
            "MiniQMT 实盘交易需要设置 MINIQMT_USERDATA_DIR 和 "
            "MINIQMT_STOCK_ACCOUNT。"
        )
    return value


__all__ = [
    "DEFAULT_SYMBOLS",
    "TradingBootstrapConfig",
    "WatchlistSelectionConfig",
    "WatchlistSelectionProvider",
    "build_live_manager",
    "build_manager",
    "build_market_data_service",
    "build_paper_manager",
    "parse_strategy_names",
    "parse_bootstrap_args",
    "registered_strategy_names",
    "run_trading_service",
    "run_live_from_cli",
    "run_paper_from_cli",
]
