"""sync 水位线持久化 — 简单 JSON 文件，只记每张表的上次同步时间。

原子写（tempfile + os.replace）防止半截 JSON。

来源 DB 识别用 **文件名 + 创建时间** 做指纹：即使同名文件被删除重建，
创建时间不同指纹就不同，自动重置 watermark。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .tables import DEFAULT_TABLE_SPECS, TableSyncSpec

_LOG = logging.getLogger("jh_quant.trading.sync.watermark")

STATE_VERSION = 2


# ---------------------------------------------------------------------------
# Source fingerprint
# ---------------------------------------------------------------------------


def source_fingerprint(db_path: str) -> str:
    """用 ``{文件名}_{ctime_ns}_{ino}`` 标识来源 DB。

    格式: ``trade_paper.db_1784530000_123456``

    文件名 + 创建时间(纳秒) + inode，覆盖两种场景：
    - 换文件 → 文件名不同
    - 同名删除重建 → inode 不同（即使 NTFS 上 ctime 可能复现）
    """
    p = Path(db_path).resolve()
    st = p.stat()
    return f"{p.name}_{st.st_ctime_ns}_{st.st_ino}"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TableWatermark:
    """单张表的水位线。"""

    since: Optional[datetime] = None
    last_run: Optional[datetime] = None


@dataclass
class SyncState:
    """sync 整体状态。

    ``source_fingerprint`` 用来检测来源 DB 是否变动：指纹不同 → 自动重置。
    """

    version: int = STATE_VERSION
    source_fingerprint: str = ""
    tables: Dict[str, TableWatermark] = field(default_factory=dict)
    last_full_run: Optional[datetime] = None

    @classmethod
    def empty(cls, *, fingerprint: str = "") -> "SyncState":
        return cls(
            source_fingerprint=fingerprint,
            tables={name: TableWatermark() for name in DEFAULT_TABLE_SPECS},
        )

    def matches_source(self, fingerprint: str) -> bool:
        if not self.source_fingerprint:
            return True  # 首次运行，没有历史指纹
        return self.source_fingerprint == fingerprint

    def since_for(self, spec: TableSyncSpec) -> Optional[datetime]:
        return self._ensure(spec).since

    def update(
        self,
        spec: TableSyncSpec,
        *,
        since: Optional[datetime] = None,
        last_run: Optional[datetime] = None,
    ) -> None:
        wm = self._ensure(spec)
        if since is not None:
            wm.since = since
        if last_run is not None:
            wm.last_run = last_run

    def _ensure(self, spec: TableSyncSpec) -> TableWatermark:
        if spec.name not in self.tables:
            self.tables[spec.name] = TableWatermark()
        return self.tables[spec.name]


# ---------------------------------------------------------------------------
# JSON (de)serialization
# ---------------------------------------------------------------------------


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_dt(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def state_to_json(state: SyncState) -> dict:
    return {
        "version": state.version,
        "source_fingerprint": state.source_fingerprint,
        "tables": {
            name: {
                "since": _fmt_dt(wm.since),
                "last_run": _fmt_dt(wm.last_run),
            }
            for name, wm in state.tables.items()
        },
        "last_full_run": _fmt_dt(state.last_full_run),
    }


def state_from_json(payload: dict) -> SyncState:
    tables_raw = payload.get("tables") or {}
    tables: Dict[str, TableWatermark] = {}
    for name in DEFAULT_TABLE_SPECS:
        t = tables_raw.get(name, {}) if isinstance(tables_raw, dict) else {}
        tables[name] = TableWatermark(
            since=_parse_dt(t.get("since") if isinstance(t, dict) else None),
            last_run=_parse_dt(t.get("last_run") if isinstance(t, dict) else None),
        )
    # 兼容 v1 的 source_path 字段
    fp = str(payload.get("source_fingerprint", payload.get("source_path", "")))
    return SyncState(
        version=int(payload.get("version", STATE_VERSION)),
        source_fingerprint=fp,
        tables=tables,
        last_full_run=_parse_dt(payload.get("last_full_run")),
    )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def default_state_path() -> Path:
    return Path.home() / ".jiuhuang" / "sync_state.json"


def load_state(path: Optional[Path] = None, *, fingerprint: str = "") -> SyncState:
    """从 JSON 文件加载状态。

    文件不存在/损坏 → 空状态。
    记录的指纹与当前不同 → 来源 DB 已变动，自动重置 watermark。
    """
    if path is None:
        path = default_state_path()
    path = Path(path)

    if not path.exists():
        return SyncState.empty(fingerprint=fingerprint)

    try:
        raw = path.read_text(encoding="utf-8")
        state = state_from_json(json.loads(raw))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _LOG.warning("sync_state.json 损坏（%s），回退到空状态: %s", path, exc)
        return SyncState.empty(fingerprint=fingerprint)

    # 来源 DB 变动检测
    if fingerprint and not state.matches_source(fingerprint):
        _LOG.info(
            "来源 DB 指纹变化（%s → %s），重置 watermark",
            state.source_fingerprint or "(无记录)", fingerprint,
        )
        return SyncState.empty(fingerprint=fingerprint)

    # 兼容：补充缺失的指纹字段（老 state 文件）
    if not state.source_fingerprint:
        state.source_fingerprint = fingerprint
    return state


def save_state(state: SyncState, path: Optional[Path] = None) -> None:
    """原子写 JSON 到 ``path``。"""
    if path is None:
        path = default_state_path()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(
        state_to_json(state), ensure_ascii=False, indent=2, sort_keys=True
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


__all__ = [
    "STATE_VERSION",
    "SyncState",
    "TableWatermark",
    "default_state_path",
    "load_state",
    "save_state",
    "source_fingerprint",
]
