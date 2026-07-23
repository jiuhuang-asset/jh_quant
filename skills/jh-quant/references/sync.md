# 数据同步模块 (sync)

## 快速开始

```bash
# 单次全量同步（DSN 从环境变量取）
REMOTE_DB_URL=postgresql://user:pass@host/db jh-quant sync --from trade_paper.db

# 显式指定目标 DSN
jh-quant sync --from trade_paper.db --to postgresql://user:pass@host/db

# 预览模式（只读不写）
jh-quant sync --from trade_paper.db --dry-run
```

## 为什么需要 sync

Trading 模块（`jh-quant paper` / `jh-quant live`）运行时将交易记录写入本地 SQLite。sync 负责将本地数据非侵入式同步到远程 Postgres，支撑：

- 远程 Dashboard 展示
- 多实例数据聚合
- 历史数据分析与报表
- 数据备份与容灾

## 数据流

```
本地 jh-quant paper/live
        │
        │  sqlite
        ▼
   jh-quant sync ──────▶ Neon/Postgres ◀──── jh_quant_rn_app
                         (远程数据库)          (手机 App)
```

## 环境要求

- 目标数据库：Postgres 15+（兼容 Neon Serverless）
- 本地仅需 SQLite 文件（由 paper/live 自动生成）

## 免费远程数据库（Neon）

1. [neon.tech](https://neon.tech) 注册，免费套餐 0.5 GB 存储
2. 创建项目 → Dashboard → Connection Details → 复制 DSN
3. 设置环境变量：`export REMOTE_DB_URL="postgresql://user:pass@host/db"`

## 环境变量

| 变量 | 说明 | 优先级 |
|------|------|--------|
| `REMOTE_DB_URL` | 远程 Postgres DSN | 最高 |
| `TRADING_REMOTE_DSN` | 备选 DSN | 次之 |
| `TRADING_SYNC_STATE_PATH` | watermark 状态文件路径 | — |
| `JH_SYNC_LOG_LEVEL` | 日志级别，默认 INFO | — |

## CLI 全部选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--from` | str | 必填 | 本地 SQLite 数据库路径 |
| `--to` | str | 环境变量 | 远程 Postgres DSN |
| `--tables` | str | 全部 | 指定同步的表，逗号分隔 |
| `--since` | str | — | ISO 时间戳，覆盖对应表的 watermark 上界 |
| `--dry-run` | flag | — | 预览模式，只读取源数据并计数 |
| `--full-reset` | flag | — | TRUNCATE 远程表再全量同步（需 `--yes-i-know`） |
| `--yes-i-know` | flag | — | `--full-reset` 的二次确认 |
| `--chunk-size` | int | 500 | 单批写入行数 |
| `--state-path` | str | `~/.jiuhuang/sync_state.json` | watermark 状态文件路径 |
| `--watch` | flag | — | 守护模式：循环执行，Ctrl-C 退出 |
| `--interval` | int | 300 | 守护模式下的同步间隔（秒） |
| `--log-level` | str | INFO | 日志级别 |

## 守护模式

```bash
# 每 5 分钟自动同步一次
jh-quant sync --from trade_paper.db --watch

# 自定义间隔（秒）
jh-quant sync --from trade_paper.db --watch --interval 600
```

## 同步的 7 张核心表

| 表名 | 同步模式 | 水印字段 | 冲突列 |
|------|----------|----------|--------|
| `trades` | upsert | `created_at` | `(trade_id,)` |
| `daily_performances` | upsert | `created_at` | `(session_id, trade_date)` |
| `positions_snapshot` | upsert | `created_at` | `(snapshot_id,)` |
| `session_states` | insert_only | `export_time` | `(session_id, export_time)` |
| `session_runtime_states` | upsert | `export_time` | `(session_id,)` |
| `session_config_records` | insert_only | `export_time` | `(session_id, config_md5)` |
| `session_runtime_events` | insert_only | `event_time` | `(id,)` |

### 同步模式说明

- **upsert**：已存在的行按最新值更新，新行直接插入（适用于状态会变化的表）
- **insert_only**：已存在的行跳过不更新（适用于只追加的事件日志和配置快照）

## 增量机制（Watermark）

```
第一次同步：拉取所有行 → watermark = max(watermark_field)
第二次同步：拉取 watermark 之后的新增/变更行 → 推进 watermark
...
```

水印持久化到 `~/.jiuhuang/sync_state.json`，包含：
- 每张表最近一次成功同步的 `since` 时间戳
- 源数据库指纹（文件大小 + mtime）

**断点续传**：每张表成功后立即落盘水印。如果第 4 张失败，前 3 张水印已保存，重启后从第 4 张继续。

### 重置水印

```bash
jh-quant sync --from trade_paper.db --full-reset --yes-i-know
```

## 编程调用

```python
from jh_quant.trading.sync import run_sync

report = run_sync(
    source_db_path="trade_paper.db",
    target_dsn="postgresql://user:pass@host/db",
    tables=["trades", "daily_performances"],  # 仅同步部分表
    dry_run=True,                              # 预览
)

for line in report.summary_lines():
    print(line)
```

## 架构

```
┌──────────────┐     ┌───────────────┐
│ SQLiteSource │────▶│ PostgresTarget│
│  (本地只读)   │     │  (远程写入)    │
└──────┬───────┘     └───────┬───────┘
       │                     │
       │     run_sync()      │
       │   watermark 驱动     │
       │   分批 upsert        │
       └──────────┬──────────┘
                  │
             SyncState
           (JSON 水印文件)
        ~/.jiuhuang/sync_state.json
```

核心组件：
- **`run_sync()`**：主循环，按 `resolve_specs()` 确定的表顺序依次同步，每表异常隔离
- **`SQLiteSource`**：从本地 SQLite 流式读取行
- **`PostgresTarget`**：写入远程 Postgres，自动建表
- **`SyncState`**：JSON 格式水印文件

## 输出示例

```
18:23:45 [INFO] [trades] mode=upsert watermark=None
18:23:46 [INFO] [trades] 完成 read=1250 written=1250 new_watermark=2026-07-22 14:30:05+00:00
...

table                            mode           read   written   duration  status
-----------------------------------------------------------------------------------------
trades                           upsert         1250       1250      0.84s  ok
daily_performances               upsert            3          3      0.12s  ok
positions_snapshot               upsert           10         10      0.09s  ok
session_states                   insert_only       2          2      0.08s  ok
session_runtime_states           upsert            2          2      0.07s  ok
session_config_records           insert_only       1          1      0.06s  ok
session_runtime_events           insert_only       0          0      0.05s  ok
-----------------------------------------------------------------------------------------
TOTAL: read=1268 written=1268 success=7/7
```
