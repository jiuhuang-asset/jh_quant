"""统一的 jh_quant CLI 入口
* ``paper``  → ``trading.bootstrap.run_paper_from_cli``
* ``live``   → ``trading.bootstrap.run_live_from_cli``
* ``sync``   → ``trading.sync.cli.main``（Phase A 占位，Phase F 替换为完整 argparse）

"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence

from .trading.bootstrap import registered_strategy_names

_PAPER_BACKENDS = ["tushare", "akshare"]
_LIVE_BACKENDS = ["tushare", "akshare", "xquant"]
_DEFAULT_PAPER_BACKEND = "tushare"
_DEFAULT_LIVE_BACKEND = "tushare"
_DEFAULT_PAPER_STRATEGIES = "momentum"
_DEFAULT_LIVE_STRATEGIES = "momentum"
_DEFAULT_PAPER_TEMPLATE = "paper-compare"
_DEFAULT_LIVE_TEMPLATE = "live-basic"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _add_common_trading_args(
    parser: argparse.ArgumentParser,
    *,
    default_template: str,
    default_db_path: str,
    default_port: int,
    backends: List[str],
    default_backend: str,
    backend_env: str = "TRADING_BACKEND",
    default_strategies: str,
    hide_initial_capital: bool = False,
    show_template_only: bool = False,
) -> None:
    """为 paper / live 子命令注册共享参数。"""

    strategy_list = ", ".join(registered_strategy_names())

    # -- 模板 / 行情 ----
    template_group = parser.add_argument_group("模板与行情")
    if not show_template_only:
        template_group.add_argument(
            "--template",
            default=os.getenv("TRADING_TEMPLATE", default_template),
            help=(
                "Bootstrap 启动模板。"
                f"默认: {default_template}。"
                "环境变量: TRADING_TEMPLATE。"
            ),
        )
    template_group.add_argument(
        "--backend",
        default=os.getenv(backend_env, default_backend),
        help=(
            f"行情数据后端，可选: {', '.join(backends)}。"
            f"默认: {default_backend}。"
            f"环境变量: {backend_env}。"
        ),
    )

    # -- 策略与选股 ----
    strat_group = parser.add_argument_group("策略与选股")
    strat_group.add_argument(
        "--strategy",
        dest="strategies",
        default=os.getenv("TRADING_STRATEGY", default_strategies),
        help=(
            "策略名称，多个策略用英文逗号分隔。"
            f"可选策略: {strategy_list}。"
            "示例: --strategy turtle 或 --strategy turtle,momentum。"
            "环境变量: TRADING_STRATEGY。"
        ),
    )
    strat_group.add_argument(
        "--symbols",
        default=os.getenv("TRADING_SYMBOLS"),
        help=(
            "股票池，多个代码用英文逗号分隔（纯数字格式，如 688041,688256）。"
            "默认使用半导体 / AI 芯片观察池。"
            "环境变量: TRADING_SYMBOLS。"
        ),
    )

    # -- 服务 ----
    svc_group = parser.add_argument_group("服务配置")
    svc_group.add_argument(
        "--host",
        default=os.getenv("TRADING_HOST", "127.0.0.1"),
        help="API 服务绑定地址。默认: 127.0.0.1。环境变量: TRADING_HOST。",
    )
    svc_group.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TRADING_PORT", str(default_port))),
        help=f"API 服务端口。默认: {default_port}。环境变量: TRADING_PORT。",
    )
    svc_group.add_argument(
        "--db-path",
        default=os.getenv("TRADING_DB_PATH", default_db_path),
        help=f"SQLite 数据库文件路径。默认: {default_db_path}。环境变量: TRADING_DB_PATH。",
    )

    # -- 资金（仅 paper 显示） --
    if not hide_initial_capital:
        cap_group = parser.add_argument_group("资金与调度")
        cap_group.add_argument(
            "--initial-capital",
            type=float,
            default=float(os.getenv("TRADING_INITIAL_CAPITAL", "100000")),
            help=(
                "模拟盘初始资金（元）；实盘模板忽略此参数。"
                "默认: 100000。环境变量: TRADING_INITIAL_CAPITAL。"
            ),
        )
        cap_group.add_argument(
            "--cron",
            default=os.getenv("TRADING_CRON", "0 14 * * 1-5"),
            help="交易循环 cron 表达式（5 段式）。默认: 0 14 * * 1-5（交易日 14:00）。",
        )
    else:
        cap_group = parser.add_argument_group("资金与调度")
        cap_group.add_argument(
            "--cron",
            default=os.getenv("TRADING_CRON", "0 14 * * 1-5"),
            help="交易循环 cron 表达式（5 段式）。默认: 0 14 * * 1-5（交易日 14:00）。",
        )

    # -- 回填 ----
    backfill_group = parser.add_argument_group("回填控制")
    backfill_group.add_argument(
        "--backfill-start",
        default=os.getenv("TRADING_BACKFILL_START"),
        help=(
            "回填起始日期（YYYY-MM-DD），例如 2025-01-01。"
            "不设置则默认从 180 天前开始回填。"
            "环境变量: TRADING_BACKFILL_START。"
        ),
    )
    backfill_group.add_argument(
        "--no-backfill",
        action="store_true",
        default=not _env_flag("TRADING_ENABLE_BACKFILL", True),
        help="关闭回填模式，仅使用实时行情。也可设置环境变量 TRADING_ENABLE_BACKFILL=0。",
    )

    # -- 仪表盘 / 调度 ----
    ui_group = parser.add_argument_group("仪表盘与调度")
    ui_group.add_argument(
        "--no-dashboard",
        action="store_true",
        default=not _env_flag("TRADING_SHOW_DASHBOARD", True),
        help=(
            "只启动 API 服务，不弹出 trading Dashboard 窗口。"
            "也可设置环境变量 TRADING_SHOW_DASHBOARD=0。"
        ),
    )
    ui_group.add_argument(
        "--dashboard-refresh-ms",
        type=int,
        default=int(os.getenv("TRADING_DASHBOARD_REFRESH_MS", "15000")),
        help="Dashboard 数据刷新间隔（毫秒）。默认: 15000。",
    )
    ui_group.add_argument(
        "--no-auto-start",
        action="store_true",
        default=not _env_flag("TRADING_AUTO_START", True),
        help="只创建 session，不自动启动交易调度器。",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jh-quant",
        description=(
            "Jiuhuang trading CLI: 统一入口，覆盖模拟盘 (paper)、"
            "实盘 (live)、本地数据同步到远程数据库 (sync)。"
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        metavar="<subcommand>",
        title="subcommands",
    )
    sub.required = True

    # ---- paper ----
    paper_parser = sub.add_parser(
        "paper",
        help="启动模拟盘服务（Paper Trading）",
        description=(
            "启动模拟盘交易服务。使用 PaperBroker 本地模拟成交，"
            "支持回填（backfill）和实时（realtime）两种时钟模式。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "启动示例:\n"
            "  # 默认启动（半导体观察池，tushare 行情）\n"
            "  jh-quant paper\n"
            "\n"
            "  # 指定策略\n"
            "  jh-quant paper --strategy turtle,momentum\n"
            "\n"
            "  # 自定义股票池 + 初始资金\n"
            "  jh-quant paper --symbols 688041,688256 --initial-capital 200000\n"
            "\n"
            "  # 纯 API 模式（不弹出 Dashboard）\n"
            "  jh-quant paper --no-dashboard --port 8080\n"
            "\n"
            "  # 关闭回填，仅实时行情\n"
            "  jh-quant paper --no-backfill\n"
        ),
    )
    _add_common_trading_args(
        paper_parser,
        default_template=_DEFAULT_PAPER_TEMPLATE,
        default_db_path="trade_paper.db",
        default_port=8000,
        backends=_PAPER_BACKENDS,
        default_backend=_DEFAULT_PAPER_BACKEND,
        default_strategies=_DEFAULT_PAPER_STRATEGIES,
        hide_initial_capital=False,
        show_template_only=False,
    )

    # ---- live ----
    live_parser = sub.add_parser(
        "live",
        help="启动实盘服务（Live Trading）",
        description=(
            "启动实盘交易服务。必须配置真实 Broker（如 XtQuant/MiniQMT），"
            "仅支持实时时钟模式，不支持回填。"
            "\n\n"
            "运行前需设置环境变量:\n"
            "  MINIQMT_USERDATA_DIR    MiniQMT userdata 目录\n"
            "  MINIQMT_STOCK_ACCOUNT   股票账户号\n"
            "  MINIQMT_TRADER_SESSION_ID  交易会话 ID（可选）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "启动示例:\n"
            "  # 默认启动\n"
            "  jh-quant live\n"
            "\n"
            "  # 指定策略 + 自定义股票池\n"
            "  jh-quant live --strategy turtle --symbols 688041,688256\n"
            "\n"
            "  # 纯 API 模式\n"
            "  jh-quant live --no-dashboard --port 8080\n"
        ),
    )
    _add_common_trading_args(
        live_parser,
        default_template=_DEFAULT_LIVE_TEMPLATE,
        default_db_path="trade_live.db",
        default_port=8000,
        backends=_LIVE_BACKENDS,
        default_backend=_DEFAULT_LIVE_BACKEND,
        default_strategies=_DEFAULT_LIVE_STRATEGIES,
        hide_initial_capital=True,
        show_template_only=False,
    )

    # ---- sync ----
    sub.add_parser(
        "sync",
        help="同步本地 trading 数据到远程 Postgres 数据库",
        add_help=False,
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """统一 CLI 入口。

    Args:
        argv: 命令行参数序列；``None`` 表示 ``sys.argv[1:]``。

    Returns:
        进程退出码（0 = 成功）。
    """

    if argv is None:
        argv = sys.argv[1:]

    argv_list = list(argv)

    # 当用户传入 -h / --help 时，让完整的 argparse 接管以展示所有选项说明。
    # 否则只提取子命令名，剩余参数全部委托给对应子命令的 parser（bootstrap 或 sync）。
    if "-h" in argv_list or "--help" in argv_list:
        parser = _build_parser()
        parser.parse_args(argv_list)
        return 0

    if not argv_list:
        _build_parser().print_help()
        return 1

    command = argv_list[0]
    rest = argv_list[1:]

    if command == "paper":
        from .trading.bootstrap import run_paper_from_cli

        run_paper_from_cli(rest)
        return 0

    if command == "live":
        from .trading.bootstrap import run_live_from_cli

        run_live_from_cli(rest)
        return 0

    if command == "sync":
        from .trading.sync.cli import main as sync_main

        return int(sync_main(rest) or 0)

    _build_parser().print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
