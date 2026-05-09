# 扩展开发

`jh_quant.trading` 提供了多个扩展点，允许你注入自定义实现来替代或增强内置组件。

---

## 自定义选股器

实现 `SelectionProvider` 协议，并通过 `register_selection_provider` 注册。

```python
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
from jh_quant.trading import SelectionProvider, SelectionSnapshot, register_selection_provider


# ① 定义配置模型
@dataclass
class MySelectionConfig:
    symbols: List[str] = field(default_factory=list)
    min_market_cap: float = 1e8  # 最低市值过滤


# ② 实现选股器
class MySelectionProvider(SelectionProvider):
    def __init__(self, config: MySelectionConfig):
        self._symbols = list(config.symbols)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        # 自定义选股逻辑：例如按市值过滤
        selected = [s for s in self._symbols if self._check_market_cap(s)]
        return SelectionSnapshot(
            top_selections=selected,
            bottom_selections=[],  # 做空候选（可选）
            metadata={"as_of_date": as_of_date, "filter": f"cap>{self._config.min_market_cap}"},
        )

    def _check_market_cap(self, symbol):
        # 实现你的市值查询逻辑
        return True

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


# ③ 注册
register_selection_provider(
    name="my_custom_picker",
    provider_cls=MySelectionProvider,
    config_model=MySelectionConfig,
)

# ④ 使用
config = (
    SessionServiceConfigBuilder.defaults()
    .with_selection(
        name="my_custom_picker",
        params=MySelectionConfig(symbols=["000001", "000002"]),
    )
    .build()
)
```

---

## 自定义策略

实现策略类并注册到策略注册表。

```python
from jh_quant.trading.config import register_strategy


# ① 定义策略（需实现 jh_quant.backtest.strategy 模块中的 Strategy 协议）
# 具体接口参见 jh_quant.backtest 文档

# ② 注册
register_strategy(
    name="my_strategy",
    strategy_cls=MyCustomStrategy,
    config_model=MyStrategyConfig,  # dataclass
)

# ③ 使用
config = (
    SessionServiceConfigBuilder.defaults()
    .add_strategy(name="my_strategy", weight=1.0, params=MyStrategyConfig(...))
    .build()
)
```

---

## 自定义风险规则

实现 `RiskRule` 协议并注册。

```python
from jh_quant.trading.config import register_risk_rule
from dataclasses import dataclass


# ① 定义配置
@dataclass
class MaxDrawdownRuleConfig:
    max_drawdown: float = -0.20  # 最大回撤阈值


# ② 实现规则（需实现 RiskRule 协议）
class MaxDrawdownRiskRule:
    def __init__(self, config: MaxDrawdownRuleConfig):
        self.config = config

    def evaluate(self, symbol, price_df, holdings, **kwargs):
        # 返回 True（通过）或 False（被过滤）
        return True


# ③ 注册
register_risk_rule(
    name="max_drawdown",
    rule_cls=MaxDrawdownRiskRule,
    config_model=MaxDrawdownRuleConfig,
)

# ④ 使用
config = (
    SessionServiceConfigBuilder.defaults()
    .add_risk_rule(name="max_drawdown", params=MaxDrawdownRuleConfig(max_drawdown=-0.15))
    .build()
)
```

---

## 自定义行情数据

实现 `MarketDataProvider` 抽象类。

```python
from typing import List, Dict, Set
import pandas as pd
from jh_quant.trading import MarketDataProvider
from jh_quant.trading.config import Frequency


class MyMarketDataProvider(MarketDataProvider):
    def __init__(self, api_key: str):
        super().__init__()
        self._api_key = api_key

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        # 对接你的数据源（Tushare、Wind、Bloomberg 等）
        # 返回 {"000001": 12.50, "000002": 8.30}
        pass

    def get_price_data(
        self, symbols, start_date, end_date, frequency=Frequency.DAILY
    ) -> pd.DataFrame:
        # 返回 MultiIndex DataFrame, columns=(symbol, field)
        pass

    def get_trade_calendar(self) -> Set[str]:
        # 返回交易日历集合，如 {"2025-01-02", "2025-01-03", ...}
        pass


# 使用
md_provider = MyMarketDataProvider(api_key="your-key")

engine = TradingEngine(
    oms=MockOMS(initial_capital=100_000),
    market_data_provider=md_provider,
)

manager = MultiSessionService(
    market_data_provider=md_provider,
)
```

---

## 自定义 OMS（订单管理系统）

实现 `OMS` 抽象类，对接真实券商接口。

```python
from jh_quant.trading import OMS


class BrokerOMS(OMS):
    """对接真实券商 API 的 OMS"""

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def executable_holds(self):
        # 返回 T+1 可卖的持仓
        return [...]

    def get_positions(self):
        # 从券商查询真实持仓
        pass

    def get_available_balance(self) -> float:
        # 查询可用资金
        pass

    def signal_buy(self, order):
        # 向券商下单买入
        pass

    def signal_sell(self, order):
        # 向券商下单卖出
        pass

    def update_position_market_value(self, price_dict):
        # 按最新价更新持仓市值
        pass
```

---

## 自定义仓位计算器

实现 `PositionSizer` 协议。

```python
from dataclasses import dataclass
import pandas as pd
from jh_quant.trading import PositionSizer


@dataclass
class KellyPositionSizer:
    """凯利公式仓位计算"""
    win_prob: float = 0.55
    win_loss_ratio: float = 1.5
    max_position_weight: float = 0.20

    def calculate(
        self, candidates: pd.DataFrame, price_df: pd.DataFrame,
        latest_prices: pd.Series, available_balance: float, total_equity: float,
    ) -> pd.DataFrame:
        kelly_fraction = self.win_prob - (1 - self.win_prob) / self.win_loss_ratio
        weight = min(kelly_fraction, self.max_position_weight)

        candidates = candidates.copy()
        candidates["target_amount"] = total_equity * weight
        candidates["target_shares"] = (
            candidates["target_amount"] / candidates["target_price"] // 100 * 100
        ).astype(int)
        return candidates
```

直接实现 `PositionSizer` 协议即可（无需注册），通过 `TradingEngine` 构造或 `configure_position_sizer` 注入：

```python
engine = TradingEngine(
    oms=MockOMS(100_000),
    position_sizer=KellyPositionSizer(win_prob=0.55),
)

# 或运行时替换
engine.configure_position_sizer(KellyPositionSizer(win_prob=0.60))
```

---

## 自定义组合优化器

`PortfolioOptimizerDefinition` 注册新优化器：

```python
from jh_quant.trading.config.portfolio import (
    register_portfolio_optimizer,
    PortfolioOptimizerDefinition,
)

register_portfolio_optimizer(
    name="custom_hierarchical_rp",
    definition=PortfolioOptimizerDefinition(
        name="custom_hierarchical_rp",
        params_schema={"linkage": "ward", "max_clusters": 5},
        optional_dependency=None,
        notes="自定义层次风险平价",
    ),
)
```

---

## 查看已注册的扩展

```python
from jh_quant.trading.config import (
    list_strategy_definitions,
    list_risk_rule_definitions,
    list_selection_definitions,
)
from jh_quant.trading.config.portfolio import list_portfolio_optimizer_definitions

print("策略:", [s.name for s in list_strategy_definitions()])
print("风险规则:", [r.name for r in list_risk_rule_definitions()])
print("选股器:", [p.name for p in list_selection_definitions()])
print("优化器:", [o.name for o in list_portfolio_optimizer_definitions()])
```
