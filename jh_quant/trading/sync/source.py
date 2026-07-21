"""SQLite source — 用 stdlib sqlite3 直接读本地 trading DB。

Tortoise 把 datetime 存为 ISO 字符串（空格分隔），读出来后尝试还原为
``datetime`` / ``date`` 对象。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional

from .tables import TableSyncSpec


class SQLiteSource:
    """从本地 SQLite 读取交易数据的轻量封装。"""

    def __init__(self, db_path: str):
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(f"SQLite DB not found: {db_path}")
        self._db_path = str(path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SQLiteSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    # ----- public API -----

    def iter_rows(
        self,
        spec: TableSyncSpec,
        since: Optional[datetime] = None,
        *,
        batch_size: Optional[int] = None,
    ) -> Iterator[List[dict]]:
        """流式分页读取行，返回 ``list[dict]`` 批次。"""
        if batch_size is None:
            batch_size = spec.chunk_size
        columns = self._columns(spec.table)
        order = ", ".join([spec.watermark_field, *spec.conflict_columns])
        offset = 0
        while True:
            if since is not None:
                sql = (
                    f"SELECT {', '.join(columns)} FROM {spec.table} "
                    f"WHERE {spec.watermark_field} >= ? "
                    f"ORDER BY {order} LIMIT ? OFFSET ?"
                )
                params: tuple = (self._fmt(since), batch_size, offset)
            else:
                sql = (
                    f"SELECT {', '.join(columns)} FROM {spec.table} "
                    f"ORDER BY {order} LIMIT ? OFFSET ?"
                )
                params = (batch_size, offset)
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                break
            yield [self._convert_row(dict(r), spec) for r in rows]
            offset += batch_size

    def latest_watermark(self, spec: TableSyncSpec) -> Optional[datetime]:
        """返回该表当前最大 watermark 值；空表返回 ``None``。"""
        wm = spec.watermark_field
        cur = self._conn.execute(f"SELECT MAX({wm}) FROM {spec.table}")
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        val = row[0]
        if isinstance(val, (datetime, date)):
            return val if isinstance(val, datetime) else datetime.combine(val, datetime.min.time())
        if isinstance(val, str):
            return _try_parse_datetime(val)
        return None

    def count(self, spec: TableSyncSpec, since: Optional[datetime] = None) -> int:
        """返回符合 watermark 过滤的行数（``--dry-run`` 预览）。"""
        if since is not None:
            cur = self._conn.execute(
                f"SELECT COUNT(*) FROM {spec.table} "
                f"WHERE {spec.watermark_field} >= ?",
                (self._fmt(since),),
            )
        else:
            cur = self._conn.execute(f"SELECT COUNT(*) FROM {spec.table}")
        return cur.fetchone()[0]

    # ----- helpers -----

    def _columns(self, table: str) -> List[str]:
        cur = self._conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cur.fetchall()]

    @staticmethod
    def _convert_row(row: dict, spec: TableSyncSpec) -> dict:
        """把一行中的 ISO 字符串还原为 datetime/date 对象。"""
        out: dict = {}
        for col, val in row.items():
            out[col] = _convert_value(val)
        return out

    @staticmethod
    def _fmt(value: Any) -> Any:
        """watermark 值序列化：datetime → ISO 空格分隔（匹配 SQLite 存储格式）。"""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat(" ")
        if isinstance(value, date):
            return value.isoformat()
        return value


def _try_parse_datetime(value: str) -> Optional[datetime]:
    """尝试把 ISO 字符串解析为 datetime；失败返回 None。"""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _convert_value(value: Any) -> Any:
    """还原单个值：ISO 字符串 → datetime / date，其他不变。"""
    if value is None:
        return None
    if isinstance(value, (datetime, date, int, float, bool)):
        return value
    if isinstance(value, str):
        # datetime 带时间 → datetime
        dt = _try_parse_datetime(value)
        if dt is not None:
            return dt
        # date（纯日期）→ date
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
        # 可能是 JSON 字符串（用于 state_data 等 JSONField 列），原样返回
    return value


__all__ = ["SQLiteSource"]
