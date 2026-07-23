# 因子计算模块 (factors)

## 快速开始

```python
from jh_quant.factors import calculate_factor_returns, load_ts_factor_inputs

inputs = load_ts_factor_inputs(start_date="2020-01-01", end_date="2024-12-31")
ff3 = calculate_factor_returns("ff3", **inputs)
```

输出为 DataFrame，index 为 date，columns 为因子名：

```
              mkt       smb       hml
date
2020-01-02  0.0123   -0.0045    0.0087
2020-01-03 -0.0056    0.0023   -0.0012
```

## 三层入口

| 入口 | 适用场景 |
|------|---------|
| `calculate_factor_returns()` | 最简洁，一次性计算因子收益率 |
| `FactorEngine` | 需要复用实例、批量计算多个模型 |
| `GeneralFactorCalculator` | 已有股票收益率和基本面数据，只需计算逻辑 |

### 方式一：便捷函数（推荐入门）

```python
from jh_quant.factors import calculate_factor_returns, load_ts_factor_inputs

inputs = load_ts_factor_inputs(start_date="2020-01-01", end_date="2024-12-31")
ff3 = calculate_factor_returns("ff3", **inputs, method="simple")

# 一次性计算所有模型
all_factors = calculate_factor_returns("all", **inputs)
# 返回 Dict[FactorType, DataFrame]
```

### 方式二：FactorEngine（推荐进阶）

```python
from jh_quant.factors import FactorEngine, FactorType, CalculationMethod

engine = FactorEngine()

# 单模型
ff5 = engine.calculate_factor_returns(
    factor_type=FactorType.FF5,
    method=CalculationMethod.CLASSIC,
    n_jobs=4,
    use_polars=True,
    **inputs,
)

# 批量
results = engine.calculate_all_factors(
    factor_types=[FactorType.FF3, FactorType.CARHART, FactorType.DHS],
    method=CalculationMethod.SIMPLE,
    **inputs,
)
```

### 方式三：便捷暴露函数

```python
from jh_quant.factors import calculate_exposures

exposures = calculate_exposures(
    stock_returns=my_stock_returns,
    factor_returns=ff3,
    period='M',
)
```

## 数据准备

因子核心不直接拉取 Tushare 或 AkShare 数据。需先准备符合 schema 的 DataFrame。

推荐使用 `load_ts_factor_inputs()`：

```python
inputs = load_ts_factor_inputs(
    start_date="2020-01-01",
    end_date="2024-12-31",
    period="M",             # "M" 月频 / "D" 日频
    price_adjust="qfq",     # "qfq" 前复权 / "hfq" 后复权 / "none"
    lag_features=True,      # 将特征滞后一收益期，避免 look-ahead bias
)
```

自行准备数据至少需要：

| 输入 | 必需列 | 说明 |
|------|--------|------|
| `stock_returns` | `symbol`, `date`, `return` | 股票收益率 |
| `market_cap` | `symbol`, `date`, `mkt_cap` | 已按可用时间对齐的市值 |
| `fundamentals` | `{field: DataFrame}` | 因子特征字段 |
| 财务字段 | `symbol`, `date`, `ann_date`, `<field>` | `ann_date` 是公告日/可获得日 |

财务字段缺少 `ann_date` 会被 schema 拦截。

### 使用自定义数据

```python
from jh_quant.factors.factors.general import GeneralFactorCalculator
from jh_quant.factors.config import FactorType, CalculationMethod

calc = GeneralFactorCalculator(
    factor_type=FactorType.FF3,
    method=CalculationMethod.SIMPLE,
)

factor_returns = calc.calculate(
    stock_returns=my_stock_returns,
    market_cap=my_market_cap,
    fundamentals={'bm': my_bm},
)
```

## 11 种因子模型

| 字符串简写 | FactorType | 因子组成 | 学术来源 |
|-----------|-----------|---------|---------|
| `capm` | `CAPM` | mkt | Sharpe (1964) |
| `ff3` | `FF3` | mkt, smb, hml | Fama-French (1993) |
| `ff5` | `FF5` | mkt, smb, hml, rmw, cma | Fama-French (2015) |
| `carhart` | `CARHART` | mkt, smb, hml, umd | Carhart (1997) |
| `novy_marx` | `NOVY_MARX` | mkt, hml_adj, umd, gp_a | Novy-Marx (2013) |
| `hxz` | `HOU_XUE_ZHANG` | mkt, me, ia, roe | Hou-Xue-Zhang (2015) |
| `dhs` | `DHS` | mkt, pead, fin | Daniel-Hirshleifer-Sun (2020) |
| `ch3` | `CH3` | mkt, smb, vmg | 汪昌云等 |
| `sy4` | `SY4` | mkt, smb, mgmt, perf | Stambaugh-Yuan (2017) |
| `reversal` | `REVERSAL` | mkt, smb, rev | A 股短期反转 |
| `low_vol` | `LOW_VOL` | mkt, smb, ivol | 低波动异象 |

### 因子含义速查

| 因子名 | 全称 | 含义 |
|--------|------|------|
| `mkt` | Market | 市场超额收益 |
| `smb` | Small Minus Big | 小市值 - 大市值 |
| `hml` | High Minus Low | 高 BM - 低 BM（价值） |
| `rmw` | Robust Minus Weak | 高盈利 - 低盈利 |
| `cma` | Conservative Minus Aggressive | 低投资 - 高投资 |
| `umd` | Up Minus Down | 高动量 - 低动量 |
| `me` | Market Equity | 规模因子（等同 SMB） |
| `ia` | Investment-to-Asset | 投资因子 |
| `roe` | Return on Equity | 盈利因子 |
| `pead` | Post-Earnings Announcement Drift | 盈余公告后漂移 |
| `fin` | Financing | 融资因子（净股票发行） |
| `vmg` | Value Minus Growth | 剔壳调整后的价值因子 |
| `mgmt` | Management | 管理因子 |
| `perf` | Performance | 绩效因子 |
| `rev` | Reversal | 短期反转 |
| `ivol` | Idiosyncratic Volatility | 特质波动率 |

## 参数速查

### CalculationMethod

| 值 | 说明 |
|----|------|
| `simple` / `CalculationMethod.SIMPLE` | 简化方法（默认），等权+中位数分组，计算快 |
| `classic` / `CalculationMethod.CLASSIC` | 经典方法，市值加权+分位数分组，接近学术论文 |

### TimePeriod

| 值 | 说明 |
|----|------|
| `'M'` / `TimePeriod.MONTHLY` | 月度因子 |
| `'D'` / `TimePeriod.DAILY` | 日度因子 |

### 常用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `n_jobs` | CPU 核数（最多 4） | 并行任务数 |
| `use_polars` | `True` | 是否用 Polars 加速 |
| `symbols` | `None`（全部 A 股） | 限定股票范围 |
| `verbose` | `True` | 是否打印进度信息 |

### load_ts_factor_inputs 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period` | `"M"` | 月频；`"D"` 为日频转月末收益 |
| `price_adjust` | `"qfq"` | 前复权；可选 `"hfq"` 或 `"none"` |
| `lag_features` | `True` | 将市值、BM、动量等特征滞后一收益期 |
| `include_proxy_fundamentals` | `False` | 仅用于 smoke test，不建议正式研究 |

## Point-in-Time (PIT) 原则

- 市值、BM、动量等市场特征应先滞后一收益期，避免用同月特征解释同月收益
- 财务字段必须包含 `ann_date`，按 `ann_date <= return_date` 匹配到股票收益
- 财务字段选取最近可用数据，默认不超过 6 个月

## 常见开发任务

- **新增因子模型**：在 `factors/factors/` 下添加新模块，注册到 `FactorType` 和 `FactorEngine`
- **修改计算方法**：`SIMPLE` 和 `CLASSIC` 在各自的 FactorCalculator 子类中实现
- **防 Look-Ahead Bias**：严格按 PIT 原则匹配数据
