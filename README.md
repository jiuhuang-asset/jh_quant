# JH_QUANT

![banner](assets/banner_sm.png)

量化交易研究与执行平台。支持：**免费数据获取**、**回测**、**因子计算**、**模拟交易**、**组合优化**、**可视化仪表盘**。

- **官网**: https://jiuhuang.xyz
- **文档**: https://doc.jiuhuang.xyz

## 快速开始

### 安装

```bash
pip install jh_quant
```

### 数据获取

```python
import os
from jh_quant.data import JHData, DataTypes

jh = JHData(api_key=os.getenv("JIUHUANG_API_KEY"))
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,  # akshare A 股日线前复权
    symbol="000001",
    start="2025-01-01",
    end="2025-12-10",
)
```

#### 数据兼容
兼容 `akshare` 调用风格：

```python
from jh_quant.data.data_providers import akshare as ak

df = ak.stock_zh_a_hist(
    symbol="000001",
    period="daily",
    start_date="20240101",
    end_date="20241231",
    adjust="qfq",
)
```

兼容 `tushare` 调用风格：

```python
from jh_quant.data.data_providers import tushare as ts

df = ts.daily(
    ts_code="000001.SZ",
    start_date="20240101",
    end_date="20241231",
)

pro_df = ts.pro.pro_bar(
    ts_code="000001.SZ",
    start_date="20240101",
    end_date="20241231",
    asset="E",
    freq="D",
)
```

### 策略回测

```python
from jh_quant.data import JHData, DataTypes
from jh_quant.backtest import (
    backtest,
    StrategyTurtle,
    StrategyMovingAverageCrossover,
    StrategyBuyAndHold,
)
from jh_quant.dashboard import display_backtesting

# 1. 准备数据
jh = JHData()
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519,300750",
    start="2025-01-01",
    end="2026-05-07",
)
stock_info = jh.get_data(DataTypes.AK_STOCK_INDIVIDUAL_INFO_EM)

# 2. 定义策略
strategies = {
    "海龟策略": StrategyTurtle(entry_window=20, exit_window=10),
    "均线交叉": StrategyMovingAverageCrossover(short_window=12, long_window=24),
    "买入持有": StrategyBuyAndHold(),
}

# 3. 执行回测
trading_hist, backtest_perf = backtest(
    strategies=strategies,
    price_data=stock_price,
    stock_info=stock_info,
)

display_backtesting(trading_hist, backtest_perf)
```

**回测仪表盘预览**

| 策略对比 | 策略分布 |
| -------- | -------- |
| ![策略对比](assets/strat_compare_resized.png) | ![策略分布](assets/strat_dist_resized.png) |

| 交易历史 | 策略排名 |
| -------- | -------- |
| ![交易历史](assets/trading_history_resized.png) | ![策略排名](assets/strat_ranking_resized.png) |

### 实时模拟交易

**jh_quant** 支持同时开启多个模拟交易会话，每个会话对应一个模拟账户。下面是示例运行方式：

```bash
python run_paper.py
```

`run_paper.py` 的完整代码见仓库根目录的 [run_paper.py](run_paper.py)。

在回填模式下（可通过 `enable_backfill=False` 关闭），系统会先完成历史交易回放，并在本地启动服务，默认端口为 `8000`。

**打开控制台仪表盘**

本地服务启动后，可以通过如下代码打开控制台仪表盘：

```python
from jh_quant.dashboard import display_trading

# 如果你修改了 run_paper.py 中的端口，需要显式传入 port 参数
display_trading()
```

![JH_QUANT Dashboard Demo](assets/dash_video.gif)


## 模块说明

| 模块 | 说明 | 文档 |
| ---- | ---- | ---- |
| [data](docs/data/index.md) | 多种数据获取，兼容 `akshare` 和 `tushare` 的数据类型与调用风格 | [README](docs/data/index.md) |
| [trading](docs/trading/index.md) | 交易运行层，支持模拟交易、交易会话编排和组合执行 | [README](docs/trading/index.md) |
| [backtest](docs/backtest/index.md) | 回测引擎，支持快速策略验证和多种内置策略 | [README](docs/backtest/index.md) |
| [factors](docs/factors/index.md) | 因子计算与暴露分析，内置多种因子模型 | [README](docs/factors/index.md) |
| `dashboard` | PyWebView 可视化仪表盘 | - |

## License

This project is licensed under the AGPL-3.0 License. See [LICENSE](LICENSE) for details.
