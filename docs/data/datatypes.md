# DataTypes 介绍

`DataTypes` 是一个枚举类，每个成员代表一种可以从 JiuHuang API 获取的数据类型。当前共支持 **360+** 种数据类型。

## 数据源前缀

所有 DataTypes 的 **值（value）** 使用前缀来标识数据来源和编码体系：

| 前缀 | 数据源 | 数量 | 字段命名 | code 列 | date 列 |
|------|--------|------|----------|---------|---------|
| `ak_` | akshare 数据源（东方财富等） | 111 | 英文标准化 | `symbol` | `date` |
| `ts_` | tushare 数据源 | 222 | 英文标准化 | `ts_code` | `trade_date` |
| `jh_` | JiuHuang 自有数据 | 28 | 英文标准化 | `symbol` | `date` |

数据统一以**英文标准化字段**输出，例如 `open`、`high`、`low`、`close`、`volume` 等，无论原始数据源是 akshare 还是 tushare。

### 枚举名 vs 枚举值

```python
from jh_quant.data import DataTypes

# 枚举名（Python中使用）
DataTypes.AK_STOCK_ZH_A_HIST_QFQ

# 枚举值（API调用中的字符串标识）
DataTypes.AK_STOCK_ZH_A_HIST_QFQ.value  # "ak_stock_zh_a_hist_qfq"
```

## 数据类型分类

### 股票行情（ak_ / ts_）

| DataType | 说明 |
|----------|------|
| `AK_STOCK_ZH_A_HIST` | A 股日线（不复权） |
| `AK_STOCK_ZH_A_HIST_QFQ` | A 股日线（前复权） |
| `AK_STOCK_ZH_A_HIST_HFQ` | A 股日线（后复权） |
| `AK_STOCK_ZH_A_SPOT` | A 股实时行情 |
| `TS_DAILY` | A 股日线（tushare 格式） |
| `TS_DAILY_QFQ` | A 股日线前复权（tushare） |
| `TS_DAILY_HFQ` | A 股日线后复权（tushare） |
| `TS_WEEKLY` / `TS_MONTHLY` | 周线 / 月线 |
| `TS_STK_MINS` | 分钟线数据 |

使用示例：

```python
from jh_quant.data import JHData, DataTypes

jh = JHData()

# 获取 A 股前复权日线
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519",
    start="2024-01-01",
    end="2024-12-31",
)

# 获取 A 股实时行情
spot = jh.get_data(DataTypes.AK_STOCK_ZH_A_SPOT)
```

### 指数数据（ak_ / ts_）

| DataType | 说明 |
|----------|------|
| `AK_STOCK_ZH_INDEX_DAILY_EM` | A 股指数日线 |
| `AK_INDEX_GLOBAL_HIST_EM` | 全球指数历史 |
| `AK_INDEX_GLOBAL_SPOT_EM` | 全球指数实时 |
| `TS_INDEX_DAILY` | 指数日线（tushare） |
| `TS_INDEX_DAILYBASIC` | 指数日线基础指标 |
| `TS_INDEX_CLASSIFY` | 指数分类 |
| `TS_INDEX_GLOBAL` | 全球指数 |

### 基金数据（ak_ / ts_）

| DataType | 说明 |
|----------|------|
| `AK_FUND_ETF_HIST_EM` | ETF 历史行情 |
| `AK_FUND_ETF_HIST_EM_QFQ` | ETF 历史（前复权） |
| `AK_FUND_INFO_INDEX_EM` | 基金基本信息 |
| `AK_FUND_NAME_EM` | 基金名称列表 |
| `AK_FUND_PORTFOLIO_HOLD_EM` | 基金持仓 |
| `AK_FUND_PORTFOLIO_INDUSTRY_ALLOCATION_EM` | 基金行业配置 |
| `TS_FUND_BASIC` | 基金基本信息（tushare） |
| `TS_FUND_ADJ` | 基金复权因子（tushare） |

### 基本面数据（ak_ / ts_）

| DataType | 说明 |
|----------|------|
| `AK_STOCK_LRB_EM` | 利润表 |
| `AK_STOCK_XJLL_EM` | 现金流量表 |
| `AK_STOCK_ZCFZ_EM` | 资产负债表 |
| `AK_STOCK_INDIVIDUAL_INFO_EM` | 个股基本信息 |
| `TS_INCOME` | 利润表（tushare） |
| `TS_BALANCESHEET` | 资产负债表（tushare） |
| `TS_CASHFLOW` | 现金流量表（tushare） |
| `TS_FINA_INDICATOR` | 财务指标 |
| `TS_EXPRESS` | 业绩快报 |
| `TS_FORECAST` | 业绩预告 |
| `TS_DIVIDEND` | 分红送股 |

### 资金流向（ak_）

| DataType | 说明 |
|----------|------|
| `AK_STOCK_MAIN_FUND_FLOW` | 主力资金流向 |
| `AK_STOCK_INDIVIDUAL_FUND_FLOW` | 个股资金流向 |
| `AK_STOCK_MARKET_FUND_FLOW` | 市场资金流向 |
| `AK_STOCK_SECTOR_FUND_FLOW_RANK` | 板块资金排名 |
| `AK_STOCK_SECTOR_FUND_FLOW_HIST` | 板块资金历史 |

### 宏观经济（ak_macro_ / ts_）

| DataType | 说明 |
|----------|------|
| `AK_MACRO_CHINA_CPI` | 居民消费价格指数 |
| `AK_MACRO_CHINA_PPI` | 工业品出厂价格指数 |
| `AK_MACRO_CHINA_PMI` | 制造业 PMI |
| `AK_MACRO_CHINA_GDP` | 国内生产总值 |
| `AK_MACRO_CHINA_GDP_YEARLY` | GDP 年度数据 |
| `AK_MACRO_CHINA_MONEY_SUPPLY` | 货币供应量 |
| `AK_MACRO_CHINA_LPR` | LPR 利率 |
| `AK_MACRO_CHINA_SHIBOR_ALL` | SHIBOR 利率 |
| `AK_MACRO_CHINA_RMB` | 人民币汇率 |
| `AK_MACRO_CHINA_TRADE_BALANCE` | 贸易差额 |
| `TS_CN_CPI` | CPI（tushare） |
| `TS_CN_GDP` | GDP（tushare） |
| `TS_CN_M` | 货币供应量（tushare） |

### JiuHuang 因子数据（jh_）

JiuHuang 自有因子数据，包含多个因子模型的日频和月频收益率及暴露度：

| DataType | 说明 |
|----------|------|
| `JH_FACTOR_CAPM_RETURNS_DAILY` | CAPM 因子日频收益率 |
| `JH_FACTOR_CAPM_RETURNS_MONTHLY` | CAPM 因子月频收益率 |
| `JH_FACTOR_CAPM_EXPOSURE_DAILY` | CAPM 因子日频暴露度 |
| `JH_FACTOR_CARHART_RETURNS_DAILY` | Carhart 四因子日频收益率 |
| `JH_FACTOR_DHS_RETURNS_DAILY` | DHS 三因子日频收益率 |
| `JH_FACTOR_HXZ_RETURNS_DAILY` | HXZ 三因子日频收益率 |
| `JH_FACTOR_LOW_VOL_RETURNS_DAILY` | 低波动因子日频收益率 |
| `JH_FACTOR_NM_RETURNS_DAILY` | NM 因子日频收益率 |
| `JH_FACTOR_REVERSAL_RETURNS_DAILY` | 反转因子日频收益率 |

每个因子包含 `RETURNS`（收益率）和 `EXPOSURE`（暴露度）两个维度，覆盖 `DAILY` 和 `MONTHLY` 两种频率。

### 更多类型

完整的 DataTypes 列表可以通过以下方式查看：

```python
from jh_quant.data import DataTypes

# 列出所有数据类型
for dt in DataTypes:
    print(f"{dt.name} = {dt.value}")
```

## 如何选择 DataType

### 根据数据源选择

- 如果你之前使用 **akshare**，选择 `ak_` 前缀的类型，字段命名偏向 akshare 风格
- 如果你之前使用 **tushare**，选择 `ts_` 前缀的类型，code 列为 `ts_code` 格式（如 `000001.SZ`）
- 如果使用 JiuHuang 自有因子数据，选择 `jh_` 前缀的类型

### 根据复权方式选择

同一种数据可能有多种复权方式：

```python
# 不复权
DataTypes.AK_STOCK_ZH_A_HIST

# 前复权（推荐用于回测）
DataTypes.AK_STOCK_ZH_A_HIST_QFQ

# 后复权（推荐用于计算实际收益）
DataTypes.AK_STOCK_ZH_A_HIST_HFQ
```

### 不同源的同一数据

许多数据类型在 akshare 和 tushare 两个源中都存在，核心字段相同：

```python
# akshare 源 - 使用 symbol，date 列名为 date
df = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001")

# tushare 源 - 使用 ts_code，date 列名为 trade_date
df = jh.get_data(DataTypes.TS_DAILY_QFQ, ts_code="000001.SZ")
```

两者的核心字段（`open`、`high`、`low`、`close`、`volume`）命名一致，可以无缝切换。
