# 快速开始

## 安装与环境

jh_quant.factors 随 jh-quant 包一起安装：

```bash
pip install jh-quant
```

依赖包括 `pandas`、`numpy`、`joblib`、`polars`（可选加速）。与 `jh_quant.data` 共享同一套环境变量配置：

```bash
export JIUHUANG_API_KEY="your-api-key"
```

## 核心入口

框架提供三个不同层次的入口，按场景选择：

| 入口 | 适用场景 |
|------|---------|
| `calculate_factor_returns()` | 最简洁，一次性计算因子收益率 |
| `FactorEngine` | 需要复用实例、批量计算多个模型 |
| `GeneralFactorCalculator` | 已有股票收益率和基本面数据，只需计算逻辑 |

### 方式一：便捷函数（推荐入门）

```python
from jh_quant.factors import calculate_factor_returns

# 计算 FF3 月度因子收益率
ff3 = calculate_factor_returns(
    'ff3',
    method='simple',
    period='M',
    start_date='2020-01-01',
    end_date='2024-12-31',
)
print(ff3.head())
```

输出为一个 DataFrame，index 为 date，columns 为因子名（如 `mkt`、`smb`、`hml`）：

```
              mkt       smb       hml
date
2020-01-02  0.0123   -0.0045    0.0087
2020-01-03 -0.0056    0.0023   -0.0012
...
```

一次性计算所有因子模型：

```python
all_factors = calculate_factor_returns('all', start_date='2020-01-01', end_date='2024-12-31')
# 返回 Dict[str, DataFrame]，key 为 "ff3", "ff5", "carhart" 等

for name, df in all_factors.items():
    print(f"{name}: {len(df)} 行, 因子: {list(df.columns)}")
```

### 方式二：FactorEngine（推荐进阶）

```python
from jh_quant.factors import FactorEngine, FactorType, CalculationMethod, TimePeriod

engine = FactorEngine()

# 计算单个因子模型
ff5 = engine.calculate_factor_returns(
    factor_type=FactorType.FF5,
    method=CalculationMethod.CLASSIC,
    period=TimePeriod.DAILY,
    start_date='2024-01-01',
    end_date='2024-12-31',
    n_jobs=4,
    use_polars=True,
)

# 批量计算
results = engine.calculate_all_factors(
    factor_types=[FactorType.FF3, FactorType.CARHART, FactorType.DHS],
    method=CalculationMethod.SIMPLE,
    period=TimePeriod.MONTHLY,
    start_date='2020-01-01',
    end_date='2024-12-31',
)

for ft, df in results.items():
    print(f"{ft.value}: {df.shape}")
```

### 方式三：导入便捷函数

```python
from jh_quant.factors import calculate_exposures

# 给定已计算好的因子收益率和个股收益率，计算个股暴露
exposures = calculate_exposures(
    stock_returns=my_stock_returns,   # 包含 symbol, date, return
    factor_returns=ff3,               # FactorEngine 的输出
    period='M',
)
```

## 参数速查

### FactorType（字符串简写）

| 字符串 | FactorType | 因子组成 |
|--------|-----------|---------|
| `'capm'` | `CAPM` | mkt |
| `'ff3'` | `FF3` | mkt, smb, hml |
| `'ff5'` | `FF5` | mkt, smb, hml, rmw, cma |
| `'carhart'` | `CARHART` | mkt, smb, hml, umd |
| `'novy_marx'` | `NOVY_MARX` | mkt, hml_adj, umd, gp_a |
| `'hxz'`, `'hou_xue_zhang'` | `HOU_XUE_ZHANG` | mkt, me, ia, roe |
| `'dhs'` | `DHS` | mkt, pead, fin |
| `'ch3'` | `CH3` | mkt, smb, vmg |
| `'sy4'` | `SY4` | mkt, smb, mgmt, perf |
| `'reversal'` | `REVERSAL` | mkt, smb, rev |
| `'low_vol'` | `LOW_VOL` | mkt, smb, ivol |
| `'all'` | 所有以上模型 | — |

### TimePeriod

| 值 | 说明 |
|----|------|
| `'M'` / `TimePeriod.MONTHLY` | 月度因子 |
| `'D'` / `TimePeriod.DAILY` | 日度因子 |

### CalculationMethod

| 值 | 说明 |
|----|------|
| `'simple'` / `CalculationMethod.SIMPLE` | 简化方法（默认），等权+中位数分组，计算快 |
| `'classic'` / `CalculationMethod.CLASSIC` | 经典方法，市值加权+分位数分组，接近学术论文实现 |

### 其他常用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `n_jobs` | CPU 核数（最多 4） | 并行任务数 |
| `use_polars` | `True` | 是否用 Polars 加速 |
| `symbols` | `None`（全部 A 股） | 限定股票范围 |
| `verbose` | `True` | 是否打印进度信息 |

## 下一步

- 查看 [11 种因子模型的详细介绍](./factor-models.md)
- 了解 [SIMPLE 与 CLASSIC 计算方法的区别](./calculation.md)
- 学习 [个股暴露度计算和因子验证](./exposure.md)
