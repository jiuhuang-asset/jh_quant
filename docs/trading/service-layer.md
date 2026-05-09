# 服务层

服务层提供 REST API 服务，包括 `SessionService`（单会话管理）和 `MultiSessionService`（多会话管理）。

---

## SessionService

`SessionService` 封装了单个会话的完整生命周期：配置管理、调度执行、状态查询、绩效追踪。

它由 `MultiSessionService.create_session()` 自动创建，通常无需手动构造。

### 核心方法

#### 交易执行

| 方法 | 说明 |
|------|------|
| `run_once(as_of_date=None)` | 手动执行一次交易周期 |
| `run_backfill()` | 执行历史回填（从 `backfill_from` 到最新交易日） |
| `close_all_positions(slippage=0.0)` | 一键平仓 |
| `signal_buy_symbol(symbol, target_qty=None, slippage=0.0)` | 手动买入单个标的 |
| `signal_sell_symbol(symbol, target_qty=None, slippage=0.0)` | 手动卖出单个标的 |

#### 调度控制

| 方法 | 说明 |
|------|------|
| `start_scheduler()` | 启动 Cron 定时调度 |
| `stop_scheduler()` | 停止调度 |
| `shutdown_session()` | 关闭会话，释放资源 |

#### 配置管理

| 方法 | 说明 |
|------|------|
| `get_config_snapshot()` | 获取完整配置快照 |
| `get_strategy_config_snapshot()` | 获取策略配置快照 |
| `get_selection_config_snapshot()` | 获取选股器配置快照 |
| `get_portfolio_config_snapshot()` | 获取组合配置快照 |
| `get_scheduler_config_snapshot()` | 获取调度配置快照 |
| `replace_session_config(config_bundle)` | 热替换会话配置 |
| `update_scheduler_config(cron_expression, timezone, auto_start)` | 动态更新调度配置 |
| `get_session_config_history()` | 查询配置变更历史 |
| `configure_strategies(specs)` | 热更新策略 |
| `configure_risk_rules(specs)` | 热更新风险规则 |
| `configure_selection(spec)` | 热更新选股器 |
| `configure_portfolio(spec)` | 热更新组合优化参数 |

#### 状态与绩效查询

| 方法 | 说明 |
|------|------|
| `get_status()` | 获取会话运行状态 |
| `get_runtime_state()` | 获取运行时状态快照 |
| `get_runtime_snapshot()` | 获取运行时快照（含最近事件） |
| `get_performance_snapshot()` | 获取绩效摘要 |
| `get_analysis_snapshot()` | 获取分析摘要 |
| `get_trade_history(symbol, limit)` | 查询交易历史 |
| `get_positions()` | 查询当前持仓 |
| `get_position_history(symbol)` | 查询持仓历史 |
| `get_session_event_history()` | 查询会话事件历史 |

#### 组合优化

| 方法 | 说明 |
|------|------|
| `optimize_portfolio(as_of_date, symbols, preview_only)` | 运行组合优化 |
| `rebalance_portfolio(as_of_date, symbols, preview_only, force)` | 执行组合再平衡 |
| `get_portfolio_analysis_snapshot()` | 获取组合分析快照 |
| `get_portfolio_history()` | 获取组合历史 |
| `should_rebalance_portfolio(drift, force, as_of_time)` | 判断是否需要再平衡 |

---

## MultiSessionService

管理多个 `SessionService` 实例。

```python
from jh_quant.trading import MultiSessionService, PersistenceCoordinator, SQLiteOrderRecorder, JHMarketDataProvider

recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
persistence = PersistenceCoordinator(recorder=recorder)

manager = MultiSessionService(
    max_sessions=4,                   # 最大会话数
    persistence=persistence,          # 共享持久化层
    market_data_provider=JHMarketDataProvider(),  # 共享行情数据
)
```

### 核心方法

| 方法 | 说明 |
|------|------|
| `create_session(config, initial_capital=100000) -> str` | 创建并注册新会话，返回 `session_id` |
| `wrap_session(service) -> str` | 直接注入已构造的 `SessionService` |
| `remove_session(session_id)` | 移除并关闭会话 |
| `get_session(session_id) -> SessionService` | 获取指定会话 |
| `list_sessions() -> SessionListResponse` | 列出所有会话 |
| `get_session_trends(session_ids, limit, days)` | 获取多会话权益曲线趋势 |
| `stop_all()` / `shutdown()` | 关闭所有会话 |

---

## REST API

### 应用工厂

```python
from jh_quant.trading.service import create_session_app, create_unified_app, run_trading_app

# 单会话应用
app = create_session_app(session)

# 多会话应用
app = create_unified_app(manager)

# 一行启动
run_trading_app(manager=manager, host="127.0.0.1", port=8000)
```

### 接口列表

#### 应用级接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/sessions` | 列出所有会话 |
| `POST` | `/sessions` | 创建新会话 |
| `DELETE` | `/sessions/{session_id}` | 删除会话 |
| `GET` | `/sessions/trends` | 多会话权益趋势 |
| `GET` | `/data/stock/{symbol}` | 查询单只股票历史数据 |

#### 会话级接口 (`/sessions/{session_id}/`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `status` | 会话运行状态 |
| `POST` | `run-once` | 手动执行一次 |
| `POST` | `run-backfill` | 执行历史回填 |
| `GET` | `config` | 查看完整配置 |
| `PUT` | `config` | 更新配置 |
| `GET` | `config/history` | 配置变更历史 |
| `GET` | `config/strategy` | 策略配置 |
| `PUT` | `config/strategy` | 更新策略配置 |
| `GET` | `config/selection` | 选股器配置 |
| `PUT` | `config/selection` | 更新选股器配置 |
| `GET` | `config/portfolio` | 组合优化配置 |
| `PUT` | `config/portfolio` | 更新组合优化配置 |
| `GET` | `positions` | 当前持仓 |
| `GET` | `positions/history` | 持仓历史 |
| `GET` | `trades` | 交易历史 |
| `GET` | `performance` | 绩效摘要 |
| `GET` | `runtime` | 运行时快照 |
| `POST` | `close-all` | 一键平仓 |
| `POST` | `signal/buy` | 手动买入 |
| `POST` | `signal/sell` | 手动卖出 |
| `GET` | `events` | 会话事件历史 |
| `POST` | `portfolio/optimize` | 组合优化预览 |
| `POST` | `portfolio/rebalance` | 触发组合再平衡 |
| `GET` | `portfolio/analysis` | 组合分析 |
| `GET` | `portfolio/history` | 组合历史 |
| `GET` | `definitions/strategies` | 可用策略列表 |
| `GET` | `definitions/risk-rules` | 可用风险规则列表 |
| `GET` | `definitions/selection-providers` | 可用选股器列表 |
| `GET` | `definitions/portfolio-optimizers` | 可用组合优化器列表 |

启动后访问 `http://127.0.0.1:8000/docs` 可查看完整的 Swagger 交互式文档。

---

## CronScheduler

`CronScheduler` 是会话定时执行的基础设施，基于标准 Cron 表达式调度。

```python
from jh_quant.trading.service.core import CronScheduler

scheduler = CronScheduler(
    cron_expression="0 16 * * 1-5",  # 周一到周五 16:00
    timezone="Asia/Shanghai",
)

# 查看未来 3 次触发时间
for ts in scheduler.peek_next_ticks(3):
    print(f"下次触发: {ts}")

# 等待直到下一次触发（阻塞）
stop_event = threading.Event()
triggered = scheduler.wait(stop_event)
```

调度器在 `SessionService` 内部自动管理，通常无需直接使用。
