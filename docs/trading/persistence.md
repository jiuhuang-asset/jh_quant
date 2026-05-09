# 数据持久化

`jh_quant.trading` 提供了完整的交易数据持久化方案，支持 SQLite 和 PostgreSQL，采用 Tortoise ORM 作为异步数据库驱动。

## 架构

```
PersistenceCoordinator  ←── 业务层门面，实现所有持久化协议
        │
   OrderRecorder (ABC)  ←── 抽象记录器，定义 18 个抽象方法
        │
  ┌─────┴──────┐
  │            │
SQLiteOrder   PostgresOrder
Recorder      Recorder (含 MemFireCloudRecorder)
```

无 Tortoise ORM 时，`PersistenceCoordinator` 自动退化为空操作，不影响核心功能运行。

---

## 快速上手

### SQLite（本地文件）

```python
from jh_quant.trading import PersistenceCoordinator, SQLiteOrderRecorder

recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
persistence = PersistenceCoordinator(recorder=recorder)

# 传递给 MultiSessionService
manager = MultiSessionService(
    persistence=persistence,
    market_data_provider=md_provider,
)
```

### PostgreSQL

```python
from jh_quant.trading import PersistenceCoordinator, PostgresOrderRecorder

recorder = PostgresOrderRecorder(
    conninfo="postgres://user:password@localhost:5432/jh_quant"
)
persistence = PersistenceCoordinator(recorder=recorder)
```

### MemFireCloud（国产云数据库）

```python
from jh_quant.trading import PersistenceCoordinator, MemFireCloudRecorder

recorder = MemFireCloudRecorder(
    conninfo="postgres://...@memfirecloud.com:5432/db"
)
persistence = PersistenceCoordinator(recorder=recorder)
```

---

## 持久化数据

系统自动记录以下数据：

### 交易记录 (trades)

每笔买卖订单执行后自动记录。

| 字段 | 说明 |
|------|------|
| `trade_id` | 交易唯一标识 |
| `session_id` | 所属会话 |
| `trade_date` | 成交日期 |
| `symbol` | 标的代码 |
| `trade_type` | `buy` / `sell` |
| `price` | 成交价 |
| `quantity` | 成交数量 |
| `amount` | 成交金额 |
| `commission` | 佣金 |
| `slippage` | 滑点成本 |
| `total_cost` | 总成本 |
| `signal_reason` | 信号原因 |

### 每日绩效 (daily_performances)

每个交易日结束后自动计算并记录。

| 字段 | 说明 |
|------|------|
| `performance_id` | 绩效记录唯一标识 |
| `session_id` | 所属会话 |
| `trade_date` | 交易日 |
| `portfolio_value` | 组合总价值 |
| `cash_balance` | 现金余额 |
| `position_value` | 持仓市值 |
| `daily_return` | 日收益率 |
| `cumulative_return` | 累计收益率 |
| `daily_pnl` | 日盈亏 |
| `num_positions` | 持仓数量 |

### 持仓快照 (positions_snapshot)

每周期自动记录每个持仓的明细。

| 字段 | 说明 |
|------|------|
| `snapshot_id` | 快照唯一标识 |
| `session_id` | 所属会话 |
| `trade_date` | 快照日期 |
| `symbol` | 标的代码 |
| `quantity` | 持仓数量 |
| `avg_cost` | 持仓均价 |
| `current_price` | 当前市价 |
| `market_value` | 市值 |
| `pnl` | 浮动盈亏 |
| `pnl_pct` | 浮动盈亏百分比 |

### 状态与配置

- **session_states**：会话运行状态（支持断点恢复）
- **session_runtime_states**：运行时状态
- **session_config_records**：配置变更历史（按 MD5 去重）
- **session_runtime_events**：运行时事件日志

---

## 状态导出与恢复

### OMS 状态导出

```python
oms = MockOMS(initial_capital=100_000)
# ... 运行一段时间后

state = oms.export_state()
# 返回 JSON 可序列化的 Dict，包含：
# - holdings: 持仓列表
# - cash_balance: 资金余额
# - total_profit: 累计盈亏
# - current_date: 当前模拟日期
```

### OMS 状态恢复

```python
# 从持久化中加载状态
saved_state = persistence.load_latest_session_state(session_id="my-session")

# 恢复 OMS
oms = MockOMS(restore_from=saved_state)
# 或
oms = MockOMS(initial_capital=100_000)
oms.import_state(saved_state)
```

---

## 会话断点恢复

启用 `restore_persisted_state=True`（默认），会话启动时会自动从持久化中恢复上次的状态：

```python
config = (
    SessionServiceConfigBuilder.defaults()
    .with_session(
        session_id="my-session",
        restore_persisted_state=True,  # 默认开启
        # ...
    )
    .build()
)
```

---

## 绩效分析

持久化数据可通过 `performance` 模块直接分析：

```python
from jh_quant.trading.performance import (
    calculate_equity_curve,
    calculate_holding_returns,
    calculate_turnover,
    get_performance_summary,
    build_performance_report,
)

# persistence 实现了 PerformanceDataSource 协议
summary = get_performance_summary(persistence, session_id="my-session")

# 完整报告（含 7 个子模块）
report = build_performance_report(persistence, session_id="my-session")
# report 包含：
# - session_info
# - equity_curve（含最大回撤）
# - holding_returns
# - turnover
# - trade_activity
# - position_exposure
# - latest_portfolio
```

---

## 数据管理

### 查询交易历史

```python
# 返回 DataFrame
trades_df = persistence.query_trades(session_id="my-session")
print(trades_df.head())
```

### 查询每日绩效

```python
daily_df = persistence.query_daily_performance(session_id="my-session")
print(daily_df[["trade_date", "portfolio_value", "daily_return"]].tail())
```

### 查询持仓快照

```python
snaps_df = persistence.query_position_snapshots(session_id="my-session")
print(snaps_df.head())
```

### 查询配置历史

```python
configs = persistence.query_session_configs(session_id="my-session")
print(f"共 {len(configs)} 条配置变更记录")
```

### 关闭连接

```python
persistence.close()
# 或在 MultiSessionService.shutdown() 时自动关闭
```
