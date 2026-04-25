# jh_quant.signalgateway

信号网关服务模块，提供量化交易的信号生成、订单管理、持仓记录和绩效分析功能。

- **信号聚合**: 多种选股策略信号聚合，统一输出多空信号
- **订单管理**: OMS（Order Management System）模拟或实盘订单执行
- **持久化**: 支持 SQLite 和 PostgreSQL 存储交易记录和持仓状态
- **定时任务**: 支持 Cron 表达式调度，可定时执行交易循环
- **FastAPI + MCP 接口**: 提供 HTTP API 用于服务控制，并可通过 MCP 对接 agent

## 安装

```bash
pip install -e .
```

环境变量（`.env`）:
- `JIUHUANG_API_KEY` - API令牌
- `JIUHUANG_API_URL` - 数据API地址（默认: `http://127.0.0.1:8080`）

## 快速开始

### 基本使用

```python
from jh_quant.signalgateway import (
    SignalGatewayService,
    SignalGateway,
    StrategySpec,
)

# 定义策略规格
strategy_specs = [
    StrategySpec(name="FamaMacBethSelector", weight=1.0),
]

# 创建服务
service = SignalGatewayService(
    session_id="my_session",
    strategies=strategy_specs,
)

# 单次执行
result = service.run_once()
print(f"做多候选: {result.long_candidate_count}")
print(f"做空候选: {result.short_candidate_count}")
```

### 定时运行

```python
from jh_quant.signalgateway import SignalGatewayService, StrategySpec

service = SignalGatewayService(
    session_id="daily_trade",
    strategies=[StrategySpec(name="FamaMacBethSelector")],
    cron_expression="0 9 * * 1-5",  # 每周一到周五早上9点执行
)

# 启动服务（会持续运行）
service.start()
```

### FastAPI / MCP 服务

```python
from jh_quant.signalgateway.service_api import run_service_app

# 启动服务
run_service_app(service)
# 访问 http://localhost:8000/docs 查看 HTTP API 文档
# MCP endpoint 默认挂载在 http://localhost:8000/mcp
```

## 核心组件

### `SignalGatewayService`

主服务类，协调整个交易流程：

```python
from jh_quant.signalgateway import SignalGatewayService, StrategySpec

service = SignalGatewayService(
    session_id="my_session",      # 会话ID
    strategies=[                   # 策略规格列表
        StrategySpec(name="FamaMacBethSelector", weight=1.0),
        StrategySpec(name="MomentumSelector", weight=0.5),
    ],
    initial_cash=1000000,         # 初始资金
    cron_expression="0 9 * * 1-5", # Cron表达式（可选）
)
```

### `SignalGateway`

信号聚合器，汇总多个策略的信号：

```python
from jh_quant.signalgateway import SignalGateway

gateway = SignalGateway(
    strategies=strategy_list,
    selection_provider=selection_provider,
)

signals = gateway.aggregate_signals(date)
```

### `OMS` / `MockOMS`

订单管理系统：

```python
from jh_quant.signalgateway import MockOMS

oms = MockOMS(initial_cash=1000000)

# 执行交易
oms.execute_long(symbols=["000001", "600036"], date="2025-01-10")
oms.execute_short(symbols=["000002"], date="2025-01-10")

# 获取当前持仓
holds = oms.get_holds()
```

### `OrderRecorder`

订单记录器接口，支持多种实现：

```python
from jh_quant.signalgateway import SQLiteOrderRecorder, PostgresOrderRecorder

# SQLite 存储
recorder = SQLiteOrderRecorder(db_path="trades.db")

# PostgreSQL 存储
recorder = PostgresOrderRecorder(
    host="localhost",
    database="trades",
    user="user",
    password="pass",
)
```

### `MarketDataProvider`

市场数据提供者：

```python
from jh_quant.signalgateway import JHMarketData

provider = JHMarketData()
data = provider.get_data(symbol="000001", start="2025-01-01", end="2025-01-10")
```

## 配置选项

### `ServiceConfig`

服务配置：

```python
from jh_quant.signalgateway.config import ServiceConfig, Frequency

config = ServiceConfig(
    frequency=Frequency.DAILY,     # 执行频率
    initial_cash=1000000,          # 初始资金
    max_position=10,              # 最大持仓数量
    rebalance_threshold=0.1,       # 再平衡阈值
)
```

### `StrategySpec`

策略规格：

```python
from jh_quant.signalgateway import StrategySpec

spec = StrategySpec(
    name="FamaMacBethSelector",    # 策略名称
    weight=1.0,                   # 权重
    params={"lookback": 60},      # 策略参数
    alias="fm_selector",          # 别名
)
```

## 持久化协议

```python
from jh_quant.signalgateway import (
    PositionPersistence,      # 持仓持久化
    TradePersistence,         # 交易持久化
    SessionStatePersistence,  # 会话状态持久化
    ServiceStatePersistence,  # 服务状态持久化
    PerformancePersistence,   # 绩效持久化
)
```

## 绩效分析

```python
from jh_quant.signalgateway.performance import (
    calculate_holding_returns,
    calculate_turnover,
    get_performance_summary,
)

# 计算持仓收益
returns = calculate_holding_returns(holds, prices)

# 计算换手率
turnover = calculate_turnover(trades)

# 获取绩效汇总
summary = get_performance_summary(holds, trades)
```

## 目录结构

```
signalgateway/
├── __init__.py                 # 主入口，导出所有公共接口
├── config.py                   # 配置（ServiceConfig, Frequency, 策略注册表）
├── service.py                  # SignalGatewayService 主类
├── signalgateway.py            # SignalGateway 信号聚合器
├── oms.py                      # OMS 订单管理系统
├── market_data.py              # 市场数据提供者
├── order_recorder.py           # OrderRecorder 持久化接口
├── performance.py              # 绩效计算
├── persistence_coordinator.py  # 持久化协调器
├── persistence_protocols.py    # 持久化协议定义
├── models.py                   # 数据模型
├── position_sizer.py           # 仓位计算
├── strategy.py                 # 策略基类
├── utils.py                    # 工具函数
└── service_api.py              # FastAPI 接口
```
