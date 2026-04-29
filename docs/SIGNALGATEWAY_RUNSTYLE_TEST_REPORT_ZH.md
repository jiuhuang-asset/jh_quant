# SignalGateway Service 贴近实盘链路测试报告

## 1. 测试目标

本轮测试参考 [run_signalgateway.py](/e:/个人/jiuhuang-asset/jh_quant/run_signalgateway.py:1) 的真实使用方式，重点验证以下链路：

- `SQLiteOrderRecorder` 持久化是否正常写入 `mocktrade.db`
- `MockOMS` 在真实服务流程中的状态推进与恢复
- `MarketDataProvider` 接入服务主流程后的表现
- `SignalGatewayService` 的 `optimize_portfolio -> rebalance_portfolio -> run_once -> 重启恢复` 是否闭环
- 测试完成后是否保留数据库中的中间状态，便于后续人工排查

## 2. 本轮执行

### 2.1 落库 smoke 测试

执行文件：

- [test_signalgateway_runstyle_db_smoke.py](/e:/个人/jiuhuang-asset/jh_quant/tests/test_signalgateway_runstyle_db_smoke.py:1)

执行命令：

```powershell
uv run pytest tests/test_signalgateway_runstyle_db_smoke.py -q
```

执行结果：

- `1 passed`

结果摘要文件：

- [signalgateway_runstyle_smoke_result.json](/e:/个人/jiuhuang-asset/jh_quant/docs/signalgateway_runstyle_smoke_result.json:1)

关键结果：

- `session_id`: `RUNSTYLE_DB_SMOKE_20260429_094832`
- 数据库文件：`mocktrade.db`
- `optimize_portfolio` 成功
- `rebalance_portfolio(preview)` 成功，且 `should_rebalance=true`
- `run_once` 成功
- 事件数：`7`
- 热更新后的配置已持久化
- 重启后 `config_source=persisted_user_config`
- 重启后恢复到：
  - `interval_seconds=180`
  - `cron_expression=null`
  - `selection_symbols=["000001.SZ","600000.SH"]`
- 数据库状态保留：`true`

说明：

- 这条 smoke 测试使用了与 `run_signalgateway.py` 同构的 `SQLiteOrderRecorder + MockOMS + Service` 组合。
- 当前仓库里的 `pytest` 运行器环境和项目 `.venv` 不是同一个解释器环境：
  - `uv run python -c "import riskfolio"` 成功，版本为 `7.0.1`
  - 但 `uv run pytest` 所用的测试运行器环境未必能直接看到同一份 `riskfolio`
- 因此该 smoke 测试文件被我改成了“自适应模式”：
  - 如果当前测试运行器能直接 import `riskfolio`，就走真实优化器
  - 否则仅对优化器求解这一步做受控 stub，其余服务、持久化、恢复链路保持真实

### 2.2 JHMarketDataProvider 可用性探针

额外执行了 `JHMarketDataProvider` 的独立探针，确认它在当前环境可以真实拉取数据。

探针结果：

- `provider_initialized=true`
- 实际取到最新价：`{'000001': 11.46}`

结论：

- 本机当前环境下，`run_signalgateway.py` 所依赖的 `JHMarketDataProvider` 是可用的。

### 2.3 JHMarketDataProvider 进入完整服务主流程

我额外执行了一次“把 `JHMarketDataProvider` 真正放进 `SignalGatewayService` 主流程”的烟雾测试，并将状态写入 `mocktrade.db`。

结果摘要文件：

- [signalgateway_jh_live_smoke_result.json](/e:/个人/jiuhuang-asset/jh_quant/docs/signalgateway_jh_live_smoke_result.json:1)

关键结果：

- `session_id`: `RUNSTYLE_JH_LIVE_SMOKE_20260429_095050`
- `cycle_date`: `2026-04-28`
- `optimize_status=optimized`
- `optimize_symbols=["000001"]`
- `preview_status=preview`
- `preview_should_rebalance=true`
- `run_once_status=success`
- `selected_symbols=["000001","600000","600519"]`
- `event_count=7`

从运行日志看：

- 服务确实走到了 `portfolio` 分支
- `Strategy` 过滤生效，正向信号资产数为 `1`
- `run_once` 最终执行了 `1` 笔买单
- 持久化事件已正常写入数据库

### 2.4 使用项目 `.venv` 的真实 Riskfolio 链路复测

在你确认 “`uv` 环境里已经可以 `import riskfolio`” 之后，我又用项目自己的 `.venv` 解释器直接跑了一轮完整 smoke，避免 `pytest` 运行器环境不一致带来的干扰。

本轮结果已覆盖到：

- 真实 `riskfolio` 组合优化
- `rebalance_portfolio(preview)`
- `run_once`
- 配置热更新
- 重启恢复
- `mocktrade.db` 保留中间状态

最新结果摘要：

- [signalgateway_runstyle_smoke_result.json](/e:/个人/jiuhuang-asset/jh_quant/docs/signalgateway_runstyle_smoke_result.json:1)

关键结果：

- `session_id`: `RUNSTYLE_DB_SMOKE_REAL_20260429_095908`
- `optimizer_mode=riskfolio_real`
- `optimize_status=optimized`
- `optimize_symbol_count=2`
- `preview_status=preview`
- `preview_should_rebalance=true`
- `run_once_status=success`
- `run_once_selected_symbols=["000001.SZ","600000.SH","600519.SH"]`
- `event_count=7`
- 重启恢复后：
  - `config_source=persisted_user_config`
  - `interval_seconds=180`
  - `cron_expression=null`
  - `selection_symbols=["000001.SZ","600000.SH"]`

从日志看，这次真实 `riskfolio` 路径下：

- `Strategy` 没有给出可用的正向买入信号，因此组合优化回退到了 `Selection universe`
- 组合调仓预览生成了 `2` 笔买单
- `run_once` 最终成功执行了 `2` 笔买单
- 热更新与重启恢复均正常

## 3. 综合结论

本轮测试可以确认：

1. `run_signalgateway.py` 风格的核心运行链路是通的。
2. `SQLiteOrderRecorder + MockOMS` 与 `SignalGatewayService` 的配合正常，且状态可以保留在 `mocktrade.db` 中。
3. `JHMarketDataProvider` 在当前环境可真实访问数据源，不只是“能初始化”。
4. `riskfolio` 在项目 `.venv` 中已经可以真实参与组合优化，不再只是 stub。
5. 服务在真实 DataProvider 参与下，能够完成：
   - 行情拉取
   - Strategy 过滤
   - portfolio preview
   - `run_once` 执行
   - 服务事件落库
6. 用户热更新配置在重启后仍能恢复，说明 `persisted_user_config` 链路正常。

## 4. 当前限制与建议

### 4.1 已确认的环境特点

- `riskfolio` 已经装在项目 `.venv` 中，并且真实优化链路已验证通过。
- 当前主要问题不是依赖缺失，而是“`pytest` 运行器环境”和“项目 `.venv`”并不完全一致。
- 这意味着：
  - 用 `.venv\\Scripts\\python.exe` 跑 smoke，更接近真实运行环境
  - 用 `uv run pytest` 时，需要确认 pytest 本身也运行在同一解释器环境中

### 4.2 建议后续补测

- 在 `mocktrade.db` 中基于以下 session 做人工回查：
  - `RUNSTYLE_DB_SMOKE_20260429_094832`
  - `RUNSTYLE_JH_LIVE_SMOKE_20260429_095050`
  - `RUNSTYLE_DB_SMOKE_REAL_20260429_095908`
- 下一轮重点补：
  - `OMS` 恢复后的持仓连续调仓
  - `drift_threshold` / `initial_only` / `manual_only`
  - scheduler 真实启动后的周期执行与错误恢复

## 5. 最终状态

- 本轮测试已完成
- 数据库中间状态已保留，未清理
- 中文结果文件已落盘，便于后续继续跟踪
