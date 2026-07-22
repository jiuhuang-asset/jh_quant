# jh_quant sync

`jh-quant sync` 将本地 SQLite 交易数据增量同步到远程 Postgres / Neon 数据库。

## 为什么需要 sync

Trading 模块（`jh-quant paper` / `jh-quant live`）运行时将交易记录、绩效快照、持仓、会话状态等写入本地 SQLite。sync 子命令负责将这些本地数据**非侵入式**地同步到远程数据库，支撑：

- 远程 Dashboard 展示
- 多实例数据聚合
- 历史数据分析与报表
- 数据备份与容灾

## 快速开始

### 环境要求

- 目标数据库：Postgres 15+（兼容 Neon Serverless）
- 本地仅需 SQLite 文件（由 `jh-quant paper` 或 `jh-quant live` 自动生成）

### 基本用法

```bash
# 单次全量同步（DSN 从环境变量取）
REMOTE_DB_URL=postgresql://user:pass@host/db jh-quant sync --from trade_paper.db

# 显式指定目标 DSN
jh-quant sync --from trade_paper.db --to postgresql://user:pass@host/db

# 预览模式（只读不写，确认数据量）
jh-quant sync --from trade_paper.db --dry-run
```

### 获取免费远程数据库（Neon）

推荐使用 [Neon](https://neon.tech) 的免费套餐，只需邮箱即可注册，无需信用卡：

1. 打开 [neon.tech](https://neon.tech)，点击 **Sign Up**，使用 GitHub / Google 账号或邮箱注册
2. 创建项目后，进入 **Dashboard** → **Connection Details**
3. 复制连接字符串（格式为 `postgresql://user:pass@host/db`）
4. 设置为环境变量：

```bash
# 设置环境变量（推荐写入 ~/.bashrc 或 ~/.zshrc 持久化）
export REMOTE_DB_URL="postgresql://user:pass@host/db"

# 之后直接运行即可
jh-quant sync --from trade_paper.db
```

> Neon 免费套餐包含 0.5 GB 存储和约 1 亿行请求/月，对个人量化交易场景绰绰有余。

### 手机随时随地查看

数据同步到远程数据库后，可以使用 [jh_quant_rn_app](https://github.com/jiuhuang-asset/jh_quant_rn_app) 在手机上随时随地查看投资表现：

1. 克隆并运行手机 App：

   ```bash
   git clone https://github.com/jiuhuang-asset/jh_quant_rn_app.git
   cd jh_quant_rn_app
   npm install
   npx expo start
   ```

2. 在 App 中填写 `REMOTE_DB_URL`（与 sync 使用同一个 Neon 连接字符串）
3. 即可在手机上实时查看交易记录、持仓、绩效曲线等完整 Dashboard

```text
本地 jh-quant paper/live
        │
        │  sqlite
        ▼
   jh-quant sync ──────▶ Neon/Postgres ◀──── jh_quant_rn_app
                         (远程数据库)          (手机 App)
```


### 守护模式

```bash
# 每 5 分钟自动同步一次，Ctrl-C 退出
jh-quant sync --from trade_paper.db --watch

# 自定义间隔（秒）
jh-quant sync --from trade_paper.db --watch --interval 600
```

## 环境变量

| 变量 | 说明 | 优先级 |
|------|------|--------|
| `REMOTE_DB_URL` | 远程 Postgres DSN | 最高 |
| `TRADING_REMOTE_DSN` | 备选 DSN | 次之 |
| `TRADING_SYNC_STATE_PATH` | watermark 状态文件路径 | — |
| `JH_SYNC_LOG_LEVEL` | 日志级别（DEBUG/INFO/WARNING/ERROR），默认 INFO | — |

目标 DSN 优先级：`REMOTE_DB_URL` > `TRADING_REMOTE_DSN` > `--to` 参数值。

## CLI 选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--from` | str | 必填 | 本地 SQLite 数据库文件路径 |
| `--to` | str | 环境变量 | 远程 Postgres DSN |
| `--tables` | str | 全部 | 指定同步的表，逗号分隔。可选: `trades, daily_performances, positions_snapshot, session_states, session_runtime_states, session_config_records, session_runtime_events` |
| `--since` | str | — | ISO 时间戳，覆盖对应表的 watermark 上界（强制从指定时间点拉取） |
| `--dry-run` | flag | — | 预览模式，只读取源数据并计数，不连接远端、不写入 |
| `--full-reset` | flag | — | 先 TRUNCATE 远程表再全量同步。必须同时加 `--yes-i-know` |
| `--yes-i-know` | flag | — | `--full-reset` 的二次确认开关 |
| `--chunk-size` | int | 500 | 单批写入行数，控制内存与网络开销 |
| `--state-path` | str | `~/.jiuhuang/sync_state.json` | watermark 状态文件路径 |
| `--watch` | flag | — | 守护模式：循环执行 sync，Ctrl-C 退出 |
| `--interval` | int | 300 | 守护模式下的同步间隔（秒） |
| `--log-level` | str | INFO | 日志级别 |

## 同步的表

sync 覆盖 7 张核心表：

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

- **upsert**：以冲突列为唯一键，已存在的行按最新值更新，新行直接插入。适用于状态会变化的表（如交易记录可能被修正、会话运行时状态持续更新）。
- **insert_only**：以冲突列为唯一键，已存在的行跳过不更新。适用于只追加的事件日志和配置快照（等幂、不可变）。

## 增量机制（Watermark）

sync 使用**水印（watermark）**实现增量同步，避免每次全量拉取：

```text
第一次同步：拉取所有行 → watermark = max(watermark_field)
第二次同步：拉取 watermark 之后的新增/变更行 → 推进 watermark
...
```

水印以 JSON 格式持久化到 `~/.jiuhuang/sync_state.json`（可通过 `--state-path` 自定义），包含：

- 每张表最近一次成功同步的 `since` 时间戳
- 源数据库指纹（文件大小 + mtime），用于检测源库是否被替换

**断点续传**：每张表成功后立即落盘水印文件。如果 7 张表中的第 4 张失败，前 3 张的水印已保存，重启后从第 4 张继续。

### 重置水印

```bash
# 清空远端 7 张表，从头全量同步
jh-quant sync --from trade_paper.db --full-reset --yes-i-know
```

`--full-reset` 会先 TRUNCATE 远程所有表，然后全量重新灌入。水印文件也会被重置。

## 架构

```text
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

- **`run_sync()`**：主循环，按 `resolve_specs()` 确定的表顺序依次同步，每表异常隔离（一张表失败不阻塞其他表）。
- **`SQLiteSource`**：从本地 SQLite 流式读取行，支持水印过滤和批次迭代。
- **`PostgresTarget`**：写入远程 Postgres，自动建表，支持 upsert 和 insert_only 两种模式。
- **`SyncState`**：JSON 格式水印文件，记录每张表的 `since` 时间戳和源库指纹。

## 输出示例

```text
18:23:45 [INFO] [trades] mode=upsert watermark=None
18:23:46 [INFO] [trades] 完成 read=1250 written=1250 new_watermark=2026-07-22 14:30:05+00:00
18:23:46 [INFO] [daily_performances] mode=upsert watermark=2026-07-20 14:30:00+00:00
18:23:46 [INFO] [daily_performances] 完成 read=3 written=3 new_watermark=2026-07-22 14:30:00+00:00
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

## 编程调用

除了 CLI，也可以直接在代码中调用 sync：

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
