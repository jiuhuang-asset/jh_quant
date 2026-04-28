# SignalGateway Service API 文档 v1

本文档版本：`v1`

本文档面向前端开发人员，描述 `jh_quant.signalgateway.service.api` 当前暴露的 HTTP API、关键数据模型，以及推荐的前端对接方式。

## 1. 基本信息

- 默认服务地址：`http://127.0.0.1:8000`
- 协议：`HTTP + JSON`
- CORS：已开启，允许任意来源 `*`
- 时间字段：默认使用 ISO 8601 字符串
- 当前代码入口：[api.py](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/api.py:1)
- 主要响应模型定义：[schemas.py](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/schemas.py:1)

## 2. 前端最重要的对接原则

### 2.1 配置不是写死表单，而是“后端 schema 驱动”

前端不要把 `selection / strategy / portfolio` 的参数写死在页面里。推荐流程：

1. 先调用：
   - `GET /service/selection-config`
   - `GET /service/strategy-config`
   - `GET /service/portfolio/config`
2. 从返回中的以下字段读取可配置定义：
   - `available_selections[].params_schema`
   - `available_strategies[].params_schema`
   - `available_optimizers[].params_schema`
3. 根据 `params_schema` 动态渲染表单。

这也是设置页实现关注点分离的基础。

### 2.2 配置优先级

服务当前已经支持“启动配置”和“用户持久化配置”并存。

推荐前端理解为：

1. `bootstrap config`
   启动 `SignalGateway` 时传入的初始配置。
2. `persisted user config`
   用户在运行中通过 API 修改后，持久化到数据库的配置。
3. 当前运行配置
   实际生效配置。

通过 `GET /service/config` 可以看到：

- `config_source`
- `persisted_user_config_available`
- `persisted_user_config_updated_at`

通常应以接口返回的当前运行配置为准，而不是以页面本地默认值为准。

### 2.3 建议的首屏加载顺序

推荐前端初始化时并行请求：

1. `GET /health`
2. `GET /service/status`
3. `GET /service/runtime`
4. `GET /service/performance`
5. `GET /service/config`
6. `GET /service/selection-config`
7. `GET /service/strategy-config`
8. `GET /service/portfolio/config`

如果想减少请求次数，也可以直接优先使用：

- `GET /service/analytics`

它会返回：

- `status`
- `runtime`
- `performance`
- `config`

但它不包含 `available_selections / available_strategies / available_optimizers`，所以配置页仍然需要额外请求 6/7/8。

## 3. 接口总览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/service/status` | 服务状态 |
| `GET` | `/service/runtime` | 运行时快照 |
| `GET` | `/service/performance` | 绩效快照 |
| `GET` | `/service/analytics` | 聚合分析快照 |
| `GET` | `/service/config` | 当前完整配置快照 |
| `PUT` | `/service/config` | 整体替换完整配置 |
| `GET` | `/service/events` | 服务事件历史 |
| `POST` | `/service/start` | 启动调度 |
| `POST` | `/service/stop` | 停止调度 |
| `POST` | `/service/run-once` | 立即执行一轮 |
| `GET` | `/service/strategy-config` | 获取策略配置与可选策略 |
| `POST` | `/service/strategy-config` | 替换全部策略配置 |
| `GET` | `/service/selection-config` | 获取选股配置与可选选股器 |
| `POST` | `/service/selection-config` | 更新选股配置 |
| `GET` | `/service/portfolio/config` | 获取组合配置与可选优化器 |
| `POST` | `/service/portfolio/config` | 更新组合配置 |
| `POST` | `/service/portfolio/optimize` | 组合优化预览 |
| `GET` | `/service/portfolio/analysis` | 组合分析快照 |
| `GET` | `/service/portfolio/history` | 组合历史 |
| `POST` | `/service/portfolio/rebalance` | 组合调仓预览或执行 |
| `GET` | `/service/scheduler-config` | 获取调度配置 |
| `POST` | `/service/scheduler-config` | 更新调度配置 |
| `POST` | `/service/close-all-positions` | 一键平仓 |
| `POST` | `/service/signal-buy` | 单标的买入信号 |
| `POST` | `/service/signal-sell` | 单标的卖出信号 |

## 4. 通用响应和错误处理

### 4.1 成功响应

所有接口默认返回 JSON。

### 4.2 失败响应

接口内部没有统一自定义错误模型，异常通常会表现为 HTTP 非 2xx，并带文本错误信息。

前端建议统一处理：

```ts
async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(`${apiBase}${path}`, options)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  return response.json()
}
```

## 5. 基础状态接口

### 5.1 `GET /health`

用途：基础健康检查。

响应示例：

```json
{
  "status": "ok"
}
```

前端用途：

- 顶部健康状态灯
- 联调时判断服务是否可达

### 5.2 `GET /service/status`

用途：获取服务运行状态和调度状态。

关键字段：

- `session_id`
- `mode`
- `running`
- `scheduler`
- `last_error`
- `last_result`

响应示例：

```json
{
  "session_id": "sg-paper-001",
  "mode": "paper",
  "running": true,
  "scheduler": {
    "interval_seconds": 300,
    "cron_expression": "0 15 * * 1-5",
    "timezone": "Asia/Shanghai",
    "schedule_type": "cron",
    "next_run_at": "2026-04-28T15:00:00+08:00",
    "next_run_in_seconds": 502.4,
    "next_runs": [
      "2026-04-28T15:00:00+08:00",
      "2026-04-29T15:00:00+08:00"
    ]
  },
  "last_error": null,
  "last_result": null
}
```

### 5.3 `GET /service/runtime`

用途：获取运行时状态快照。

关键字段：

- `positions`
- `oms_state`

说明：

- `positions` 适合用于持仓、待执行订单、当前运行态面板。
- `oms_state` 更偏调试和诊断。

### 5.4 `GET /service/performance`

用途：获取绩效、收益曲线、换手、仓位暴露等信息。

关键字段：

- `summary`
- `holding_returns`
- `turnover`
- `equity_curve`
- `trade_activity`
- `position_exposure`
- `latest_portfolio`

前端用途：

- 绩效图表
- 持仓收益表
- 曝险分析

### 5.5 `GET /service/analytics`

用途：一次性获取聚合快照。

响应结构：

```json
{
  "session_id": "sg-paper-001",
  "generated_at": "2026-04-28T13:00:00+08:00",
  "status": {},
  "runtime": {},
  "performance": {},
  "config": {}
}
```

适合：

- 总览页首屏加载
- 诊断页原始快照展示

## 6. 配置相关接口

### 6.1 `GET /service/config`

用途：获取当前完整配置快照。

关键字段：

- `config_bundle`
- `service`
- `selection_spec`
- `selection_provider`
- `strategy_specs`
- `portfolio_spec`
- `config_source`
- `persisted_user_config_available`
- `persisted_user_config_updated_at`

响应示例：

```json
{
  "session_id": "sg-paper-001",
  "config_bundle": {
    "service": {
      "session_id": "sg-paper-001",
      "mode": "paper",
      "price_lookback_days": 180,
      "max_candidates": 10,
      "auto_start": false,
      "frequency": "daily",
      "price_slippage": 0.0,
      "interval_seconds": 300,
      "cron_expression": null,
      "timezone": "Asia/Shanghai",
      "restore_persisted_state": true
    },
    "selection_spec": {
      "name": "factor_selector",
      "alias": "月频因子选股",
      "params": {
        "factor": "momentum",
        "start": "2020-01-01",
        "top_n": 100,
        "bottom_n": 100,
        "period": "M"
      }
    },
    "strategy_specs": [],
    "portfolio_spec": {
      "enabled": false,
      "optimizer": "riskfolio",
      "objective": "Sharpe",
      "risk_measure": "MV",
      "model": "Classic",
      "covariance_method": "ledoit"
    }
  },
  "service": {},
  "selection_spec": {},
  "selection_provider": {},
  "strategy_specs": [],
  "portfolio_spec": {},
  "config_source": "persisted_user_config",
  "persisted_user_config_available": true,
  "persisted_user_config_updated_at": "2026-04-28T12:31:00+08:00"
}
```

前端建议：

- 总览页显示 `config_source`
- 设置页初始值始终以该接口返回为准

### 6.2 `PUT /service/config`

用途：整体替换完整配置。

请求体：

```json
{
  "config_bundle": {
    "service": {},
    "selection_spec": null,
    "strategy_specs": [],
    "portfolio_spec": {}
  }
}
```

适合：

- 做“导入完整配置”
- 做“高级模式一键替换”

不太适合：

- 普通设置页逐项更新

普通设置页更推荐用下面拆分后的接口。

## 7. 调度控制接口

### 7.1 `POST /service/start`

用途：启动调度线程。

响应示例：

```json
{
  "status": "started",
  "session_id": "sg-paper-001"
}
```

### 7.2 `POST /service/stop`

用途：停止调度线程。

### 7.3 `POST /service/run-once`

用途：立即执行一轮选股/策略/调仓流程。

响应示例：

```json
{
  "session_id": "sg-paper-001",
  "mode": "paper",
  "cycle_time": "2026-04-28T13:02:00+08:00",
  "selection_count": 100,
  "long_candidate_count": 12,
  "short_candidate_count": 5,
  "executed_buy_count": 3,
  "executed_sell_count": 1,
  "selected_symbols": ["000001", "600519"],
  "long_symbols": ["000001"],
  "short_symbols": ["600519"],
  "status": "success",
  "error": null
}
```

### 7.4 `GET /service/scheduler-config`

用途：获取当前调度配置。

响应字段：

- `running`
- `auto_start`
- `scheduler`

### 7.5 `POST /service/scheduler-config`

用途：更新调度配置。

请求体：

```json
{
  "interval_seconds": 300,
  "cron_expression": "0 15 * * 1-5",
  "timezone": "Asia/Shanghai",
  "auto_start": true
}
```

说明：

- 字段都是可选的。
- `interval_seconds >= 1`
- `cron_expression` 可传 `null`

前端建议：

- “服务调度”单独作为一个设置分区
- 不要和 `selection / strategy / portfolio` 参数混在同一个表单里

## 8. 选股配置接口

### 8.1 `GET /service/selection-config`

用途：获取当前选股配置和所有可选选股器定义。

响应字段：

- `selection_spec`
- `active_selection_config`
- `available_selections`

响应示例：

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "月频动量",
    "params": {
      "factor": "momentum",
      "start": "2020-01-01",
      "top_n": 100,
      "bottom_n": 100,
      "factor_alpha": 0.1,
      "default_weight": 0.1,
      "period": "M",
      "insignificant_weight_ratio": 0.5,
      "missing_data_threshold": 0.1,
      "test_window": 36,
      "verbose": true
    }
  },
  "active_selection_config": {
    "factor": "momentum",
    "start": "2020-01-01"
  },
  "available_selections": [
    {
      "name": "factor_selector",
      "params_schema": {
        "type": "object",
        "properties": {}
      },
      "runtime_dependencies": ["jh_data"]
    }
  ]
}
```

前端重点：

- 使用 `available_selections` 渲染可选 `Selection Provider`
- 使用 `params_schema` 动态渲染参数表单
- `runtime_dependencies` 只做展示提示，不需要前端填写

### 8.2 `POST /service/selection-config`

用途：更新选股配置。

请求体：

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "月频动量",
    "params": {
      "factor": "momentum",
      "start": "2020-01-01",
      "top_n": 100,
      "bottom_n": 100,
      "factor_alpha": 0.1,
      "default_weight": 0.1,
      "period": "M",
      "insignificant_weight_ratio": 0.5,
      "missing_data_threshold": 0.1,
      "test_window": 36,
      "verbose": true
    }
  }
}
```

当前内置选股器：

- `factor_selector`

当前 `factor_selector` 常用字段：

- `factor`
- `start`
- `top_n`
- `bottom_n`
- `factor_alpha`
- `default_weight`
- `period`
- `insignificant_weight_ratio`
- `missing_data_threshold`
- `test_window`
- `verbose`

## 9. 策略配置接口

### 9.1 `GET /service/strategy-config`

用途：获取当前策略配置和可选策略定义。

响应字段：

- `strategy_specs`
- `available_strategies`

### 9.2 `POST /service/strategy-config`

用途：整体替换当前策略列表。

请求体：

```json
{
  "strategy_specs": [
    {
      "name": "moving_average_crossover",
      "weight": 1,
      "alias": "均线交叉",
      "params": {
        "short_window": 20,
        "long_window": 60
      }
    },
    {
      "name": "rsi",
      "weight": 0.8,
      "alias": "RSI 策略",
      "params": {
        "rsi_window": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "rsi_exit_oversold": 50,
        "rsi_exit_overbought": 50
      }
    }
  ]
}
```

说明：

- 这是“替换全部”的语义，不是 append。
- 前端应维护完整策略数组，再一次性提交。

当前内置策略：

- `turtle`
- `moving_average_crossover`
- `buy_and_hold`
- `volume_trend`
- `volume_divergence`
- `mean_reversion`
- `rsi`
- `bollinger_bands`
- `momentum`
- `breakout`
- `dual_thrust`

每个策略的参数结构应以 `available_strategies[].params_schema` 为准。

## 10. 组合配置接口

### 10.1 `GET /service/portfolio/config`

用途：获取当前组合配置和可选优化器定义。

响应字段：

- `portfolio_spec`
- `available_optimizers`

当前默认优化器：

- `riskfolio`

### 10.2 `POST /service/portfolio/config`

用途：更新组合配置。

请求体示例：

```json
{
  "portfolio_spec": {
    "enabled": true,
    "optimizer": "riskfolio",
    "objective": "Sharpe",
    "risk_measure": "MV",
    "model": "Classic",
    "covariance_method": "ledoit",
    "historical_lookback_days": 252,
    "max_assets": 20,
    "min_weight": 0.0,
    "max_weight": 0.2,
    "weight_epsilon": 0.001,
    "cash_reserve_ratio": 0.02,
    "lot_size": 100,
    "allow_partial_rebalance": true,
    "rebalance_policy": {
      "mode": "manual_only",
      "drift_threshold": null,
      "min_rebalance_interval_seconds": null,
      "schedule_cron": null,
      "on_selection_change": true,
      "on_strategy_change": true
    },
    "analysis": {
      "enabled": true,
      "benchmark_symbol": "000300.SH",
      "risk_free_rate": 0.02,
      "rolling_window": 60
    }
  }
}
```

前端中适合做预设选项的字段：

- `objective`
- `risk_measure`
- `model`
- `covariance_method`
- `rebalance_policy.mode`

这些字段仍建议最终以 schema 和后端校验结果为准。

### 10.3 `POST /service/portfolio/optimize`

用途：执行组合优化预览。

请求体：

```json
{
  "as_of_date": "2026-04-28",
  "preview_only": true,
  "symbols": ["000001", "600519"]
}
```

响应字段：

- `status`
- `optimizer`
- `as_of_date`
- `symbols`
- `weights`
- `diagnostics`
- `preview_only`

### 10.4 `GET /service/portfolio/analysis`

用途：获取当前组合分析快照。

响应字段：

- `portfolio_spec`
- `current_portfolio`
- `drift`
- `latest_optimization`
- `latest_rebalance`

### 10.5 `GET /service/portfolio/history`

用途：获取组合历史。

响应字段：

- `weight_history`
- `portfolio_value_history`

### 10.6 `POST /service/portfolio/rebalance`

用途：进行组合调仓预览或执行。

请求体：

```json
{
  "as_of_date": "2026-04-28",
  "preview_only": true,
  "symbols": ["000001", "600519"],
  "force": false
}
```

响应关键字段：

- `should_rebalance`
- `reason`
- `execution_path`
- `target_allocations`
- `buy_orders`
- `sell_orders`
- `blocked_buy_orders`
- `blocked_sell_orders`
- `projected_buy_cost`
- `projected_sell_value`
- `projected_cash_after`
- `drift`
- `executed_buy_count`
- `executed_sell_count`

前端建议：

- `preview_only=true` 作为默认值
- 先预览，再允许用户确认执行

## 11. 交易操作接口

### 11.1 `POST /service/close-all-positions`

用途：一键平仓。

请求体：

```json
{
  "slippage": 0.001
}
```

响应字段：

- `status`
- `closed_count`
- `executed_trades`

### 11.2 `POST /service/signal-buy`

用途：触发单标的买入。

请求体：

```json
{
  "symbol": "600519",
  "target_qty": 100,
  "slippage": 0.001
}
```

### 11.3 `POST /service/signal-sell`

用途：触发单标的卖出。

请求体与买入一致。

单标的交易响应字段：

- `status`
- `action`
- `symbol`
- `executed`
- `trade`
- `message`

## 12. 事件历史接口

### 12.1 `GET /service/events`

用途：查看服务事件历史。

响应字段：

- `session_id`
- `count`
- `events`

每条 `event` 包含：

- `event_type`
- `event_time`
- `export_time`
- `state_data`

适合：

- 审计时间线
- 调试状态恢复逻辑
- 展示配置变更历史

## 13. 关键配置模型说明

### 13.1 `ServiceConfig`

主要字段：

- `session_id`
- `mode`: `paper | live`
- `price_lookback_days`
- `max_candidates`
- `auto_start`
- `frequency`
- `price_slippage`
- `interval_seconds`
- `cron_expression`
- `timezone`
- `restore_persisted_state`

### 13.2 `SelectionSpec`

字段：

- `name`
- `params`
- `alias`

### 13.3 `StrategySpec`

字段：

- `name`
- `weight`
- `params`
- `alias`

### 13.4 `PortfolioSpec`

核心字段：

- `enabled`
- `optimizer`
- `objective`
- `risk_measure`
- `model`
- `covariance_method`
- `historical_lookback_days`
- `max_assets`
- `min_weight`
- `max_weight`
- `weight_epsilon`
- `cash_reserve_ratio`
- `lot_size`
- `allow_partial_rebalance`
- `rebalance_policy`
- `analysis`

### 13.5 `RebalancePolicySpec`

字段：

- `mode`
- `drift_threshold`
- `min_rebalance_interval_seconds`
- `schedule_cron`
- `on_selection_change`
- `on_strategy_change`

当前 `mode` 枚举：

- `disabled`
- `initial_only`
- `every_cycle`
- `drift_threshold`
- `schedule`
- `manual_only`

### 13.6 `PortfolioAnalysisSpec`

字段：

- `enabled`
- `benchmark_symbol`
- `risk_free_rate`
- `rolling_window`

## 14. 推荐的前端页面拆分

推荐将设置页分成五块：

1. `Connection`
   只管理 `apiBase`、刷新间隔等前端本地设置。
2. `Service`
   对接 `GET/POST /service/scheduler-config`。
3. `Selection`
   对接 `GET/POST /service/selection-config`。
4. `Strategy`
   对接 `GET/POST /service/strategy-config`。
5. `Portfolio`
   对接 `GET/POST /service/portfolio/config`，以及 `optimize/rebalance/analysis/history`。

这样可以避免不同关注点混杂。

## 15. 推荐的前端状态结构

```ts
type DashboardState = {
  health: any
  status: any
  runtime: any
  performance: any
  config: any
  selectionConfig: any
  strategyConfig: any
  portfolioConfig: any
}
```

建议将：

- 只读快照
- 用户编辑表单
- 动态 schema 定义

分开存储，不要混成一个对象。

## 16. 一个推荐的对接流程

### 16.1 首屏

1. 检查 `GET /health`
2. 拉取 `GET /service/analytics`
3. 拉取三个配置定义接口
4. 基于返回生成表单初始值

### 16.2 用户保存选股配置

1. 从 `available_selections` 找到选中的 provider
2. 用 `params_schema` 渲染参数表单
3. 组装 `selection_spec`
4. 提交 `POST /service/selection-config`
5. 成功后重新请求：
   - `GET /service/config`
   - `GET /service/selection-config`

### 16.3 用户保存策略配置

1. 在前端维护完整 `strategy_specs[]`
2. 提交 `POST /service/strategy-config`
3. 重新请求 `GET /service/strategy-config`

### 16.4 用户保存组合配置

1. 根据 `available_optimizers[0].params_schema` 生成表单
2. 提交 `POST /service/portfolio/config`
3. 如需预览，调用 `POST /service/portfolio/optimize`
4. 如需调仓预览，调用 `POST /service/portfolio/rebalance`

## 17. 当前实现上的几个注意点

### 17.1 `POST /service/strategy-config` 是替换，不是追加

前端不要误以为每次发一个策略就会 append。

### 17.2 `params_schema` 是权威来源

尤其是：

- 选股参数
- 策略参数
- 组合参数

前端预设选项可以增强体验，但不应替代 schema 驱动。

### 17.3 `active_selection_config` 和 `selection_spec.params` 不完全等价

- `selection_spec.params` 是用户输入配置
- `active_selection_config` 更像运行时解析后的配置

展示上可以都保留，但编辑时优先以 `selection_spec.params` 为准。

### 17.4 完整配置替换要谨慎

`PUT /service/config` 会整体替换服务配置，更适合高级操作，不建议给普通用户做成高频按钮。

## 18. 文档维护位置

本文档所在路径：

- [API_DOCUMENTATION.md](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/documents/API_DOCUMENTATION.md:1)

文档索引：

- [index.md](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/documents/index.md:1)

当以下内容变更时，应同步更新本文档：

- 新增/删除 API 路由
- 请求/响应模型字段变更
- Registry 中新增可配置组件
- 配置优先级和持久化恢复逻辑变更
