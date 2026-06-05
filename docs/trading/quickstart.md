# 快速开始

## 模拟盘

根目录提供简洁 CLI 入口：

```bash
uv run python run_paper.py
```

默认会启动两个并行模拟场景：

- `paper-turtle`：海龟策略，作为保底基准。
- `paper-momentum`：默认用户策略场景。

API 启动后会自动打开 trading Dashboard。只想启动 API 时可以加：

```bash
uv run python run_paper.py --no-dashboard
```

查看完整参数说明：

```bash
uv run python run_paper.py --help
```

常用示例：

```bash
uv run python run_paper.py --strategy turtle --backend tushare
uv run python run_paper.py --strategy rsi --symbols 688041,688256,688981
uv run python run_paper.py --strategy turtle,momentum --no-dashboard
```

默认行为：

- backend: `tushare`
- 历史行情: `TuShareMarketDataService`
- 当天实时合并: 暂用 `AkShareRealtimeQuoteProvider`
- template: `paper-compare`
- strategy: `turtle,momentum`
- 默认股票池: 半导体 / AI 芯片链观察池
- API 地址: `http://127.0.0.1:8000/docs`

## 实盘

实盘入口：

```bash
uv run python run_live.py
```

运行前需要设置 MiniQMT / xtquant broker 环境变量：

```bash
set MINIQMT_USERDATA_DIR=D:\path\to\userdata
set MINIQMT_STOCK_ACCOUNT=你的资金账号
```

查看完整参数说明：

```bash
uv run python run_live.py --help
```

常用示例：

```bash
uv run python run_live.py --strategy turtle
uv run python run_live.py --backend xquant --strategy turtle,momentum
uv run python run_live.py --no-dashboard
```

## 策略参数

`--strategy` 接收一个或多个注册策略名，多个策略用英文逗号分隔：

```bash
--strategy turtle,momentum
```

当前注册策略会在 `--help` 中完整列出，例如：

```text
bollinger_bands, breakout, buy_and_hold, dual_thrust, mean_reversion,
momentum, moving_average_crossover, rsi, turtle, volume_divergence, volume_trend
```

`paper-compare` 模板会自动把 `turtle` 作为保底 scenario。如果你传入 `--strategy rsi`，最终会创建 `paper-turtle` 和 `paper-rsi` 两个模拟场景。
