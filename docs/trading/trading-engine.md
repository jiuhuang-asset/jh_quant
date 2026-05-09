# TradingEngine

`TradingEngine` 是信号聚合与交易执行的核心引擎，负责汇总多策略信号、计算仓位、过滤风险规则并执行买卖订单。

## 构造

```python
from jh_quant.trading import TradingEngine, MockOMS, JHMarketDataProvider, ATRPositionSizer

engine = TradingEngine(
    oms=MockOMS(initial_capital=100_000),
    market_data_provider=JHMarketDataProvider(),
    position_sizer=ATRPositionSizer(risk_unit=0.01, max_position_weight=0.2),
    strict_mode=True,
    risk_rules=[...],
)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `oms` | `OMS` | 订单管理系统，通常使用 `MockOMS` |
| `market_data_provider` | `MarketDataProvider` | 行情数据提供者，默认 `JHMarketDataProvider` |
| `position_sizer` | `PositionSizer` | 仓位计算器，默认 `ATRPositionSizer` |
| `strict_mode` | `bool` | 是否严格校验价格数据新鲜度（过期数据拒绝执行） |
| `risk_rules` | `List[RiskRule]` | 风险规则列表，可选在构造时直接传入 |

---

## 策略管理

### `add_strategy(strategy, name, weight=1.0)`

添加策略到引擎。

```python
from jh_quant.backtest.strategy import MomentumStrategy

engine.add_strategy(MomentumStrategy(window=20), name="momentum", weight=1.0)
```

### `replace_strategies(strategies)`

批量替换所有策略。

```python
engine.replace_strategies([
    {"strategy": MomentumStrategy(window=20), "name": "momentum", "weight": 0.6},
    {"strategy": MeanReversionStrategy(window=10), "name": "mean_rev", "weight": 0.4},
])
```

---

## 行情数据

### `get_price_data(symbols, start_date=None, end_date=None, frequency=DAILY) -> DataFrame`

获取历史 OHLCV 数据。

```python
prices = engine.get_price_data(
    symbols=["000001", "000002"],
    start_date="2025-01-01",
    end_date="2025-06-01",
    frequency=Frequency.DAILY,
)
# 返回 MultiIndex DataFrame: columns = (symbol, field), index = 日期
```

### `get_latest_prices(symbols=None) -> Series`

获取最新收盘价。

```python
latest = engine.get_latest_prices(symbols=["000001", "000002"])
# 返回 Series，index 为 symbol
```

### `build_return_matrix(symbols, start_date, end_date, frequency=None, price=None) -> DataFrame`

构建收益率矩阵（对数收益率），用于组合优化。

```python
returns = engine.build_return_matrix(
    symbols=["000001", "000002"],
    start_date="2024-01-01",
    end_date="2025-06-01",
)
```

### `build_price_matrix(symbols, start_date, end_date, frequency=None, price=None) -> DataFrame`

构建收盘价矩阵。

### `validate_price_freshness(price, frequency=DAILY, reference_time=None, strict_mode=None) -> bool`

校验价格数据是否在允许的时间窗口内（避免使用过期数据）。

---

## 信号聚合

### `aggregate_signals(price, frequency=DAILY, signal_type="buy") -> DataFrame`

聚合所有已注册策略的信号，按权重加权求和。

```python
buy_signals = engine.aggregate_signals(prices, frequency=Frequency.DAILY, signal_type="buy")
# 返回加权聚合后的信号 DataFrame
```

### `aggregate_buy_signals(price, frequency=DAILY) -> DataFrame`

聚合买入信号的快捷方法。

### `aggregate_sell_signals(price, frequency=DAILY) -> DataFrame`

聚合卖出信号的快捷方法。

---

## 候选生成

### `get_long_candidates(start_date=None, end_date=None, max_candidates=5, price=None, frequency=DAILY, reference_time=None) -> DataFrame`

生成买入候选。内部流程：

1. 聚合策略买入信号
2. 应用风险规则过滤
3. 按信号得分排序，取前 `max_candidates` 名
4. 计算目标仓位

```python
candidates = engine.get_long_candidates(
    start_date="2025-06-01",
    end_date="2025-06-01",
    max_candidates=5,
)
# DataFrame 字段：symbol, score, target_shares, target_amount 等
```

### `get_short_candidates(start_date=None, end_date=None, price=None, frequency=DAILY, reference_time=None) -> DataFrame`

生成卖出候选，聚合卖出信号并过滤风险规则。

---

## 仓位计算

### `calculate_position_size(candidates, price_df, latest_prices=None) -> DataFrame`

为候选标的计算具体仓位，使用构造时注入的 `PositionSizer`。

```python
sized = engine.calculate_position_size(candidates, price_df, latest_prices)
# DataFrame 追加字段：target_shares, target_amount 等
```

---

## 交易执行

### `execute_long(orders, slippage=0.0) -> List[Trade]`

执行买入订单。会校验资金余额，不足时自动降量。

### `execute_short(orders, slippage=0.0) -> List[Trade]`

执行卖出订单。会校验持仓数量，不足时自动降量。

### `close_all_positions(slippage=0.0) -> List[Trade]`

一键平仓所有当前持仓（卖出所有可卖份额）。

### `execute_cycle(top_selections, price_start, cycle_date, frequency=DAILY, max_candidates=10, price_slippage=0.0) -> tuple[List[Trade], List[Trade], DataFrame, DataFrame]`

执行一个完整的交易周期：

1. 获取价格数据
2. 生成卖出候选 → 执行卖出
3. 生成买入候选 → 执行买入
4. 返回 `(buy_trades, sell_trades, buy_candidates, sell_candidates)`

---

## 动态配置

### `configure_risk_rules(risk_rules)`

动态更新风险规则列表。

### `configure_position_sizer(sizer)`

动态替换仓位计算器。

```python
from jh_quant.trading import FixedWeightPositionSizer

engine.configure_position_sizer(FixedWeightPositionSizer(max_stocks=10))
```

---

## PositionSizer

### ATRPositionSizer

基于 ATR（平均真实波幅）的波动率对齐仓位计算。

```python
from jh_quant.trading import ATRPositionSizer

sizer = ATRPositionSizer(
    risk_unit=0.01,            # 单笔风险敞口（占总权益的百分比）
    max_position_weight=0.2,   # 单个标的最大仓位（占总权益的百分比）
)
```

核心逻辑：`仓位数 = (总权益 × risk_unit) / (ATR × 乘数)`，并受 `max_position_weight` 约束和 A 股 100 股取整。

### FixedWeightPositionSizer

等权仓位计算。

```python
from jh_quant.trading import FixedWeightPositionSizer

sizer = FixedWeightPositionSizer(max_stocks=10)
# 可用资金平均分配给前 max_stocks 个候选标的
```

---

## 直接使用引擎（不使用服务层）

如果不使用 REST API，可以直接构造引擎编程式调用：

```python
from jh_quant.trading import TradingEngine, MockOMS, JHMarketDataProvider

oms = MockOMS(initial_capital=100_000)
engine = TradingEngine(
    oms=oms,
    market_data_provider=JHMarketDataProvider(),
)

# 添加策略
from jh_quant.backtest.strategy import MomentumStrategy
engine.add_strategy(MomentumStrategy(window=20), name="momentum")

# 获取行情
prices = engine.get_price_data(["000001"], "2025-01-01", "2025-06-01")

# 生成买入候选
candidates = engine.get_long_candidates(
    start_date="2025-06-01",
    end_date="2025-06-01",
    max_candidates=5,
    price=prices,
)

# 查看持仓
positions = oms.get_positions()
print(f"持仓数: {positions.total}, 可用资金: {positions.available_balance}")
```
