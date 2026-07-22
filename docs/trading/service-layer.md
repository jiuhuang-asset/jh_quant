# 服务层

`SessionService` 管理一个交易 session，`MultiSessionService` 管理多个 session，并通过 `trading.service.api` 暴露 REST API。API 可用于查看运行状态、配置、持仓、绩效、交易记录，也可触发手动操作。

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
    default_symbols=["688041", "688256"],
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

## 端口与访问地址

`run_trading_app()` 由 `jh_quant.trading.service.api` 提供：

```python
run_trading_app(
    session=None,
    host="127.0.0.1",
    port=8000,
    manager=None,
)
```

默认监听：

```text
http://127.0.0.1:8000
```

常用访问地址：

| 地址 | 说明 |
| --- | --- |
| `http://127.0.0.1:8000/docs` | Swagger / OpenAPI 交互文档 |
| `http://127.0.0.1:8000/openapi.json` | OpenAPI JSON |
| `http://127.0.0.1:8000/health` | 健康检查 |

如果 8000 端口已被占用，可以指定其他端口：

```bash
jh-quant paper --port 8010
```

## Dashboard 与 API 端口

bootstrap 默认会先启动 API，再自动调用：

```python
from jh_quant.dashboard import display_trading

display_trading(host=host, port=port)
```

因此 Dashboard 会连接同一个 `host:port`。如果你修改 API 端口，Dashboard 也必须使用同一端口。

## 手动启动 API + Dashboard

```python
import threading
import time

from jh_quant.dashboard import display_trading
from jh_quant.trading import run_trading_app

api_thread = threading.Thread(
    target=run_trading_app,
    kwargs={"manager": manager, "host": "127.0.0.1", "port": 8000},
    daemon=True,
)
api_thread.start()
time.sleep(1.5)

display_trading(host="127.0.0.1", port=8000)
```
