# 回测指标与选股

回测引擎基于策略日收益率序列，自动计算 11 项绩效指标。此外提供因子选股器，可基于 Fama-MacBeth 回归权重进行股票筛选。

## 绩效指标

回测完成后，`backtest()` 返回的 `backtest_perf`（DataFrame）对每只股票的每个策略计算以下指标：

| 指标 | 列名 | 说明 |
|------|------|------|
| 累积收益率 | `累积收益率` | 整个回测期的累计收益 |
| 最大回撤 | `最大回撤` | 收益曲线从峰顶到谷底的最大跌幅 |
| 胜率 | `胜率` | 盈利交易日占总交易日的比例 |
| 夏普比率 | `夏普比率` | 年化超额收益 / 年化波动率（无风险利率设为 0） |
| 卡玛比率 | `卡玛比率` | 年化收益率 / 最大回撤绝对值 |
| 索提诺比率 | `索提诺比率` | 类似夏普，但只惩罚下行波动率 |
| 收益率标准差 | `收益率标准差` | 日收益率的标准差（波动率度量） |
| VaR | `VaR` | 95% 置信度的 Value at Risk |
| CVaR | `CVaR` | 95% 置信度的 Conditional VaR（尾部期望损失） |
| 盈亏比 | `盈亏比` | 平均盈利 / 平均亏损（绝对值比） |
| 欧米伽比率 | `欧米伽比率` | 盈利概率加权和 / 亏损概率加权和 |

指标计算底层使用 `quantstats` 库。`metric_decimal` 参数控制小数位数（默认 2 位）。

### 查看结果

```python
# 查看全部指标
print(backtest_perf)

# 筛选关注的指标
cols = ["symbol", "strategy", "累积收益率", "夏普比率", "最大回撤", "胜率"]
print(backtest_perf[cols])

# 按策略汇总（平均值）
summary = backtest_perf.groupby("strategy")[[
    "累积收益率", "夏普比率", "最大回撤", "胜率"
]].mean()
print(summary)

# 按行业汇总
industry_summary = backtest_perf.groupby("industry")[[
    "累积收益率", "夏普比率"
]].mean()
print(industry_summary)

# 找出每只股票的最优策略
best = backtest_perf.loc[
    backtest_perf.groupby("symbol")["夏普比率"].idxmax()
]
print(best[["symbol", "strategy", "夏普比率"]])
```

## 费率对指标的影响

佣金和印花税会直接影响策略日收益率，进而影响所有指标：

```python
# 默认费率
trading_history, perf_low = backtest(strategies, stock_price)
# commission_rate=0.0002, stamp_tax_rate=0.0005

# 高费率场景
trading_history, perf_high = backtest(
    strategies, stock_price,
    commission_rate=0.001,    # 千一佣金
    stamp_tax_rate=0.001,     # 千一印花税
)

# 对比费率影响
print("低费率夏普:", perf_low["夏普比率"].mean())
print("高费率夏普:", perf_high["夏普比率"].mean())
```

费率在 `calculate_strategy_returns()` 中扣除：
- **佣金**：买入和卖出各收取一次
- **印花税**：仅卖出时收取
- **计算公式**：`日收益率 = (卖出收入 - 佣金 - 印花税) / (买入成本 + 佣金) - 1`

## FactorSelector 因子选股

`FactorSelector` 使用 Fama-MacBeth 回归得到的因子权重对股票打分，选出得分最高的 N 只股票。

### 原理

1. 对每只股票计算其在各因子上的暴露度（Beta）
2. 使用 Fama-MacBeth 第二步得到的因子风险溢价（lambda）作为权重
3. 股票得分 = `sum(beta_k * lambda_k)`，即因子暴露的加权和
4. 选取得分最高的 top N 只股票

### 基本用法

```python
from jh_quant.backtest import FactorSelector
from jh_quant.factors import FactorEngine, FactorType
from jh_quant.factors.validators import FamaMacBethValidator

# 1. 计算因子收益率
engine = FactorEngine()
ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    period='M',
    start_date='2020-01-01',
    end_date='2024-12-31',
)

# 2. 计算暴露度
exposures = engine.calculate_stock_exposures(
    stock_returns=stock_returns,
    factor_returns=ff3,
)

# 3. Fama-MacBeth 得到因子权重
validator = FamaMacBethValidator()
fm_result = validator.validate(
    stock_returns=stock_returns,
    factor_returns=ff3,
    exposures=exposures,
)

# 4. 创建选股器
selector = FactorSelector(
    exposures=exposures,
    fm_result=fm_result,
)

# 5. 选股
selected = selector.select(top_n=10)
# selected: {"2023-01-31": ["000001", "600519", ...], "2023-02-28": [...]}
```

### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `exposures` | DataFrame | 个股因子暴露度，包含 `symbol`、`date` 和因子列 |
| `fm_result` | FamaMacBethValidationResult | Fama-MacBeth 验证结果 |
| `factor_alpha_threshold` | float | 因子显著性阈值，默认 0.05（5%）。不显著的因子权重置零 |
| `weight_normalize` | bool | 是否对得分权重做归一化处理，默认 True |
| `use_significant_only` | bool | 是否只使用显著的因子，默认 True |

### 使用选股结果

```python
# 获取选股结果后，可在回测中限制标的
selected = selector.select(top_n=10)

# 用选股结果过滤价格数据
# selected["2023-01-31"] → ["000001", "600519", ...]

# 按月调仓的回测逻辑伪代码
for date, symbols in selected.items():
    monthly_stocks = stock_price[stock_price["symbol"].isin(symbols)]
    # 在该月使用这些股票进行回测
```

### 因子权重解读

```python
# 查看各因子的权重（lambda）
print(fm_result.to_dataframe())
#   factor  mean_lambda  t_statistic_nw  p_value_nw  significant
# 0    mkt       0.0078           2.21       0.031         True
# 1    smb       0.0021           1.43       0.158        False
# 2    hml       0.0045           2.55       0.014         True

# 如果 smb 不显著（p > 0.05），而 use_significant_only=True
# 则选股得分中 smb 的权重为 0，实际只使用 mkt 和 hml
```

## 指标精度

所有绩效指标支持通过 `metric_decimal` 调整小数位数：

```python
# 默认 2 位小数
_, perf = backtest(strategies, stock_price)
print(perf["夏普比率"].iloc[0])  # 1.23

# 4 位小数
_, perf = backtest(strategies, stock_price, metric_decimal=4)
print(perf["夏普比率"].iloc[0])  # 1.2345
```

这仅影响显示精度，不改变内部计算。
