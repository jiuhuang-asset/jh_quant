# 项目架构

## 目录结构

```
jh_quant/
├── data/            # JHData API 客户端 + DuckDB 缓存
├── backtest/        # 回测引擎（11 种策略）
├── factors/         # 因子引擎（11 种因子模型）
├── trading/         # Signal Gateway + 交易服务编排 + Bootstrap + Sync
├── dashboard/       # PyWebView 可视化仪表盘
└── cli/             # CLI 入口（jh-quant paper/live/sync）
```

## 数据流

```
JHData.get_data() ──> JiuHuang API（DuckDB 本地缓存）
       │
       ├──> backtest() ──> Strategy.__call__() ──> build_position()
       │
       ├──> FactorEngine ──> FactorCalculator / StockExposureCalculator
       │
       └──> Trading Service
              ├──> SelectionProvider.select()
              ├──> 多策略信号聚合
              ├──> 组合优化（Riskfolio）
              ├──> 风控规则过滤
              └──> execute_long/short() ──> Broker/OMS
```

## 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **Strategy 模式** | `backtest/strategies/` | 所有策略继承 `Strategy` 基类，实现 `_execute_one(symbol, df)` |
| **Provider 模式** | `trading/` | `MarketDataProvider`、`SelectionProvider`、`OrderRecorder` 均为抽象基类 |
| **Builder 模式** | `trading/config.py` | `SessionServiceConfigBuilder` 流式构建交易配置 |
| **DataFrame 包装** | `data/` | `_JHDataWrapper` 为 DataFrame 附加 `jh_dt`、`code_col`、`date_col` 元数据 |

## 环境要求

- Python 3.10+
- 依赖：`pandas`、`duckdb`、`httpx`、`numpy`、`joblib`、`polars`（可选加速）
- 环境变量：
  - `JIUHUANG_API_KEY` — 数据 API 密钥（必填）
  - `JIUHUANG_API_URL` — 数据 API 地址（默认 `https://data.jiuhuang.xyz`）
  - `REMOTE_DB_URL` — Sync 远程数据库 DSN

## 命名约定

| 类型 | 风格 | 示例 |
|------|------|------|
| 模块/文件 | 下划线小写 | `jh_quant/backtest/strategies/` |
| 类 | PascalCase | `StrategyTurtle`、`FactorEngine`、`JHData` |
| 函数/变量 | 下划线小写 | `get_data()`、`calculate_factor_returns()` |
| 私有方法 | 前缀下划线 | `_execute_one()` |
| 测试文件 | `test_` 前缀 | `test_backtest.py` |

## 关键入口文件

| 文件 | 说明 |
|------|------|
| `jh_quant/data/jh_data.py` | JHData 客户端 |
| `jh_quant/data/datatypes.py` | DataTypes 枚举 |
| `jh_quant/backtest/backtest.py` | 回测主函数 + 绩效评估 |
| `jh_quant/backtest/strategies/` | 11 种内置策略 |
| `jh_quant/factors/main.py` | FactorEngine + 便捷函数 |
| `jh_quant/factors/factors/` | 各因子模型计算器 |
| `jh_quant/trading/bootstrap.py` | trading bootstrap |
| `jh_quant/trading/config.py` | Builder 配置系统 |
| `jh_quant/trading/sync/` | 数据同步模块 |
| `jh_quant/dashboard/` | PyWebView 仪表盘 |
| `jh_quant/cli/` | 命令行入口 |
