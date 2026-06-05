# Look-Ahead Bias 防护

因子计算最容易出错的地方不是分组公式，而是**数据在时间上的可获得性**。如果把未来才知道的特征用于当期收益，就会产生 look-ahead bias，回测和因子检验都会被系统性高估。

`jh_quant.factors` 现在按以下规则处理时间对齐。

## 核心原则

1. 因子核心只接受标准化后的 DataFrame，不直接依赖 Tushare、AkShare 或 `JHData`。
2. 价格、市值、财务字段需要在进入因子计算前转换成统一 schema。
3. 用于分组的特征必须在收益期开始前已经可获得。
4. 财务字段必须带 `ann_date`，用公告日判断是否可用，而不是用报告期末日期。

## 默认 TS Loader

`load_ts_factor_inputs()` 是面向 Tushare 的便捷数据准备函数。默认参数是：

```python
from jh_quant.factors import load_ts_factor_inputs

inputs = load_ts_factor_inputs(
    start_date="2020-01-01",
    end_date="2024-12-31",
    period="M",
    price_adjust="qfq",
    lag_features=True,
)
```

默认行为：

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `period` | `"M"` | 直接使用 `TS_MONTHLY_*` 月频行情 |
| `price_adjust` | `"qfq"` | 优先使用前复权价格，默认映射到 `TS_MONTHLY_QFQ` |
| `lag_features` | `True` | 将 t 期观测到的特征用于下一期收益 |

如果设置 `period="D"`，loader 会使用 `TS_DAILY_*` 行情并转换为月末收益；默认仍是 `TS_DAILY_QFQ`。

## 市场特征滞后

市值、BM、动量、反转、波动率等市场特征容易和同月收益发生时间穿越。默认 TS loader 会做一期间隔：

```text
2024-01-31 的 mkt_cap / bm / momentum
        ↓
用于 2024-02-29 的股票收益和因子组合分组
```

也就是说，`2024-01-31` 月末才知道的特征不会用来解释 `2024-01-31` 当月收益。

如果确实要做诊断或对照实验，可以关闭：

```python
inputs = load_ts_factor_inputs(..., lag_features=False)
```

但研究和回测默认不建议关闭。

## 财务字段必须使用公告日

财务报表的报告期末日期不等于可获得日期。例如一季报报告期是 `2024-03-31`，但公告日可能是 `2024-05-05`。在这种情况下，该财务数据不能用于 `2024-04-30` 的收益期。

财务类字段必须包含：

| 列名 | 含义 |
|------|------|
| `symbol` | 股票代码 |
| `date` | 报告期或观测期，例如 `2024-03-31` |
| `ann_date` | 公告日或真实可获得日，例如 `2024-05-05` |
| `<field>` | 财务字段值，例如 `roe`、`op`、`asset_growth` |

示例：

```python
roe = pd.DataFrame({
    "symbol": ["000001.SZ"],
    "date": ["2024-03-31"],      # 报告期
    "ann_date": ["2024-05-05"],  # 公告日
    "roe": [0.12],
})
```

因子核心会按 `ann_date <= return_date` 做 as-of 匹配。因此上面的 ROE 不会用于 `2024-04-30`，只会从 `2024-05-31` 这类公告日之后的收益期开始可用。

缺少 `ann_date` 的财务字段会在 schema 校验阶段报错，避免静默引入未来信息。

## 需要 `ann_date` 的字段

当前 schema 将以下字段视为财务或公告相关字段：

```text
op, asset_growth, gp_a, gross_profit, roe, roe_quarterly,
pead, sud, fin, net_share_issuance, operating_accruals,
mgmt, perf
```

这些字段进入 `fundamentals` 时必须带 `ann_date`。

市场衍生字段如 `bm`、`momentum`、`rev`、`ivol` 不强制要求 `ann_date`，但应由数据准备层先做滞后对齐。

## 自行准备数据时的检查清单

- `stock_returns` 使用收益期结束日作为 `date`，包含 `symbol/date/return`。
- `market_cap` 的 `date` 应已经对齐到可使用该市值的收益期。
- 市场衍生特征不要和同一期收益 exact match，除非该特征在收益期开始前已知。
- 财务字段必须带 `ann_date`，并用公告日而不是报告期末日期做可获得性判断。
- 因子验证中的 Fama-MacBeth 暴露默认滞后一阶，避免用当期估计的 beta 解释当期收益。

## 相关文档

- [快速开始](./quickstart.md)
- [计算方法详解](./calculation.md)
- [暴露计算与验证](./exposure.md)
