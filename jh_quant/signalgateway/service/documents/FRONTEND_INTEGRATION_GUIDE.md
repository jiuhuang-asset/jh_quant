# SignalGateway 前端集成指南 v1

本文档版本：`v1`

本文档面向前端开发者，重点回答三个问题：

1. 首屏应该怎么拉数据
2. 设置页应该怎么拆
3. `selection / strategy / portfolio` 这类动态配置应该怎么对接

底层接口字段明细请配合 [API_DOCUMENTATION.md](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/documents/API_DOCUMENTATION.md:1) 一起看。

## 1. 先理解这套服务的结构

SignalGateway 的前端不是一个简单的“状态看板”，而是一个“运行态 + 配置工作台”。

建议把它理解成 5 个关注点：

1. `Connection`
   管理前端自己的 API 地址、刷新频率。
2. `Service`
   管理调度、运行、停止、手动执行。
3. `Selection`
   管理选股器及参数。
4. `Strategy`
   管理策略列表及参数。
5. `Portfolio`
   管理组合优化、调仓、分析。

核心原则是：

- 前端本地设置和后端服务配置分开
- 调度设置和选股/策略/组合设置分开
- schema 定义和用户填写值分开
- 只读快照和可编辑表单分开

## 2. 推荐页面结构

建议页面至少有三个一级区：

1. `总览`
   展示健康状态、运行状态、配置来源、最近结果。
2. `设置`
   再拆成二级菜单：
   - `连接设置`
   - `服务调度`
   - `选股配置`
   - `策略配置`
   - `组合配置`
3. `诊断`
   展示健康状态、接口地址、最近刷新、原始快照、最近错误。

其中“设置页二级拆分”很重要，不建议把所有字段堆成一个超长表单。

## 3. 推荐首屏加载流程

### 3.1 最稳妥方案

前端初始化时并行请求：

1. `GET /health`
2. `GET /service/status`
3. `GET /service/runtime`
4. `GET /service/performance`
5. `GET /service/config`
6. `GET /service/selection-config`
7. `GET /service/strategy-config`
8. `GET /service/portfolio/config`

### 3.2 更快的总览方案

如果你要先把总览渲染出来，可以先请求：

1. `GET /health`
2. `GET /service/analytics`

然后在进入设置页时再补：

1. `GET /service/selection-config`
2. `GET /service/strategy-config`
3. `GET /service/portfolio/config`

原因：

- `/service/analytics` 有 `status / runtime / performance / config`
- 但没有动态表单最关键的 registry schema

## 4. 推荐前端状态分层

建议至少分成 4 层状态。

### 4.1 只读服务快照

```ts
type DashboardSnapshotState = {
  health: any
  status: any
  runtime: any
  performance: any
  config: any
}
```

### 4.2 动态 schema 定义

```ts
type ConfigDefinitionsState = {
  availableSelections: any[]
  availableStrategies: any[]
  availableOptimizers: any[]
}
```

### 4.3 用户正在编辑的表单

```ts
type SettingsFormState = {
  connection: {
    apiBase: string
    refreshIntervalMs: number
  }
  scheduler: {
    interval_seconds: number | null
    cron_expression: string | null
    timezone: string | null
    auto_start: boolean | null
  }
  selection: {
    name: string
    alias: string
    params: Record<string, any>
  }
  strategies: Array<{
    name: string
    alias: string
    weight: number
    params: Record<string, any>
  }>
  portfolio: {
    portfolio_spec: Record<string, any>
  }
}
```

### 4.4 页面本地 UI 状态

```ts
type UiState = {
  activeNav: 'overview' | 'settings' | 'diagnostics'
  activeSettingsPanel: 'connection' | 'service' | 'selection' | 'strategy' | 'portfolio'
  isRefreshing: boolean
  lastRefreshedAt: string
  errorText: string
}
```

## 5. 配置优先级一定要讲清楚

这是这套服务最容易让前端误判的地方。

当前生效配置可能来自两个来源：

1. `bootstrap config`
   服务启动时传入的初始配置。
2. `persisted user config`
   用户后续通过 API 修改后持久化到数据库的配置。

前端应始终以 `GET /service/config` 返回值为准，而不是页面默认值。

重点看这几个字段：

- `config_source`
- `persisted_user_config_available`
- `persisted_user_config_updated_at`

推荐在总览页或者诊断页显示它们。

## 6. 设置页怎么做才不耦合

### 6.1 Connection

只放前端自己的设置：

- `apiBase`
- `refreshIntervalMs`

这些一般存本地，例如 `localStorage`。

### 6.2 Service

只对接：

- `GET /service/scheduler-config`
- `POST /service/scheduler-config`
- `POST /service/start`
- `POST /service/stop`
- `POST /service/run-once`

这一组只负责“什么时候运行”，不负责“运行什么策略”。

### 6.3 Selection

只对接：

- `GET /service/selection-config`
- `POST /service/selection-config`

这里不要和策略/组合字段混在一起。

### 6.4 Strategy

只对接：

- `GET /service/strategy-config`
- `POST /service/strategy-config`

注意它是“整体替换策略数组”，不是单条 append。

### 6.5 Portfolio

只对接：

- `GET /service/portfolio/config`
- `POST /service/portfolio/config`
- `POST /service/portfolio/optimize`
- `POST /service/portfolio/rebalance`
- `GET /service/portfolio/analysis`
- `GET /service/portfolio/history`

## 7. 动态 schema 表单的正确打开方式

### 7.1 Selection

先请求：

- `GET /service/selection-config`

然后使用：

- `available_selections[].name`
- `available_selections[].params_schema`

来生成：

- 可选 provider 下拉
- provider 参数表单

### 7.2 Strategy

先请求：

- `GET /service/strategy-config`

然后使用：

- `available_strategies[].name`
- `available_strategies[].params_schema`

来生成每个策略实例的参数表单。

### 7.3 Portfolio

先请求：

- `GET /service/portfolio/config`

然后使用：

- `available_optimizers[].params_schema`

来生成组合参数表单。

## 8. 预设选项和 schema 驱动如何共存

前端体验上，建议给这些专业字段加预设选项：

- `factor`
- `period`
- `objective`
- `risk_measure`
- `model`
- `covariance_method`
- `rebalance_policy.mode`

但要注意：

- 预设只是“增强体验”
- schema 仍然是“后端权威”

也就是说：

1. 先从 schema 确认字段存在
2. 如果这个字段属于你维护的预设项，就用更友好的 select 渲染
3. 其他字段仍按 schema 通用渲染

## 9. 推荐的保存流程

### 9.1 保存调度配置

1. 用户修改 `interval_seconds / cron_expression / timezone / auto_start`
2. 调用 `POST /service/scheduler-config`
3. 成功后重新拉：
   - `GET /service/status`
   - `GET /service/scheduler-config`
   - `GET /service/config`

### 9.2 保存选股配置

1. 从 `available_selections` 找到当前选中的 provider
2. 用其 `params_schema` 渲染并校验参数
3. 提交：

```json
{
  "selection_spec": {
    "name": "factor_selector",
    "alias": "月频动量",
    "params": {}
  }
}
```

4. 成功后重新拉：
   - `GET /service/selection-config`
   - `GET /service/config`

### 9.3 保存策略配置

1. 前端维护完整 `strategy_specs[]`
2. 调用 `POST /service/strategy-config`
3. 成功后重新拉：
   - `GET /service/strategy-config`
   - `GET /service/config`

### 9.4 保存组合配置

1. 维护完整 `portfolio_spec`
2. 调用 `POST /service/portfolio/config`
3. 成功后重新拉：
   - `GET /service/portfolio/config`
   - `GET /service/config`

## 10. 预览优先，不要默认真执行

组合相关操作建议默认都走 preview。

### 10.1 优化预览

调用：

- `POST /service/portfolio/optimize`

推荐默认：

```json
{
  "preview_only": true
}
```

### 10.2 调仓预览

调用：

- `POST /service/portfolio/rebalance`

推荐默认：

```json
{
  "preview_only": true,
  "force": false
}
```

先让用户看到：

- `should_rebalance`
- `reason`
- `buy_orders`
- `sell_orders`
- `blocked_buy_orders`
- `blocked_sell_orders`

再决定是否执行。

## 11. 总览页建议展示哪些字段

推荐展示：

- `health.status`
- `status.running`
- `status.mode`
- `status.session_id`
- `status.scheduler.next_run_at`
- `status.last_error`
- `config.config_source`
- `config.persisted_user_config_available`
- `performance.latest_portfolio`

## 12. 诊断页建议展示哪些字段

推荐展示：

- 健康状态
- 当前 API 地址
- 最近刷新时间
- 最近错误
- 原始 `analytics` / `config` / `runtime` 快照
- 接口耗时

## 13. 常见误区

### 13.1 把本地连接设置发给后端

不应该。

`apiBase`、`refreshIntervalMs` 是前端本地设置，不属于后端配置。

### 13.2 用页面默认值覆盖服务当前值

不应该。

设置页初始化应始终以接口返回值为准。

### 13.3 把 `POST /service/strategy-config` 当成“新增一条策略”

不应该。

它是替换整个数组。

### 13.4 忽略 `config_source`

不建议。

如果不展示配置来源，前端很难解释“为什么页面打开后看到的不是启动时写死的那套配置”。

## 14. 一个推荐的实现顺序

1. 先做好基础 API client
2. 再做好 `analytics + config definitions` 的首屏加载
3. 再拆 `Connection / Service / Selection / Strategy / Portfolio`
4. 再补专业字段预设选项
5. 最后补诊断页和原始快照

## 15. 相关文档

- 接口参考：[API_DOCUMENTATION.md](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/documents/API_DOCUMENTATION.md:1)
- 文档索引：[index.md](/e:/个人/jiuhuang-asset/jh_quant/jh_quant/signalgateway/service/documents/index.md:1)
