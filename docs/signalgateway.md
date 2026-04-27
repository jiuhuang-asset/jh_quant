# jh_quant.signalgateway

`jh_quant.signalgateway` provides a service-oriented trading gateway with:

- signal aggregation from multiple strategies
- pluggable selection providers
- OMS-driven execution
- persistence for trades, snapshots, and service state
- FastAPI endpoints for runtime inspection and configuration

## Install

```bash
pip install -e .
```

Common environment variables:

- `JIUHUANG_API_KEY`
- `JIUHUANG_API_URL`

## Package Layout

```text
signalgateway/
  __init__.py
  config.py
  market_data.py
  models/
  oms.py
  persistence/
    coordinator.py
    models.py
    protocols.py
    recorder.py
  service/
    __init__.py
    api.py
    core.py
    schemas.py
  signalgateway.py
  performance.py
  position_sizer.py
  utils.py
```

## Core Concepts

### `StrategySpec`

`StrategySpec` describes a strategy by registry name plus user-editable params.

```python
from jh_quant.signalgateway import StrategySpec

spec = StrategySpec(
    name="moving_average_crossover",
    alias="sma",
    weight=1.0,
    params={
        "short_window": 5,
        "long_window": 20,
    },
)
```

### `SelectionSpec`

`SelectionSpec` does the same thing for selection providers.

```python
from jh_quant.signalgateway import SelectionSpec

spec = SelectionSpec(
    name="factor_selector",
    alias="factor_v1",
    params={
        "factor": "CH3",
        "start": "2020-01-01",
        "period": "M",
        "top_n": 100,
    },
)
```

Important: `params` should contain only user-editable config. Runtime dependencies such as `jh_data` are injected by the service when needed.

### `SignalGatewayService`

`SignalGatewayService` coordinates:

- a `SignalGateway`
- one `selection_spec` or a direct `selection_provider`
- a list of `strategy_specs`
- persistence and scheduler state

## Basic Usage

```python
from jh_quant.signalgateway import (
    JHMarketDataProvider,
    MockOMS,
    PersistenceCoordinator,
    SelectionSpec,
    ServiceConfig,
    SignalGateway,
    SignalGatewayService,
    StrategySpec,
)

gateway = SignalGateway(
    oms=MockOMS(session_id="demo", initial_capital=100000),
    market_data_provider=JHMarketDataProvider(),
)

service = SignalGatewayService(
    gateway=gateway,
    config=ServiceConfig(
        session_id="demo",
        mode="paper",
        interval_seconds=300,
        cron_expression="0 9 * * 1-5",
    ),
    selection_spec=SelectionSpec(
        name="factor_selector",
        params={
            "factor": "CH3",
            "start": "2020-01-01",
            "period": "M",
        },
    ),
    strategy_specs=[
        StrategySpec(name="turtle"),
        StrategySpec(
            name="moving_average_crossover",
            alias="sma",
            params={"short_window": 5, "long_window": 20},
        ),
    ],
    persistence=PersistenceCoordinator(),
)

result = service.run_once()
print(result.selection_count)
```

## Smoke Runner

The repository includes [test_signalgateway.py](/E:/个人/jiuhuang-asset/jh_quant/test_signalgateway.py:1) as a lightweight manual smoke runner.

It demonstrates:

- service construction from `selection_spec`
- strategy construction from `strategy_specs`
- a custom registered selection provider
- a self-contained demo market data provider

## FastAPI Service

```python
from jh_quant.signalgateway import run_service_app

run_service_app(service, host="127.0.0.1", port=8000)
```

If `fastapi-mcp` is installed, MCP routes are mounted automatically. If not, the HTTP API still works normally.

## Dynamic Runtime Configuration

The recommended flow for UI / agent / API clients is:

1. Read the available strategy or selection catalog.
2. Inspect each component's `params_schema`.
3. Submit a validated `StrategySpec` list or `SelectionSpec`.

This avoids guessing which keys are supported in `params`.

### Read Current Strategy Config

`GET /service/strategy-config`

Example response shape:

```json
{
  "strategy_specs": [
    {
      "name": "moving_average_crossover",
      "weight": 1.0,
      "params": {
        "short_window": 5,
        "long_window": 20
      },
      "alias": "sma"
    }
  ],
  "available_strategies": [
    {
      "name": "moving_average_crossover",
      "params_schema": {
        "type": "object",
        "properties": {
          "short_window": {"type": "integer", "default": 50},
          "long_window": {"type": "integer", "default": 200}
        }
      },
      "runtime_dependencies": []
    }
  ]
}
```

### Update Strategy Config

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

### Read Current Selection Config

`GET /service/selection-config`

Example response shape:

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "params": {
      "factor": "CH3",
      "start": "2020-01-01",
      "period": "M"
    },
    "alias": "factor_v1"
  },
  "active_selection_config": {
    "factor": "CH3",
    "start": "2020-01-01",
    "period": "M"
  },
  "available_selections": [
    {
      "name": "factor_selector",
      "params_schema": {
        "type": "object",
        "properties": {
          "factor": {"type": "string"},
          "start": {"type": "string"},
          "period": {"type": "string", "default": "M"}
        },
        "required": ["factor", "start"]
      },
      "runtime_dependencies": ["jh_data"]
    }
  ]
}
```

### Update Selection Config

`POST /service/selection-config`

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "factor_v2",
    "params": {
      "factor": "CH3",
      "start": "2021-01-01",
      "period": "M",
      "top_n": 50
    }
  }
}
```

## Other Service Endpoints

- `GET /health`
- `GET /service/status`
- `GET /service/runtime`
- `GET /service/performance`
- `GET /service/analytics`
- `GET /service/config`
- `POST /service/start`
- `POST /service/stop`
- `POST /service/run-once`
- `POST /service/scheduler-config`
- `POST /service/close-all-positions`
- `POST /service/signal-buy`
- `POST /service/signal-sell`

## Persistence

Persistence lives under `signalgateway/persistence/`.

Common exports:

```python
from jh_quant.signalgateway import (
    PersistenceCoordinator,
    SQLiteOrderRecorder,
    PostgresOrderRecorder,
    TradePersistence,
    PositionPersistence,
    SessionStatePersistence,
    ServiceStatePersistence,
    PerformancePersistence,
)
```

ORM record models now live in:

- [jh_quant/signalgateway/persistence/models.py](/E:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/persistence/models.py:1)

## Notes

- `StrategySpec.params` and `SelectionSpec.params` are validated against registered implementations.
- Unknown params are rejected.
- Basic type coercion is supported by Pydantic during config validation.
- `factor_selector` requires a market data provider carrying `jhd`; the API caller does not need to pass that dependency manually.
