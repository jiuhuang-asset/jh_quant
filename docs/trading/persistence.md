# 持久化

trading 服务通过 `PersistenceCoordinator` 统一管理订单、成交、持仓、绩效和运行状态持久化。

## SQLite

```python
from jh_quant.trading import PersistenceCoordinator, SQLiteOrderRecorder

persistence = PersistenceCoordinator(
    recorder=SQLiteOrderRecorder(db_path="trade_paper.db")
)
```

bootstrap 模板默认使用 SQLite：

```python
from jh_quant.trading.bootstrap import TradingBootstrapConfig, build_paper_manager

config = TradingBootstrapConfig(
    template="paper-basic",
    backend="tushare",
    db_path="trade_paper.db",
)

manager = build_paper_manager(config)
```

## PostgreSQL

如果需要集中式持久化，可以使用 `PostgresOrderRecorder`：

```python
from jh_quant.trading import PersistenceCoordinator, PostgresOrderRecorder

persistence = PersistenceCoordinator(
    recorder=PostgresOrderRecorder(
        conninfo="postgres://user:password@localhost:5432/trading"
    )
)
```

## 注意事项

- 不同 session 建议使用明确的 `session_id`，便于查询和恢复。
- SQLite 适合本地 demo 和轻量模拟盘；多人或长期实盘建议使用 PostgreSQL。
- 不要在同一个进程中手动删除正在使用的 SQLite 文件，先停止服务再清理。
