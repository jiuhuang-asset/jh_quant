# 服务层

`SessionService` 管理一个交易 session，`MultiSessionService` 管理多个 session，并通过 REST API 暴露运行状态、配置、持仓、绩效和手动操作接口。

## 最小示例

```python
from jh_quant.trading import (
    MultiSessionService,
    PersistenceCoordinator,
    SQLiteOrderRecorder,
    create_market_data_service,
    run_trading_app,
)

market_data = create_market_data_service(
    backend="tushare",
    default_symbols=["600519", "000001"],
)

manager = MultiSessionService(
    max_sessions=4,
    persistence=PersistenceCoordinator(
        recorder=SQLiteOrderRecorder(db_path="trade_service.db")
    ),
    market_data_provider=market_data,
)

run_trading_app(manager=manager, host="127.0.0.1", port=8000)
```

## MarketDataService

服务层只注入统一 `MarketDataService`，不直接依赖 akshare 或 tushare 字段。内置 backend：

- `tushare`：默认，TuShare 历史行情 + AkShare 当天实时合并。
- `akshare`：AkShare 历史行情 + AkShare 实时行情。
- `xquant`：TuShare 历史行情 + xtquant 实时行情。

## Session 创建

推荐通过 bootstrap 创建：

```python
from jh_quant.trading.bootstrap import TradingBootstrapConfig, build_paper_manager

config = TradingBootstrapConfig(
    template="paper-basic",
    backend="tushare",
    symbols=["600519", "000001"],
)

manager = build_paper_manager(config)
```

专业用户可以直接构造 `SessionServiceConfig` 后调用：

```python
manager.create_session(config=session_config, initial_capital=100_000)
```

## API 文档

服务启动后访问：

```text
http://127.0.0.1:8000/docs
```
