"""Table sync specs — 7 张表的同步策略定义。

每个 spec 只需要：表名、同步模式、watermark 字段、冲突键列表。
不再依赖 Tortoise 模型，纯配置。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

SyncMode = Literal["upsert", "insert_only"]


@dataclass(frozen=True)
class TableSyncSpec:
    """描述一张表的同步策略。"""

    name: str
    table: str
    mode: SyncMode
    watermark_field: str
    conflict_columns: Tuple[str, ...] = ()
    chunk_size: int = 500


# 7 张表定义（与 persistence/models.py 的表结构对齐）
DEFAULT_TABLE_SPECS: dict[str, TableSyncSpec] = {
    "trades": TableSyncSpec(
        name="trades",
        table="trades",
        mode="upsert",
        watermark_field="created_at",
        conflict_columns=("trade_id",),
    ),
    "daily_performances": TableSyncSpec(
        name="daily_performances",
        table="daily_performances",
        mode="upsert",
        watermark_field="created_at",
        conflict_columns=("session_id", "trade_date"),
    ),
    "positions_snapshot": TableSyncSpec(
        name="positions_snapshot",
        table="positions_snapshot",
        mode="upsert",
        watermark_field="created_at",
        conflict_columns=("snapshot_id",),
    ),
    "session_states": TableSyncSpec(
        name="session_states",
        table="session_states",
        mode="insert_only",
        watermark_field="export_time",
        conflict_columns=("session_id", "export_time"),
    ),
    "session_runtime_states": TableSyncSpec(
        name="session_runtime_states",
        table="session_runtime_states",
        mode="upsert",
        watermark_field="export_time",
        conflict_columns=("session_id",),
    ),
    "session_config_records": TableSyncSpec(
        name="session_config_records",
        table="session_config_records",
        mode="insert_only",
        watermark_field="export_time",
        conflict_columns=("session_id", "config_md5"),
    ),
    "session_runtime_events": TableSyncSpec(
        name="session_runtime_events",
        table="session_runtime_events",
        mode="insert_only",
        watermark_field="event_time",
        conflict_columns=("id",),
    ),
}


def list_default_tables() -> list[str]:
    """返回默认 7 张表的符号名（按字母序）。"""
    return sorted(DEFAULT_TABLE_SPECS.keys())


def get_spec(name: str) -> TableSyncSpec:
    """按符号名获取 spec；不存在则抛 ``KeyError``。"""
    if name not in DEFAULT_TABLE_SPECS:
        raise KeyError(
            f"Unknown table: {name!r}. "
            f"Available: {', '.join(list_default_tables())}"
        )
    return DEFAULT_TABLE_SPECS[name]


def resolve_specs(names: list[str] | None) -> list[TableSyncSpec]:
    """把 CLI 传来的 ``--tables`` 列表解析为 spec 列表。

    ``None`` 或空列表表示全部默认表。
    """
    if not names:
        return [DEFAULT_TABLE_SPECS[n] for n in list_default_tables()]
    return [get_spec(n.strip()) for n in names if n.strip()]


__all__ = [
    "DEFAULT_TABLE_SPECS",
    "SyncMode",
    "TableSyncSpec",
    "get_spec",
    "list_default_tables",
    "resolve_specs",
]
