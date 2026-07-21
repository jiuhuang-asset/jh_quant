"""sync 主循环 — 串联 source → target → watermark。

- 每表异常隔离：一张表失败不阻塞其他表
- 分批写入：避免大表一次性撑爆内存
- 每表成功后立刻落盘 watermark，支持断点续传
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from typing import Callable as _Callable

from .source import SQLiteSource
from .tables import TableSyncSpec, resolve_specs
from .target import PostgresTarget
from .watermark import (
    SyncState,
    default_state_path,
    load_state,
    save_state,
    source_fingerprint,
)

_LOG = logging.getLogger("jh_quant.trading.sync.syncer")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class TableResult:
    """单张表的同步结果。"""

    name: str
    mode: str
    rows_read: int = 0
    rows_written: int = 0
    watermark_before: Optional[datetime] = None
    watermark_after: Optional[datetime] = None
    duration_s: float = 0.0
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class SyncReport:
    """整次 sync 的汇总报告。"""

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    full_reset: bool = False
    dry_run: bool = False
    source_path: str = ""
    table_results: List[TableResult] = field(default_factory=list)

    def add(self, result: TableResult) -> None:
        self.table_results.append(result)

    @property
    def all_succeeded(self) -> bool:
        return all(r.succeeded for r in self.table_results)

    @property
    def total_read(self) -> int:
        return sum(r.rows_read for r in self.table_results)

    @property
    def total_written(self) -> int:
        return sum(r.rows_written for r in self.table_results)

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        header = (
            f"{'table':30s}  {'mode':12s}  {'read':>6s}  {'written':>8s}  "
            f"{'duration':>9s}  status"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for r in self.table_results:
            status = "ok" if r.succeeded else f"FAIL: {r.error}"
            lines.append(
                f"{r.name:30s}  {r.mode:12s}  {r.rows_read:>6d}  "
                f"{r.rows_written:>8d}  {r.duration_s:>7.2f}s  {status}"
            )
        lines.append("-" * len(header))
        lines.append(
            f"TOTAL: read={self.total_read} written={self.total_written} "
            f"success={sum(1 for r in self.table_results if r.succeeded)}/"
            f"{len(self.table_results)}"
        )
        return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunked(seq: Sequence[dict], size: int) -> Iterable[Sequence[dict]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _max_watermark(spec: TableSyncSpec, rows: Sequence[dict]) -> Optional[datetime]:
    if not rows:
        return None
    wm_field = spec.watermark_field
    values = [r.get(wm_field) for r in rows if r.get(wm_field) is not None]
    if not values:
        return None
    return max(values)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_sync(
    source_db_path: str,
    target_dsn: str,
    *,
    tables: Optional[Sequence[str]] = None,
    since: Optional[datetime] = None,
    full_reset: bool = False,
    dry_run: bool = False,
    chunk_size: int = 500,
    state_path: Optional[Path] = None,
    _target_factory: Optional[_Callable[[str], object]] = None,
) -> SyncReport:
    """执行一次完整 sync。

    Args:
        source_db_path: 本地 SQLite DB 路径。
        target_dsn: 远端 Postgres / Neon DSN。
        tables: 要同步的表名列表；``None`` = 全部 7 张。
        since: 强制覆盖 watermark。
        full_reset: 先 truncate 远端再全量同步。
        dry_run: 只读 + 计数，不写入。
        chunk_size: 单批写入行数。
        state_path: watermark 文件路径。

    Returns:
        :class:`SyncReport` 实例。
    """
    specs = resolve_specs(list(tables) if tables else None)
    if not specs:
        _LOG.info("没有可同步的表，退出")
        return SyncReport(source_path=source_db_path)

    if state_path is None:
        state_path = default_state_path()

    report = SyncReport(
        full_reset=full_reset,
        dry_run=dry_run,
        source_path=source_db_path,
    )

    # 1. 加载 watermark（指纹用于检测来源 DB 是否被替换）
    fp = source_fingerprint(source_db_path)
    state = load_state(state_path, fingerprint=fp)

    # 2. dry-run 分支：只读源不连远端
    if dry_run:
        _LOG.info("dry-run: 跳过远端连接，仅读源 + 计数")
        with SQLiteSource(db_path=source_db_path) as source:
            for spec in specs:
                result = TableResult(
                    name=spec.name,
                    mode=spec.mode,
                    watermark_before=state.since_for(spec),
                )
                started = datetime.now(timezone.utc)
                try:
                    _sync_one_table(
                        spec=spec,
                        source=source,
                        target=None,
                        state=state,
                        result=result,
                        since_override=since,
                        dry_run=True,
                        chunk_size=chunk_size,
                    )
                except Exception as exc:
                    result.error = f"{type(exc).__name__}: {exc}"
                    _LOG.error(
                        "dry-sync %s 失败: %s\n%s",
                        spec.name, exc, traceback.format_exc(),
                    )
                finally:
                    result.duration_s = (
                        datetime.now(timezone.utc) - started
                    ).total_seconds()
                    report.add(result)
        report.finished_at = datetime.now(timezone.utc)
        return report

    # 3. 正常同步
    factory = _target_factory or (lambda dsn: PostgresTarget(conninfo=dsn))
    target = factory(target_dsn)
    try:
        # 确保远端表存在（仅生产 PostgresTarget 走这个路径；测试注入跳过）
        if not dry_run and _target_factory is None:
            from .target import generate_postgres_schema

            _LOG.info("确保远端 schema 就绪 ...")
            generate_postgres_schema(target_dsn)

        if full_reset:
            _LOG.info("--full-reset: 清空远端 7 张表")
            target.truncate_all()
            state = SyncState.empty(fingerprint=fp)

        with SQLiteSource(db_path=source_db_path) as source:
            for spec in specs:
                result = TableResult(
                    name=spec.name,
                    mode=spec.mode,
                    watermark_before=state.since_for(spec),
                )
                started = datetime.now(timezone.utc)
                try:
                    _sync_one_table(
                        spec=spec,
                        source=source,
                        target=target,
                        state=state,
                        result=result,
                        since_override=since,
                        dry_run=False,
                        chunk_size=chunk_size,
                    )
                except Exception as exc:
                    result.error = f"{type(exc).__name__}: {exc}"
                    _LOG.error(
                        "sync %s 失败: %s\n%s",
                        spec.name, exc, traceback.format_exc(),
                    )
                finally:
                    result.duration_s = (
                        datetime.now(timezone.utc) - started
                    ).total_seconds()
                    report.add(result)

                # 每张表成功后立刻落盘（断点续传）
                if result.succeeded:
                    try:
                        save_state(state, state_path)
                    except OSError as exc:
                        _LOG.warning("watermark 落盘失败 (%s)", exc)
    finally:
        target.close()

    report.finished_at = datetime.now(timezone.utc)
    return report


def _sync_one_table(
    *,
    spec: TableSyncSpec,
    source: SQLiteSource,
    target,  # PostgresTarget | None (dry-run)
    state: SyncState,
    result: TableResult,
    since_override: Optional[datetime],
    dry_run: bool,
    chunk_size: int,
) -> None:
    """处理单张表；异常向上抛由 ``run_sync`` 记录。"""

    start_wm = since_override or state.since_for(spec)
    _LOG.info("[%s] mode=%s watermark=%s", spec.name, spec.mode, start_wm)

    # 1. 流式读
    rows: List[dict] = []
    for batch in source.iter_rows(spec, since=start_wm, batch_size=chunk_size):
        rows.extend(batch)
    result.rows_read = len(rows)

    if dry_run:
        _LOG.info("[%s] dry-run: would %s %d rows", spec.name, spec.mode, len(rows))
        return

    if not rows:
        _LOG.info("[%s] 没有新行", spec.name)
        return

    # 2. 分批写入
    written = 0
    for batch in _chunked(rows, chunk_size):
        if spec.mode == "upsert":
            written += target.upsert(spec, batch)
        else:
            written += target.insert_only(spec, batch)
    result.rows_written = written

    # 3. 推进 watermark
    new_wm = _max_watermark(spec, rows)
    state.update(spec, since=new_wm, last_run=datetime.now(timezone.utc))
    _LOG.info(
        "[%s] 完成 read=%d written=%d new_watermark=%s",
        spec.name, len(rows), written, new_wm,
    )


__all__ = [
    "SyncReport",
    "TableResult",
    "run_sync",
]
