# 快速开始

## 模拟盘

统一 CLI 入口 `jh-quant paper`：

```bash
jh-quant paper
```

默认使用 `paper-compare` 模板，自动创建两个并行模拟场景：

- `paper-turtle`：海龟策略基准场景。
- `paper-momentum`：默认用户策略场景。

API 启动后会自动打开 trading Dashboard。只想启动 API 时：

```bash
jh-quant paper --no-dashboard
```

查看完整参数说明：

```bash
jh-quant paper --help
```

常用示例：

```bash
jh-quant paper --strategy turtle --backend tushare
jh-quant paper --strategy rsi --symbols 688041,688256,688981
jh-quant paper --strategy turtle,momentum --no-dashboard
```

默认行为：

- backend: `tushare`
- template: `paper-compare`
- strategy: `momentum`
- 默认股票池: 半导体 / AI 芯片链观察池
- API 地址: `http://127.0.0.1:8000/docs`
- 初始资金: 100,000 元

## 实盘

```bash
jh-quant live
```

运行前需要设置 MiniQMT / xtquant broker 环境变量：

```bash
set MINIQMT_USERDATA_DIR=D:\path\to\userdata
set MINIQMT_STOCK_ACCOUNT=你的资金账号
```

查看完整参数说明：

```bash
jh-quant live --help
```

常用示例：

```bash
jh-quant live --strategy turtle
jh-quant live --backend xquant --strategy turtle,momentum
jh-quant live --no-dashboard
```

> **注意**: `live` 模式没有 `--initial-capital`（资金以 broker 查询为准），不支持回填（始终保持 `realtime` 时钟）。

## 数据同步

将本地 SQLite 交易数据增量同步到远程 Postgres/Neon：

```bash
jh-quant sync --from trade_paper.db
```

详见 [数据同步模块](#)（待补充独立文档）。

## 策略参数

`--strategy` 接收一个或多个注册策略名，多个策略用英文逗号分隔：

```bash
--strategy turtle,momentum
```

当前注册策略会在 `--help` 中完整列出，共 11 种：

```text
bollinger_bands, breakout, buy_and_hold, dual_thrust, mean_reversion,
momentum, moving_average_crossover, rsi, turtle, volume_divergence, volume_trend
```

`paper-compare` 模板会自动把 `turtle` 作为保底 scenario。如果你传入 `--strategy rsi`，最终会创建 `paper-turtle` 和 `paper-rsi` 两个模拟场景。
