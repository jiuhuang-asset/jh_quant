# Bootstrap 模板

`jh_quant.trading.bootstrap` 用来降低模拟盘和实盘启动成本。CLI 入口只需要选择模板、backend、策略、股票池和少量运行参数，bootstrap 会完成行情服务、持久化、选股器、session config、API 和 Dashboard 的组装。

## CLI 入口

```bash
jh-quant paper --help
jh-quant live  --help
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--template` | 模板：`paper-basic`、`paper-compare`、`live-basic` |
| `--backend` | 行情 backend：`tushare`、`akshare`、`xquant` |
| `--strategy` | 一个或多个策略名，多个用英文逗号分隔 |
| `--symbols` | 股票池，纯代码格式，例如 `688041,688256` |
| `--db-path` | SQLite 数据库路径 |
| `--host` | API 服务绑定地址，默认 `127.0.0.1` |
| `--port` | API 服务端口，默认 `8000` |
| `--no-dashboard` | 只启动 API，不自动打开 Dashboard |
| `--dashboard-refresh-ms` | Dashboard 刷新间隔，默认 15000 毫秒 |
| `--no-backfill` | 关闭回填模式 |
| `--no-auto-start` | 创建 session 但不自动启动调度 |

`--strategy` 的可选值来自系统已注册策略，完整列表会显示在 `--help` 中。

## 内置模板

| 模板 | 行为 |
| --- | --- |
| `paper-basic` | 创建一个模拟盘 session；多个策略在同一 session 内等权聚合 |
| `paper-compare` | 为每个策略创建独立模拟盘 session，适合做策略对比；始终保留 `turtle` 基准 |
| `live-basic` | 创建一个实盘 session；broker 使用 xtquant/MiniQMT |

默认策略：

| 模板 | 默认策略 |
| --- | --- |
| `paper-basic` | `momentum` |
| `paper-compare` | `turtle,momentum` |
| `live-basic` | `momentum` |

`jh-quant paper` 默认使用 `paper-compare`。当用户传入 `--strategy rsi` 时，bootstrap 会自动保留 `turtle` 基准场景，并额外创建 `paper-rsi`。

## 默认股票池

默认股票池偏向半导体 / AI 芯片链，便于演示并行策略比较：

```text
688041, 688256, 688981, 688012, 688008, 688347, 603986,
603501, 300604, 002371, 688072, 688525, 688126, 688521
```

## 行情 Backend

| backend | 历史行情 | 实时行情 |
| --- | --- | --- |
| `tushare` | `TuShareHistoricalBarProvider` | 复用 AkShare 实时行情合并当天数据 |
| `akshare` | `AkShareHistoricalBarProvider` | `AkShareRealtimeQuoteProvider` |
| `xquant` | `TuShareHistoricalBarProvider` | `XtQuantRealtimeQuoteProvider` |

默认 backend 是 `tushare`。

## 选股器

内置两种选股器：

| 选股器 | 说明 |
| --- | --- |
| `watchlist` | 固定股票池选股（bootstrap 默认） |
| `factor_selector` | 基于因子排序选股（包装 `jh_quant.backtest.selectors.FactorSelector`） |

## 风控规则

bootstrap 默认为所有 session 配置 `atr_trailing_stop`（multiplier=3.0, window=20）。可选规则还包括 `stop_loss`、`take_profit`、`trailing_stop`、`max_holding_bars`、`max_consecutive_rising`、`max_consecutive_falling`。详见 [配置指南](configuration.md)。

## 组合优化

bootstrap 默认启用 Riskfolio 组合优化（`MinRisk` 目标，`DRIFT_THRESHOLD` 再平衡 \(\pm10\%\) 漂移）。详见 [组合优化](portfolio.md)。

## Dashboard

默认情况下，bootstrap 会先启动 API，再自动调用：

```python
from jh_quant.dashboard import display_trading

display_trading(host=host, port=port)
```

因此用户运行 `jh-quant paper` 后不需要再手动启动 Dashboard。若只需要 API：

```bash
jh-quant paper --no-dashboard
```

## Python API

```python
from jh_quant.trading.bootstrap import TradingBootstrapConfig, build_paper_manager

config = TradingBootstrapConfig(
    template="paper-compare",
    backend="tushare",
    strategies=["rsi"],
    symbols=["688041", "688256", "688981"],
    initial_capital=100_000,
    db_path="trade_paper.db",
    show_dashboard=True,
)

manager = build_paper_manager(config)
```

专业用户可以跳过 bootstrap，直接构造 `MarketDataService`、`SessionServiceConfig` 和 `MultiSessionService`。详见 [高级自定义运行](advanced-usage.md)。
