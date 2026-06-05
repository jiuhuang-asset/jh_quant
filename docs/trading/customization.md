# 扩展开发

## 自定义行情源

自定义行情源需要实现三个常用方法：

```python
class MyMarketDataProvider:
    def get_price_data(self, symbols, start_date, end_date, frequency=None):
        return price_df

    def get_latest_prices(self, symbols, as_of_date=None):
        return {"600519": 1600.0}

    def get_trade_calendar(self, start_date="2020-01-01", end_date=None):
        return {"2026-06-05"}
```

`price_df` 必须能转换为 trading price schema。推荐直接返回：

```text
symbol, date, open, high, low, close, volume, amount, price
```

如果返回 TuShare 风格字段，例如 `ts_code/trade_date/vol`，内置 adapter 会自动转换。

## 自定义选股器

```python
from dataclasses import dataclass
from jh_quant.trading import SelectionSnapshot, register_selection_provider


@dataclass
class MySelectionConfig:
    symbols: list[str]


class MySelectionProvider:
    def __init__(self, config: MySelectionConfig):
        self.config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(top_selections=list(self.config.symbols))


register_selection_provider(
    name="my_selection",
    provider_cls=MySelectionProvider,
    config_model=MySelectionConfig,
)
```

## 自定义入口

可以复用 bootstrap，只覆盖你关心的配置：

```python
from jh_quant.trading import run_trading_app
from jh_quant.trading.bootstrap import TradingBootstrapConfig, build_paper_manager

config = TradingBootstrapConfig(
    template="paper-basic",
    backend="tushare",
    symbols=["600519", "000001"],
    initial_capital=200_000,
)

manager = build_paper_manager(config)
run_trading_app(manager=manager, host="127.0.0.1", port=8000)
```

专业用户也可以跳过 bootstrap，直接创建 `MarketDataService`、`SessionServiceConfig` 和 `MultiSessionService`。
