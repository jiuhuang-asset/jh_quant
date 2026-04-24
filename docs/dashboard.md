# jh_quant.dashboard

可视化仪表盘模块，基于 PyWebView 提供交互式回测结果和因子分析展示。

- **回测可视化**: 展示交易历史、策略表现、排名对比等
- **因子可视化**: 展示因子收益时序图
- **交互式图表**: 使用 ECharts 渲染，支持日/分钟级数据

## 安装

```bash
pip install -e .
```

## 快速开始

### 回测结果可视化

```python
from jh_quant.dashboard import display_backtesting

# trading_hist: 回测交易历史 DataFrame
# perf_data: 策略表现指标 DataFrame
display_backtesting(trading_hist, perf_data)
```

### 因子收益可视化

```python
from jh_quant.dashboard import display_factors

# factor_returns: 因子收益 DataFrame
display_factors(factor_returns)
```

## 数据格式

### `trading_hist` 交易历史

| 字段 | 说明 |
|------|------|
| `symbol` | 股票代码 |
| `date` | 日期 |
| `open/high/low/close` | OHLC价格 |
| `volume` | 成交量 |
| `buy_signal` | 买入信号 |
| `sell_signal` | 卖出信号 |
| `strategy` | 策略名称 |
| `strategy_return` | 策略收益 |
| `cumulative_return` | 累计收益 |
| `drawdown` | 回撤 |

### `perf_data` 策略表现

| 字段 | 说明 |
|------|------|
| `strategy` | 策略名称 |
| `total_return` | 总收益 |
| `annualized_return` | 年化收益 |
| `sharpe_ratio` | 夏普比率 |
| `max_drawdown` | 最大回撤 |
| ... | 其他绩效指标 |

### `factor_returns` 因子收益

| 字段 | 说明 |
|------|------|
| `date` | 日期 |
| `model_name` | 模型名称 |
| `factor_name` | 因子名称 |
| `factor_return` | 因子收益 |

## 目录结构

```
dashboard/
├── __init__.py       # 主入口，导出 display_backtesting, display_factors
├── dash.py           # 可视化逻辑和 PyWebView 集成
└── front_src/        # 前端资源
    └── bt-dash/      # 回测仪表盘前端
```
