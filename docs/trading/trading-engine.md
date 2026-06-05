# TradingEngine

`TradingEngine` 是交易执行层核心，负责获取价格数据、聚合策略信号、生成候选、计算仓位、应用风控规则并执行订单。

## 构造

```python
from jh_quant.trading import PaperBroker, TradingEngine, create_market_data_service

market_data = create_market_data_service(
    backend="tushare",
    default_symbols=["600519", "000001"],
)

engine = TradingEngine(
    broker=PaperBroker(initial_capital=100_000),
    market_data_provider=market_data,
)
```

`market_data_provider` 可以是内置 `TuShareMarketDataService`、`AkShareMarketDataService`、`XtQuantMarketDataService`，也可以是用户自定义 provider。自定义 provider 只需要保证 `get_price_data()` 返回的数据能转换为 trading price schema。

## 价格数据

```python
price = engine.get_price_data(
    symbols=["600519", "000001"],
    start_date="2025-01-01",
    end_date="2025-06-01",
)
```

返回 DataFrame 至少包含：

```text
symbol, date, open, high, low, close
```

常用可选字段：

```text
volume, amount, price, pct_chg, chg, turnover_rate, amplitude
```

`TradingEngine.get_price_data()` 会对 provider 输出进行最终 schema 校验和标准化，因此策略、风控和仓位计算不需要关心数据源来自 TuShare、AkShare 还是 xtquant。

## 常用方法

- `build_price_matrix(symbols, start_date, end_date)`：生成 close price matrix。
- `build_return_matrix(symbols, start_date, end_date)`：生成收益率矩阵。
- `aggregate_signals(price, frequency, signal_type)`：聚合策略信号。
- `get_long_candidates(...)`：生成买入候选。
- `get_short_candidates(...)`：生成卖出候选。
- `execute_cycle(...)`：执行一个完整交易周期。

## 数据源替换

自定义 provider 示例：

```python
class MyMarketDataProvider:
    def get_price_data(self, symbols, start_date, end_date, frequency=None):
        return my_dataframe  # 必须能转换到 trading price schema

    def get_latest_prices(self, symbols, as_of_date=None):
        return {"600519": 1600.0}

    def get_trade_calendar(self, start_date="2020-01-01", end_date=None):
        return {"2026-06-05"}
```

如果 provider 返回 TuShare 风格字段，例如 `ts_code/trade_date/vol`，adapter 会自动映射；如果返回完全自定义字段，请在 provider 内部先转换为统一字段。
