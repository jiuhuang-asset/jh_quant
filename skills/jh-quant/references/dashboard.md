# 可视化仪表盘模块 (dashboard)

## 回测仪表盘

```python
from jh_quant.dashboard import display_backtesting

display_backtesting(trading_history, backtest_perf)
```

包含四个视图：
- **策略对比**：各策略净值曲线叠加
- **策略分布**：各策略收益分布（箱线/小提琴）
- **交易历史**：买卖点标注的 K 线图
- **策略排名**：按收益/夏普/回撤等指标排名

## 交易仪表盘

```python
from jh_quant.dashboard import display_trading

display_trading(host="127.0.0.1", port=8000)
```

实时监控交易运行状态。

## Bootstrap 集成

Bootstrap 默认自动打开仪表盘：

```bash
jh-quant paper      # 自动打开 trading dashboard
jh-quant paper --no-dashboard    # 仅启动 API
```

## 手动后台启动

如果不使用 bootstrap，可以用后台线程启动 API 再打开 Dashboard：

```python
import threading
import time
from jh_quant.dashboard import display_trading
from jh_quant.trading import run_trading_app

api_thread = threading.Thread(
    target=run_trading_app,
    kwargs={"manager": manager, "host": "127.0.0.1", "port": 8000},
    daemon=True,
)
api_thread.start()
time.sleep(1.5)

display_trading(host="127.0.0.1", port=8000)
```

## 技术栈

- 基于 PyWebView + HTML/JS 前端
- 定时从 API 拉取数据刷新

## 常见开发任务

- **新增回测图表**：修改 `dashboard/` 下对应 HTML/JS 模板
- **Dashboard 刷新频率**：通过 `--dashboard-refresh-ms` 参数配置（默认 15000ms）
