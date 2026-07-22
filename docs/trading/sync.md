# 数据同步

`jh-quant sync` 将本地 SQLite 交易数据增量同步到远程 Postgres/Neon 数据库。

## 快速开始

```bash
# 单次同步
REMOTE_DB_URL=postgresql://... jh-quant sync --from trade_paper.db

# 预览（不实际写入）
jh-quant sync --from trade_paper.db --to postgresql://... --dry-run

# 守护模式（每 300 秒自动同步）
jh-quant sync --from trade_paper.db --to postgresql://... --watch --interval 300
```

目标 DSN 优先级：`REMOTE_DB_URL` > `TRADING_REMOTE_DSN`。

## 同步的表

| 表 | 模式 | 水印字段 | 冲突列 |
| --- | --- | --- | --- |
| `trades` | upsert | `created_at` | `(trade_id,)` |
| `daily_performances` | upsert | `created_at` | `(session_id, trade_date)` |
| `positions_snapshot` | upsert | `created_at` | `(snapshot_id,)` |
| `session_states` | insert_only | `export_time` | `(session_id, export_time)` |
| `session_runtime_states` | upsert | `export_time` | `(session_id,)` |
| `session_config_records` | insert_only | `export_time` | `(session_id, config_md5)` |
| `session_runtime_events` | insert_only | `event_time` | `(id,)` |

- **upsert**：已存在的行按冲突列更新，新行直接插入。
- **insert_only**：已存在的行跳过，不更新。

## 增量机制

每张表维护一个 watermark（水印），记录上次同步到的时间戳。每次同步只拉取水印之后的新增/变更数据，写入成功后更新水印。支持断点续传——同步中断后重启，从上次水印继续。

重置水印（重新全量同步）：

```bash
jh-quant sync --from trade_paper.db --to postgresql://... --full-reset --yes-i-know
```

## CLI 选项

| 选项 | 说明 |
| --- | --- |
| `--from` | 本地 SQLite 文件路径 |
| `--to` | 远程 Postgres DSN（可选，默认读环境变量 `REMOTE_DB_URL`） |
| `--tables` | 指定同步的表，逗号分隔（默认全部） |
| `--dry-run` | 预览模式，不实际写入 |
| `--full-reset` | 重置所有水印，下次全量同步 |
| `--yes-i-know` | 配合 `--full-reset` 使用，跳过确认 |
| `--watch` | 守护模式，持续运行 |
| `--interval` | 守护模式下同步间隔（秒），默认 300 |

## 架构

```text
SQLiteSource ──→ PostgresTarget
     │                  │
     │    run_sync()     │
     │  (watermark +     │
     │   batch upsert)   │
     └────────┬──────────┘
          SyncState
        (JSON 水印文件)
```

- `SQLiteSource`：从本地 SQLite 读取行，支持水印过滤和批次迭代。
- `PostgresTarget`：写入远程 Postgres，支持 upsert 和 insert_only 两种模式。
- `SyncState`：JSON 格式水印文件，记录每张表的 `since` 时间戳。
