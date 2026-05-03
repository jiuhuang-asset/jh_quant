# 暴露计算与因子验证

计算出因子收益率之后，通常还需要知道**个股在这些因子上的暴露度（Beta）**，以及**因子是否真的有效**。框架提供了完整的暴露计算和因子验证链路。

## 暴露计算

### 基本用法

```python
from jh_quant.factors import FactorEngine, FactorType
from jh_quant.data import JHData, DataTypes

engine = FactorEngine()

# 1. 计算因子收益率
ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    period='M',
    start_date='2023-01-01',
    end_date='2024-12-31',
)

# 2. 获取个股收益率
jh = JHData()
stock_returns = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519",
    start="2023-01-01",
    end="2024-12-31",
)

# 3. 确保数据格式正确
stock_returns = stock_returns[['symbol', 'date', 'pct_chg']].rename(
    columns={'pct_chg': 'return'}
)
stock_returns['return'] = stock_returns['return'] / 100  # 百分比转小数

# 4. 计算暴露度
exposures = engine.calculate_stock_exposures(
    stock_returns=stock_returns,
    factor_returns=ff3,
    n_jobs=4,
)
print(exposures.head())
```

输出示例：

```
  symbol        date     alpha       mkt       smb       hml
0  000001  2024-12-31   0.0023    0.8956   -0.1234    0.4567
1  600519  2024-12-31  -0.0012    0.7234    0.0890   -0.2340
```

### 便捷函数

```python
from jh_quant.factors import calculate_exposures

exposures = calculate_exposures(
    stock_returns=stock_returns,
    factor_returns=ff3,
    period='M',        # 'M' 或 'D'，影响默认 lookback
    lookback=36,       # 滚动窗口大小，默认 36（月频）/ 252（日频）
)
```

### 计算方法

暴露度通过 **OLS 时序回归** 计算：

```
r_i - r_f = alpha_i + beta_1 * MKT + beta_2 * SMB + beta_3 * HML + epsilon_i
```

底层使用 `numpy.linalg.lstsq` 拟合，单只股票最小需要 24 条（`DEFAULT_MIN_OBSERVATIONS`）有效数据，否则返回 NaN。

### 滚动窗口 vs 全样本

默认使用**滚动窗口**计算（更贴合实际投资场景）：

```python
# 滚动窗口（默认）
exposures_rolling = engine.calculate_stock_exposures(
    stock_returns=stock_returns,
    factor_returns=ff3,
    n_jobs=4,
    verbose=True,
)
# 每只股票会产出多条暴露度时间序列（每个日期一条）
```

也可通过 `StockExposureCalculator` 直接控制：

```python
from jh_quant.factors.exposure import StockExposureCalculator

calc = StockExposureCalculator(min_observations=24, n_jobs=4)

# 滚动窗口：lookback_months=24
exposures_rolling = calc.calculate_rolling_exposures(
    stock_returns, ff3,
    lookback_months=24,
    verbose=True,
)

# 全样本（pooled OLS，每个股票只有一条记录）
exposures_pooled = calc.calculate_all_exposures(
    stock_returns, ff3,
    rolling=False,
    verbose=True,
)
```

## 因子验证

### 截距项验证

检验因子收益率序列是否显著不为零。对每个因子进行单样本 t 检验，使用 Newey-West 调整标准误（处理自相关）。

```python
from jh_quant.factors.validators import validate_factor_intercept

# 传入已计算的因子收益率
result = validate_factor_intercept(ff3)

# 查看结果
print(result.summary)

# 转为 DataFrame
print(result.to_dataframe())

# 所有因子是否都在 5% 水平显著
print(result.is_all_significant())
```

输出格式：

| factor | coefficient | t_statistic | t_statistic_nw | p_value_nw | significant_5pct |
|--------|-------------|-------------|----------------|------------|-----------------|
| mkt    | 0.0082      | 2.15        | 2.08           | 0.041      | True |
| smb    | 0.0034      | 1.87        | 1.72           | 0.089      | False |
| hml    | 0.0056      | 2.43        | 2.35           | 0.022      | True |

### Fama-MacBeth 两步验证

Fama-MacBeth 是最经典的因子有效性验证方法：

**Step 1（横截面回归）**：每个月，用个股收益率对因子暴露度做横截面回归，得到因子风险溢价 `lambda_t`

**Step 2（时序检验）**：对 `lambda_t` 序列做 t 检验，判断风险溢价是否显著

```python
from jh_quant.factors.validators import FamaMacBethValidator

validator = FamaMacBethValidator()

result = validator.validate(
    stock_returns=stock_returns,
    factor_returns=ff3,
    exposures=exposures,        # 可选，不传则自动计算
    nw_lags=12,                 # Newey-West 滞后阶数
)

# 查看验证结果
print(result.to_dataframe())

# 因子风险溢价的月度序列
print(result.lambdas)
```

输出格式：

| factor | mean_lambda | t_statistic | t_statistic_nw | p_value_nw | significant |
|--------|-------------|-------------|----------------|------------|-------------|
| mkt    | 0.0078      | 2.34        | 2.21           | 0.031      | True |
| smb    | 0.0021      | 1.56        | 1.43           | 0.158      | False |
| hml    | 0.0045      | 2.67        | 2.55           | 0.014      | True |

### 两种验证的区别

| 方面 | 截距项验证 | Fama-MacBeth |
|------|-----------|-------------|
| 检验对象 | 因子收益率均值是否非零 | 因子风险溢价是否显著 |
| 数据需求 | 仅需因子收益率 | 需要个股收益率 + 因子收益率 |
| 计算复杂度 | 低 | 高（每月一次横截面回归） |
| 学术地位 | 初步检验 | 黄金标准 |
| 用途 | 快速判断因子有没有"alpha" | 判断因子是否被市场定价 |

### 便捷函数

```python
from jh_quant.factors.validators import validate_factor

# 一站式验证（截距项 + Fama-MacBeth）
results = validate_factor(
    factor_returns=ff3,
    stock_returns=stock_returns,
    exposures=exposures,  # 可选
)

# results 包含:
# - results['intercept']: InterceptValidationResult
# - results['fama_macbeth']: FamaMacBethValidationResult
```

## 完整工作流示例

```python
from jh_quant.factors import FactorEngine, FactorType, CalculationMethod, TimePeriod
from jh_quant.data import JHData, DataTypes
from jh_quant.factors.validators import validate_factor

# === Step 1: 计算因子收益率 ===
engine = FactorEngine()
ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    method=CalculationMethod.SIMPLE,
    period=TimePeriod.MONTHLY,
    start_date='2020-01-01',
    end_date='2024-12-31',
)
print(f"FF3 因子收益率: {len(ff3)} 个月, 因子: {list(ff3.columns)}")

# === Step 2: 获取个股收益率 ===
jh = JHData()
stock_returns = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol='000001,000002,600519,300750,688981',
    start='2020-01-01',
    end='2024-12-31',
)
# 月度化: 取每月加权收益率
stock_returns['date'] = stock_returns['date'].dt.to_period('M').dt.to_timestamp()
monthly_rets = stock_returns.groupby(['symbol', 'date'])['pct_chg'].sum().reset_index()
monthly_rets = monthly_rets.rename(columns={'pct_chg': 'return'})
monthly_rets['return'] = monthly_rets['return'] / 100

# === Step 3: 验证因子 ===
validation_results = validate_factor(
    factor_returns=ff3,
    stock_returns=monthly_rets,
)

# 查看截距项检验
print("\n=== 截距项检验 ===")
print(validation_results['intercept'].to_dataframe())

# 查看 Fama-MacBeth 检验
print("\n=== Fama-MacBeth 检验 ===")
print(validation_results['fama_macbeth'].to_dataframe())
```
