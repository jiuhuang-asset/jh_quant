# `jh_quant.signalgateway`

`jh_quant.signalgateway` 是一个面向服务的交易网关层，负责把：

- 选股器 `selection provider`
- 一个或多个交易策略 `strategy`
- `OMS`
- 持久化
- 调度与 FastAPI 服务

组织成一套可以直接运行、观察和动态调整的交易服务。

## 适用场景

它比较适合下面这几类用法：

- 本地做模拟盘和手工 smoke test
- 给前端控制台或 agent 暴露 HTTP / MCP 接口
- 在“选股 + 多策略 + 调仓”之间做统一编排
- 让内置组件和用户自定义组件都走同一套注册与配置机制

## 核心模块

```text
jh_quant/signalgateway/
  config/
    service.py      # 服务配置、builder
    selection.py    # 选股器注册、参数模型、schema
    strategy.py     # 策略注册、参数模型、schema
    portfolio.py    # 组合优化与调仓配置
  market_data.py    # 行情数据适配层
  oms.py            # 订单管理系统接口与 mock 实现
  persistence/      # 交易、状态、绩效持久化
  service/          # SignalGatewayService 与 FastAPI API
  signalgateway.py  # 网关本体，负责执行策略周期
```

## 配置对象分层

SignalGateway 的配置大致分三层：

### `ServiceConfig`

控制服务如何运行，例如：

- `session_id`
- `mode`
- `interval_seconds`
- `cron_expression`
- `restore_persisted_state`

### `SelectionSpec`

描述“使用哪个选股器”和“它的用户可配置参数”。

```python
from jh_quant.signalgateway import SelectionSpec

spec = SelectionSpec(
    name="factor_selector",
    alias="factor_v1",
    params={
        "factor": "ch3",
        "start": "2020-01-01",
        "top_n": 50,
    },
)
```

### `StrategySpec`

描述“启用哪个策略”“权重是多少”“策略参数是什么”。

```python
from jh_quant.signalgateway import StrategySpec

spec = StrategySpec(
    name="moving_average_crossover",
    alias="sma",
    weight=1.0,
    params={
        "short_window": 12,
        "long_window": 24,
    },
)
```

## Builder 用法

推荐使用 `SignalGatewayServiceConfigBuilder` 组织配置。

### 基础示例

```python
from jh_quant.signalgateway import (
    FactorSelectionConfig,
    JHMarketDataProvider,
    MockOMS,
    MovingAverageCrossoverStrategyConfig,
    PersistenceCoordinator,
    SignalGateway,
    SignalGatewayService,
    SignalGatewayServiceConfigBuilder,
    SQLiteOrderRecorder,
    TurtleStrategyConfig,
)

session_id = "demo"

gateway = SignalGateway(
    oms=MockOMS(session_id=session_id, initial_capital=100000),
    market_data_provider=JHMarketDataProvider(),
)

persistence = PersistenceCoordinator(
    recorder=SQLiteOrderRecorder(db_path="mocktrade.db")
)

config = (
    SignalGatewayServiceConfigBuilder.defaults()
    .with_service(
        session_id=session_id,
        mode="paper",
        interval_seconds=300,
        cron_expression="0 9 * * 1-5",
        restore_persisted_state=False,
    )
    .with_selection(
        name="factor_selector",
        params=FactorSelectionConfig(
            factor="ch3",
            start="2020-01-01",
            top_n=50,
        ),
    )
    .add_strategy(
        name="turtle",
        alias="turtle",
        weight=1.0,
        params=TurtleStrategyConfig(entry_window=20, exit_window=10),
    )
    .add_strategy(
        name="moving_average_crossover",
        alias="sma",
        weight=1.0,
        params=MovingAverageCrossoverStrategyConfig(
            short_window=12,
            long_window=24,
        ),
    )
    .build()
)

service = SignalGatewayService(
    gateway=gateway,
    config=config,
    persistence=persistence,
)

result = service.run_once()
print(result)
```

### `params` 现在支持什么

`with_selection(..., params=...)` 和 `add_strategy(..., params=...)` 现在都支持：

- `dict`
- `dataclass` 实例
- `Pydantic BaseModel` 实例
- `None`

这让你可以保留动态扩展能力，同时在常用组件上获得更好的类型提示和文档可见性。

## 内置参数模型

### 选股器

当前内置：

- `FactorSelectionConfig`

### 策略

当前内置了一组策略参数 dataclass，可直接导入使用：

- `TurtleStrategyConfig`
- `MovingAverageCrossoverStrategyConfig`
- `BuyAndHoldStrategyConfig`
- `VolumeTrendStrategyConfig`
- `VolumeDivergenceStrategyConfig`
- `MeanReversionStrategyConfig`
- `RSIStrategyConfig`
- `BollingerBandsStrategyConfig`
- `MomentumStrategyConfig`
- `BreakoutStrategyConfig`
- `DualThrustStrategyConfig`

这些类的作用有两个：

- 写代码时给 IDE 提供字段补全
- 运行时生成更明确的 schema

## 注册自定义选股器

如果你希望注入自定义选股器，推荐同时注册：

- 实现类
- 参数模型
- 运行时依赖说明

### 示例

```python
from dataclasses import dataclass

from jh_quant.signalgateway import register_selection_provider


@dataclass
class DemoSelectionConfig:
    symbols: list[str]
    top_n: int = 10


class DemoSelectionProvider:
    def __init__(self, config: DemoSelectionConfig):
        self._config = config

    def select(self, as_of_date: str):
        ...

    @property
    def config(self):
        return {
            "symbols": self._config.symbols,
            "top_n": self._config.top_n,
        }


register_selection_provider(
    "demo_selector",
    DemoSelectionProvider,
    config_model=DemoSelectionConfig,
    runtime_dependencies=(),
)
```

注册后你就可以这样使用：

```python
builder.with_selection(
    name="demo_selector",
    params=DemoSelectionConfig(symbols=["000001.SZ", "600000.SH"]),
)
```

## 注册自定义策略

策略侧也推荐走“实现类 + 参数模型”一起注册。

### 示例

```python
from dataclasses import dataclass

from jh_quant.backtest.strategy import Strategy
from jh_quant.signalgateway import register_strategy


@dataclass
class DemoStrategyConfig:
    fast_window: int = 10
    slow_window: int = 30


class DemoStrategy(Strategy):
    def __init__(self, fast_window: int = 10, slow_window: int = 30):
        ...


register_strategy(
    "demo_strategy",
    DemoStrategy,
    config_model=DemoStrategyConfig,
)
```

之后可以直接传配置对象：

```python
builder.add_strategy(
    name="demo_strategy",
    alias="demo",
    weight=1.0,
    params=DemoStrategyConfig(fast_window=8, slow_window=21),
)
```

## 为什么推荐“注册参数模型”

如果只注册实现类，系统仍然可以通过反射 `__init__` 签名来做基础校验和 schema 生成，但它有几个局限：

- IDE 无法像普通配置类一样提供稳定补全
- 字段说明不容易集中维护
- 对外文档只能依赖运行时推导

而注册参数模型后：

- 写配置时可以直接看到字段名
- 类和字段可以挂中文 docstring / `Field(description=...)`
- `list_selection_definitions()` / `list_strategy_definitions()` 返回的 schema 更稳定
- 自定义扩展和内置组件可以走完全相同的机制

## 自描述能力

SignalGateway 提供了一组“读目录 / 读 schema”的能力，适合前端、agent 和动态配置界面使用。

### 选股器

```python
from jh_quant.signalgateway import (
    get_selection_config_model,
    get_selection_params_schema,
    list_selection_definitions,
)

print(get_selection_config_model("factor_selector"))
print(get_selection_params_schema("factor_selector"))
print(list_selection_definitions())
```

### 策略

```python
from jh_quant.signalgateway import (
    get_strategy_config_model,
    get_strategy_params_schema,
    list_strategy_definitions,
)

print(get_strategy_config_model("moving_average_crossover"))
print(get_strategy_params_schema("moving_average_crossover"))
print(list_strategy_definitions())
```

`list_*_definitions()` 的返回结果里会包含：

- `name`
- `params_schema`
- `config_model`
- `runtime_dependencies`（选股器侧）

## `SignalGatewayService`

`SignalGatewayService` 负责把配置变成真正运行中的服务实例，核心职责包括：

- 初始化选股器
- 初始化策略实例
- 恢复持久化状态
- 执行一次交易周期 `run_once`
- 启停调度线程
- 暴露运行时查询与配置更新接口

## 状态恢复注意事项

默认情况下，`ServiceConfig.restore_persisted_state=True`。

这意味着服务启动时会优先尝试从持久化层恢复最近一次保存的状态，其中包括：

- service config
- selection spec
- strategy specs
- portfolio spec

所以如果你本地做 smoke runner 或调试脚本，通常建议显式设置：

```python
.with_service(
    restore_persisted_state=False,
)
```

这样当前脚本配置就不会被数据库中的旧状态覆盖。

## FastAPI 服务

### 启动方式

```python
from jh_quant.signalgateway import run_service_app

run_service_app(service, host="127.0.0.1", port=8000)
```

如果安装了 `fastapi-mcp`，MCP 路由会自动挂载；否则普通 HTTP API 仍然可以正常工作。

### 常见接口

- `GET /health`
- `GET /service/status`
- `GET /service/runtime`
- `GET /service/performance`
- `GET /service/analytics`
- `GET /service/config`
- `GET /service/selection-config`
- `GET /service/strategy-config`
- `POST /service/start`
- `POST /service/stop`
- `POST /service/run-once`
- `POST /service/selection-config`
- `POST /service/strategy-config`
- `POST /service/scheduler-config`
- `POST /service/close-all-positions`
- `POST /service/signal-buy`
- `POST /service/signal-sell`

## 动态配置接口示例

### 读取策略目录

`GET /service/strategy-config`

返回结果会包含：

- 当前 `strategy_specs`
- `available_strategies`
- 每个策略的 `params_schema`
- 如果可用，还会包含 `config_model`

### 更新策略配置

`POST /service/strategy-config`

```json
{
  "strategy_specs": [
    {
      "name": "turtle",
      "alias": "turtle_fast",
      "weight": 1.0,
      "params": {
        "entry_window": 10,
        "exit_window": 5
      }
    },
    {
      "name": "moving_average_crossover",
      "alias": "sma",
      "weight": 1.0,
      "params": {
        "short_window": 5,
        "long_window": 20
      }
    }
  ]
}
```

### 读取选股器目录

`GET /service/selection-config`

返回结果会包含：

- 当前 `selection_spec`
- `active_selection_config`
- `available_selections`
- 每个选股器的 `params_schema`
- 如果可用，还会包含 `config_model`

### 更新选股器配置

`POST /service/selection-config`

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "factor_v2",
    "params": {
      "factor": "ch3",
      "start": "2021-01-01",
      "period": "M",
      "top_n": 50
    }
  }
}
```

## 持久化

常见持久化导出：

```python
from jh_quant.signalgateway import (
    PerformancePersistence,
    PersistenceCoordinator,
    PositionPersistence,
    PostgresOrderRecorder,
    ServiceStatePersistence,
    SessionStatePersistence,
    SQLiteOrderRecorder,
    TradePersistence,
)
```

持久化主要负责：

- 交易记录
- 持仓快照
- 日度绩效
- session 状态
- service 状态

## 推荐实践

- 本地脚本调试时，优先设置 `restore_persisted_state=False`
- 常用组件尽量传参数模型对象，不只传裸 `dict`
- 自定义扩展时，注册实现类的同时注册 `config_model`
- UI / agent 侧优先使用 `list_*_definitions()` 和 `params_schema` 构建动态表单
- 需要最大灵活性时，仍然可以退回到 `name + params dict` 的模式

## 相关文件

- [run_signalgateway.py](/e:/个人/jiuhuang-asset/jh_quant/run_signalgateway.py:1)
- [config/service.py](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/config/service.py:1)
- [config/selection.py](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/config/selection.py:1)
- [config/strategy.py](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/config/strategy.py:1)
- [service/core.py](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/core.py:1)
