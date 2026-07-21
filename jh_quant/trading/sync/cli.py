"""sync CLI — ``jh-quant sync ...``

环境变量（优先级从高到低）：
    NEON_PG_URL > TRADING_REMOTE_DSN
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from .syncer import run_sync
from .tables import list_default_tables
from .watermark import default_state_path

_LOG = logging.getLogger("jh_quant.trading.sync.cli")


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def _env_dsn() -> Optional[str]:
    """优先级：NEON_PG_URL > TRADING_REMOTE_DSN。"""
    return (
        os.getenv("NEON_PG_URL")
        or os.getenv("TRADING_REMOTE_DSN")
        or None
    )


def _env_state_path() -> Optional[Path]:
    raw = os.getenv("TRADING_SYNC_STATE_PATH")
    if not raw:
        return None
    return Path(raw).expanduser()


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jh-quant sync",
        description="把本地 trading SQLite 数据增量同步到远程 Neon/Postgres 数据库。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 一次性全量同步（DSN 从环境变量取）\n"
            "  NEON_PG_URL=postgresql://... jh-quant sync --from trade_paper.db\n"
            "\n"
            "  # 预览（不写）\n"
            "  jh-quant sync --from trade_paper.db --to postgresql://... --dry-run\n"
            "\n"
            "  # 守护模式：每 5 分钟一次\n"
            "  jh-quant sync --from trade_paper.db --to postgresql://... --watch\n"
        ),
    )
    p.add_argument(
        "--from", dest="source_db_path", required=True,
        help="本地 SQLite DB 路径（例如 trade_paper.db）。",
    )
    p.add_argument(
        "--to", dest="target_dsn", default=_env_dsn(),
        help="目标 Neon/Postgres DSN。缺省走环境变量 NEON_PG_URL。",
    )
    p.add_argument(
        "--tables", default=None,
        help=(
            "只同步指定表，逗号分隔。"
            f"可选: {', '.join(list_default_tables())}。缺省 = 全部。"
        ),
    )
    p.add_argument(
        "--since", default=None,
        help="ISO 时间戳，覆盖 watermark 上界。",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="只读 + 计数，不实际写入远程。",
    )
    p.add_argument(
        "--full-reset", action="store_true",
        help="先 TRUNCATE 远程表再灌。必须同时加 --yes-i-know。",
    )
    p.add_argument(
        "--yes-i-know", action="store_true",
        help="--full-reset 的二次确认开关。",
    )
    p.add_argument(
        "--chunk-size", type=int, default=500,
        help="单批写入行数。默认 500。",
    )
    p.add_argument(
        "--state-path", dest="state_path",
        default=_env_state_path() or default_state_path(),
        help="watermark 状态文件路径。",
    )
    p.add_argument(
        "--watch", action="store_true",
        help="守护模式：循环跑 sync；Ctrl-C 退出。",
    )
    p.add_argument(
        "--interval", type=int, default=300,
        help="守护模式间隔秒数。默认 300 (5 分钟)。",
    )
    p.add_argument(
        "--log-level", default=os.getenv("JH_SYNC_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别。默认 INFO。",
    )
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_since(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise SystemExit(f"--since 解析失败: {exc}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_tables(raw: Optional[str]) -> Optional[list[str]]:
    if raw is None or not raw.strip():
        return None
    return [t.strip() for t in raw.split(",") if t.strip()]


def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger("jh_quant.trading.sync")
    root.setLevel(level)
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------


class _WatchStop:
    def __init__(self):
        self._flag = threading.Event()

    def set(self):
        self._flag.set()

    def is_set(self):
        return self._flag.is_set()

    def wait(self, seconds: float) -> bool:
        return self._flag.wait(seconds)


def _install_signal_handlers(stop: _WatchStop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run_once(args: argparse.Namespace) -> int:
    target_dsn = args.target_dsn
    if not target_dsn:
        _LOG.error(
            "缺少目标 DSN：通过 --to 显式指定，或设置环境变量 "
            "NEON_PG_URL / TRADING_REMOTE_DSN"
        )
        return 2

    if args.full_reset and not args.yes_i_know:
        _LOG.error("--full-reset 必须同时加 --yes-i-know 二次确认")
        return 2

    report = run_sync(
        source_db_path=args.source_db_path,
        target_dsn=target_dsn,
        tables=_parse_tables(args.tables),
        since=_parse_since(args.since),
        full_reset=args.full_reset,
        dry_run=args.dry_run,
        chunk_size=args.chunk_size,
        state_path=Path(args.state_path).expanduser(),
    )

    print()
    for line in report.summary_lines():
        print(line)

    if not report.all_succeeded:
        _LOG.error("部分或全部表同步失败")
        return 1
    return 0


def _run_watch(args: argparse.Namespace) -> int:
    interval = max(args.interval, 1)
    stop = _WatchStop()
    _install_signal_handlers(stop)
    _LOG.info("守护模式启动：每 %ss 跑一次 sync，Ctrl-C 退出", interval)

    while not stop.is_set():
        try:
            _run_once(args)
        except Exception as exc:
            _LOG.exception("本次 sync 抛错：%s", exc)

        if stop.is_set():
            break
        _LOG.info("等待 %ss 后下一次 run ...", interval)
        stop.wait(interval)

    _LOG.info("收到退出信号，守护模式结束")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    args = parser.parse_args(list(argv))
    _setup_logging(args.log_level)

    if args.watch:
        return _run_watch(args)
    return _run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
