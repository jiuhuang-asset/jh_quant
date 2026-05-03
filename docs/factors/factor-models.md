# 因子模型介绍

框架支持 11 种因子模型，覆盖从经典 CAPM 到 A 股特定异象模型。每种模型的核心差异在于**包含哪些因子**以及**需要哪些基本面数据**。

## 模型总览

| 模型 | 因子数量 | 核心因子 | 学术来源 |
|------|---------|---------|---------|
| [CAPM](#capm) | 1 | mkt | Sharpe (1964) |
| [FF3](#ff3) | 3 | mkt, smb, hml | Fama & French (1993) |
| [FF5](#ff5) | 5 | mkt, smb, hml, rmw, cma | Fama & French (2015) |
| [Carhart](#carhart) | 4 | mkt, smb, hml, umd | Carhart (1997) |
| [Novy-Marx](#novy-marx) | 4 | mkt, hml_adj, umd, gp_a | Novy-Marx (2013) |
| [HXZ (q-factor)](#hou-xue-zhang) | 4 | mkt, me, ia, roe | Hou, Xue & Zhang (2015) |
| [DHS](#dhs) | 3 | mkt, pead, fin | Daniel, Hirshleifer & Sun (2020) |
| [CH3](#ch3) | 3 | mkt, smb, vmg | 汪昌云等 |
| [SY4](#sy4) | 4 | mkt, smb, mgmt, perf | Stambaugh & Yuan (2017) |
| [Reversal](#reversal) | 3 | mkt, smb, rev | A 股短期反转异象 |
| [Low Vol](#low-vol) | 3 | mkt, smb, ivol | 低波动异象 |

## 各模型详解

### CAPM

```
因子: [mkt]
CAPM 单因子模型。因子收益率即为市场超额收益率 (R_m - R_f)。
```

**所需数据**：仅需市场超额收益率数据。

```python
from jh_quant.factors import FactorEngine, FactorType

engine = FactorEngine()
capm = engine.calculate_factor_returns(factor_type=FactorType.CAPM, period='M')

# capm 仅有一列: mkt（市场超额收益）
print(capm.columns)  # Index(['mkt'])
```

### FF3

```
因子: [mkt, smb, hml]
Fama-French 三因子模型，市场 + 规模 + 价值。
```

| 因子 | 全称 | 含义 |
|------|------|------|
| `mkt` | Market | 市场超额收益 |
| `smb` | Small Minus Big | 小市值股票收益 - 大市值股票收益 |
| `hml` | High Minus Low | 高账面市值比 (BM) - 低账面市值比 |

**所需数据**：`mkt_cap`、`bm`

```python
ff3 = engine.calculate_factor_returns(factor_type=FactorType.FF3)
print(ff3.columns)  # Index(['mkt', 'smb', 'hml'])
```

### FF5

```
因子: [mkt, smb, hml, rmw, cma]
Fama-French 五因子模型，在 FF3 基础上增加盈利和投资两个因子。
```

| 因子 | 全称 | 含义 |
|------|------|------|
| `mkt` | Market | 市场超额收益 |
| `smb` | Small Minus Big | 规模因子 |
| `hml` | High Minus Low | 价值因子 |
| `rmw` | Robust Minus Weak | 高盈利 - 低盈利（基于 OP） |
| `cma` | Conservative Minus Aggressive | 低投资 - 高投资 |

**所需数据**：`mkt_cap`、`bm`、`op`、`asset_growth`

```python
ff5 = engine.calculate_factor_returns(factor_type=FactorType.FF5)
# 包含 5 个因子: mkt, smb, hml, rmw, cma
```

### Carhart

```
因子: [mkt, smb, hml, umd]
Carhart 四因子模型，在 FF3 基础上增加动量因子。
```

| 因子 | 全称 | 含义 |
|------|------|------|
| `mkt` | Market | 市场超额收益 |
| `smb` | Small Minus Big | 规模因子 |
| `hml` | High Minus Low | 价值因子 |
| `umd` | Up Minus Down | 高动量 (赢家) - 低动量 (输家) |

**所需数据**：`mkt_cap`、`bm`、`momentum`

```python
carhart = engine.calculate_factor_returns(factor_type=FactorType.CARHART)
# 包含 4 个因子: mkt, smb, hml, umd
```

### Novy-Marx

```
因子: [mkt, hml_adj, umd, gp_a]
Novy-Marx 四因子模型。核心创新：用毛利/资产 (GP/A) 替代传统价值因子中的 BM。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `hml_adj` | 行业调整后的价值因子（BM - 行业中位数 BM） |
| `umd` | 动量因子 |
| `gp_a` | 毛利/资产 (Gross Profit / Assets) 盈利因子 |

**所需数据**：`mkt_cap`、`bm`、`momentum`、`gross_profit`、`industry`

```python
novy_marx = engine.calculate_factor_returns(factor_type=FactorType.NOVY_MARX)
# 包含 4 个因子: mkt, hml_adj, umd, gp_a
```

### Hou-Xue-Zhang (q-factor)

```
因子: [mkt, me, ia, roe]
Hou-Xue-Zhang q-factor 模型。基于投资 q 理论，用投资和盈利解释股票收益。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `me` | 规模因子 (Market Equity，等同 SMB) |
| `ia` | 投资因子 (Investment-to-Asset)，低投资 - 高投资 |
| `roe` | 盈利因子 (ROE)，高盈利 - 低盈利 |

**所需数据**：`mkt_cap`、`asset_growth`、`roe_quarterly`

```python
hxz = engine.calculate_factor_returns(factor_type=FactorType.HOU_XUE_ZHANG)
# 包含 4 个因子: mkt, me, ia, roe
```

### DHS

```
因子: [mkt, pead, fin]
Daniel-Hirshleifer-Sun 行为三因子模型。以盈余公告后漂移和融资行为作为定价因子。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `pead` | 盈余公告后漂移 (Post-Earnings Announcement Drift) |
| `fin` | 融资因子（过去 1 年净股票发行） |

**所需数据**：`mkt_cap`、`sud`（标准未预期盈余）、`net_share_issuance`

```python
dhs = engine.calculate_factor_returns(factor_type=FactorType.DHS)
# 包含 3 个因子: mkt, pead, fin
```

### CH3

```
因子: [mkt, smb, vmg]
中国三因子模型。核心创新：在计算价值因子 (VMG) 时剔除市值最低 30% 的"壳价值"股票。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `smb` | 规模因子 |
| `vmg` | Value Minus Growth（剔壳调整后的价值因子） |

**所需数据**：`mkt_cap`、`bm`、`is_st`

### SY4

```
因子: [mkt, smb, mgmt, perf]
Stambaugh-Yuan 误定价四因子模型。基于多个异象指标聚类构建管理和绩效两个因子。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `smb` | 规模因子 |
| `mgmt` | 管理因子（基于资产增长、应计项目等指标的聚类） |
| `perf` | 绩效因子（基于 ROE、动量等指标的聚类） |

**所需数据**：`mkt_cap`、`asset_growth`、`operating_accruals`、`roe`

### Reversal

```
因子: [mkt, smb, rev]
短期反转模型。A 股市场存在显著的短期反转效应 — 过去 20 日跌幅大的股票未来表现更好。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `smb` | 规模因子 |
| `rev` | 反转因子（低过去 20 日收益 - 高过去 20 日收益） |

**所需数据**：`mkt_cap`、股价数据（用于计算 20 日收益率）

### Low Vol

```
因子: [mkt, smb, ivol]
低波动模型。低特质波动率的股票倾向于获得更高的风险调整后收益。
```

| 因子 | 含义 |
|------|------|
| `mkt` | 市场超额收益 |
| `smb` | 规模因子 |
| `ivol` | 特质波动率因子（低波动 - 高波动） |

**所需数据**：`mkt_cap`、日收益率数据（用于计算特质波动率）

## 数据准备

### 自动数据拉取

FactorEngine 内部通过 `FactorReturnData` 子类自动从 JiuHuang API 拉取所需数据：

1. 根据 `factor_type` 选择对应的数据类（如 `FF3Data`、`FF5Data` 等）
2. 调用 `prepare_data()` 拉取股票收益率、市值、基本面数据
3. 合并后传入计算器

整个过程对用户透明，无需手动准备数据。

### 数据合并逻辑

基本面数据（BM、盈利、投资等）使用 **Point-in-Time (PIT)** 原则匹配到股票收益：
- 仅使用已知的财报数据（`ann_date <= trade_date`）
- 选取最近可用数据（不超过 6 个月前）

### 使用自定义数据

如果你已有股票收益率和基本面数据，可以跳过 FactorEngine 直接使用 `GeneralFactorCalculator`：

```python
from jh_quant.factors.factors.general import GeneralFactorCalculator
from jh_quant.factors.config import FactorType, CalculationMethod, TimePeriod

calc = GeneralFactorCalculator(
    factor_type=FactorType.FF3,
    method=CalculationMethod.SIMPLE,
    period=TimePeriod.MONTHLY,
)

factor_returns = calc.calculate(
    stock_returns=my_stock_returns,  # DataFrame [symbol, date, return]
    market_cap=my_market_cap,        # DataFrame [symbol, date, mkt_cap]
    fundamentals={'bm': my_bm},      # Dict[str, DataFrame]
)
```

`stock_returns` 需要包含 `symbol`、`date`、`return` 列，`return` 为小数形式（如 0.03 表示 3%）。
