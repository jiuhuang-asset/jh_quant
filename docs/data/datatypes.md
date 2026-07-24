# DataTypes 介绍

`DataTypes` 是一个枚举类，每个成员代表一种可以从 JiuHuang API 获取的数据类型。当前共支持 **37 种**（含复权变体共 **43 个**）数据类型。

## 数据源

| 前缀 | 数据源 | 字段命名 | code 列 | date 列 |
|------|--------|----------|---------|---------|
| `ts_` | tushare 数据源 | 英文标准化 | `ts_code` | `trade_date` |
| `ak_` | akshare 数据源（东方财富等） | 英文标准化 | `symbol` | `date` |

数据统一以**英文标准化字段**输出，例如 `open`、`high`、`low`、`close`、`volume` 等。

### 枚举名 vs 枚举值

```python
from jh_quant.data import DataTypes

# 枚举名（Python中使用）
DataTypes.TS_DAILY

# 枚举值（API调用中的字符串标识）
DataTypes.TS_DAILY.value  # "ts_daily"
```

## 行情数据

### 日线 / 周线 / 月线

| DataType | 说明 |
|----------|------|
| `TS_DAILY` | A 股日线（不复权） |
| `TS_DAILY_QFQ` | A 股日线（前复权） |
| `TS_DAILY_HFQ` | A 股日线（后复权） |
| `TS_WEEKLY` | A 股周线（不复权） |
| `TS_WEEKLY_QFQ` | A 股周线（前复权） |
| `TS_WEEKLY_HFQ` | A 股周线（后复权） |
| `TS_MONTHLY` | A 股月线（不复权） |
| `TS_MONTHLY_QFQ` | A 股月线（前复权） |
| `TS_MONTHLY_HFQ` | A 股月线（后复权） |

使用示例：

```python
from jh_quant.data import JHData, DataTypes

jh = JHData()

# 获取 A 股前复权日线
df = jh.get_data(
    DataTypes.TS_DAILY_QFQ,
    ts_code="000001.SZ,600519.SH",
    start="2024-01-01",
    end="2024-12-31",
)

# 获取 A 股月线
df = jh.get_data(
    DataTypes.TS_MONTHLY,
    ts_code="000001.SZ",
    start="2020-01-01",
    end="2024-12-31",
)
```

### 日线基础指标

| DataType | 说明 |
|----------|------|
| `TS_DAILY_BASIC` | 日线基础指标（换手率、市盈率、市净率等） |

### 实时行情

| DataType | 说明 |
|----------|------|
| `AK_STOCK_ZH_A_SPOT` | A 股实时行情（akshare 源） |

```python
# 获取 A 股实时行情（建议 bypass_cache=True）
spot = jh.get_data(DataTypes.AK_STOCK_ZH_A_SPOT, bypass_cache=True)
```

## 基本面数据

### 财务报表

| DataType | 说明 |
|----------|------|
| `TS_BALANCESHEET` | 资产负债表 |
| `TS_INCOME` | 利润表 |
| `TS_CASHFLOW` | 现金流量表 |
| `TS_FINA_INDICATOR` | 财务指标（ROE、ROA、毛利率等） |
| `TS_FINA_AUDIT` | 财务审计意见 |

```python
# 获取资产负债表
df = jh.get_data(
    DataTypes.TS_BALANCESHEET,
    ts_code="000001.SZ",
    start="2023-01-01",
    end="2024-12-31",
)
```

## 股票基础信息

| DataType | 说明 |
|----------|------|
| `TS_STOCK_BASIC` | 股票基本信息（公司名称、行业、上市日期等） |
| `TS_TRADE_CAL` | 交易日历 |
| `TS_ADJ_FACTOR` | 复权因子 |

```python
# 获取股票基本信息
df = jh.get_data(DataTypes.TS_STOCK_BASIC)

# 获取交易日历
cal = jh.get_data(DataTypes.TS_TRADE_CAL, start="2024-01-01", end="2024-12-31")
```

## 新股与风险警示

| DataType | 说明 |
|----------|------|
| `TS_NEW_SHARE` | 新股列表（IPO 信息） |
| `TS_STOCK_ST` | 风险警示股票（ST/*ST 等） |
| `TS_SUSPEND_D` | 停牌信息 |

```python
# 获取新股列表
df = jh.get_data(DataTypes.TS_NEW_SHARE)

# 获取风险警示股票
df = jh.get_data(
    DataTypes.TS_STOCK_ST,
    start="2024-01-01",
    end="2024-12-31",
)

# 获取停牌信息
df = jh.get_data(
    DataTypes.TS_SUSPEND_D,
    start="2024-01-01",
    end="2024-12-31",
)
```

## 筹码与持仓数据

| DataType | 说明 |
|----------|------|
| `TS_CYQ_CHIPS` | 筹码分布 |
| `TS_CYQ_PERF` | 筹码穿透率 |
| `TS_STK_HOLDERTRADE` | 股东增减持 |
| `TS_TOP10_HOLDERS` | 十大股东 |

```python
# 获取筹码分布
df = jh.get_data(DataTypes.TS_CYQ_CHIPS, ts_code="000001.SZ")
```

## 资金流向

| DataType | 说明 |
|----------|------|
| `TS_MONEYFLOW` | 个股资金流向（大单/小单成交，2010年起） |
| `TS_MONEYFLOW_THS` | 同花顺个股资金流向 |
| `TS_MONEYFLOW_CNT_THS` | 同花顺板块资金流向 |
| `TS_MONEYFLOW_IND_THS` | 同花顺行业资金流向 |
| `TS_MONEYFLOW_MKT_DC` | 东方财富大盘资金流向 |

```python
# 获取个股资金流向
df = jh.get_data(
    DataTypes.TS_MONEYFLOW,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)

# 获取同花顺个股资金流向
df = jh.get_data(
    DataTypes.TS_MONEYFLOW_THS,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 融资融券

| DataType | 说明 |
|----------|------|
| `TS_MARGIN` | 融资融券汇总（按交易所） |
| `TS_MARGIN_DETAIL` | 融资融券明细（按个股） |

```python
# 获取融资融券明细
df = jh.get_data(
    DataTypes.TS_MARGIN_DETAIL,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-06-30",
)
```

## 业绩预告与快报

| DataType | 说明 |
|----------|------|
| `TS_EXPRESS` | 业绩快报 |
| `TS_FORECAST` | 业绩预告 |

```python
# 获取业绩预告
df = jh.get_data(
    DataTypes.TS_FORECAST,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 分红与股本变化

| DataType | 说明 |
|----------|------|
| `TS_DIVIDEND` | 分红送股 |

```python
# 获取分红送股数据
df = jh.get_data(DataTypes.TS_DIVIDEND, ts_code="000001.SZ")
```

## 龙虎榜

| DataType | 说明 |
|----------|------|
| `TS_TOP_LIST` | 龙虎榜每日交易明细 |
| `TS_TOP_INST` | 龙虎榜机构成交明细 |

```python
# 获取龙虎榜交易明细
df = jh.get_data(
    DataTypes.TS_TOP_LIST,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 技术面因子

| DataType | 说明 |
|----------|------|
| `TS_STK_FACTOR_PRO` | 技术面专业版数据（MACD、KDJ、RSI 等全历史因子） |

```python
# 获取技术面因子
df = jh.get_data(
    DataTypes.TS_STK_FACTOR_PRO,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 跨市场比价

| DataType | 说明 |
|----------|------|
| `TS_STK_AH_COMPARISON` | AH 股比价 |

```python
# 获取 AH 股比价数据
df = jh.get_data(
    DataTypes.TS_STK_AH_COMPARISON,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 同花顺概念板块

| DataType | 说明 |
|----------|------|
| `TS_THS_INDEX` | 同花顺概念和行业指数 |
| `TS_THS_MEMBER` | 同花顺概念板块成分 |
| `TS_THS_DAILY` | 同花顺概念板块行情 |

```python
# 获取同花顺概念和行业指数
df = jh.get_data(DataTypes.TS_THS_INDEX, ts_code="884166.TI")

# 获取同花顺概念板块成分股
df = jh.get_data(DataTypes.TS_THS_MEMBER, ts_code="884166.TI")

# 获取同花顺概念板块行情
df = jh.get_data(
    DataTypes.TS_THS_DAILY,
    ts_code="884166.TI",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 完整列表

以下为当前有数据维护的全部 DataTypes（含复权变体共 43 个），表名大写即对应枚举名：

| 枚举名 | 值（API 标识） | 分类 |
|--------|---------------|------|
| `TS_DAILY` | `ts_daily` | 行情 |
| `TS_DAILY_QFQ` | `ts_daily_qfq` | 行情 |
| `TS_DAILY_HFQ` | `ts_daily_hfq` | 行情 |
| `TS_WEEKLY` | `ts_weekly` | 行情 |
| `TS_WEEKLY_QFQ` | `ts_weekly_qfq` | 行情 |
| `TS_WEEKLY_HFQ` | `ts_weekly_hfq` | 行情 |
| `TS_MONTHLY` | `ts_monthly` | 行情 |
| `TS_MONTHLY_QFQ` | `ts_monthly_qfq` | 行情 |
| `TS_MONTHLY_HFQ` | `ts_monthly_hfq` | 行情 |
| `TS_DAILY_BASIC` | `ts_daily_basic` | 行情 |
| `AK_STOCK_ZH_A_SPOT` | `ak_stock_zh_a_spot` | 行情 |
| `TS_BALANCESHEET` | `ts_balancesheet` | 基本面 |
| `TS_INCOME` | `ts_income` | 基本面 |
| `TS_CASHFLOW` | `ts_cashflow` | 基本面 |
| `TS_FINA_INDICATOR` | `ts_fina_indicator` | 基本面 |
| `TS_FINA_AUDIT` | `ts_fina_audit` | 基本面 |
| `TS_STOCK_BASIC` | `ts_stock_basic` | 基础信息 |
| `TS_TRADE_CAL` | `ts_trade_cal` | 基础信息 |
| `TS_ADJ_FACTOR` | `ts_adj_factor` | 基础信息 |
| `TS_NEW_SHARE` | `ts_new_share` | 新股与风险警示 |
| `TS_STOCK_ST` | `ts_stock_st` | 新股与风险警示 |
| `TS_SUSPEND_D` | `ts_suspend_d` | 新股与风险警示 |
| `TS_CYQ_CHIPS` | `ts_cyq_chips` | 筹码持仓 |
| `TS_CYQ_PERF` | `ts_cyq_perf` | 筹码持仓 |
| `TS_STK_HOLDERTRADE` | `ts_stk_holdertrade` | 筹码持仓 |
| `TS_TOP10_HOLDERS` | `ts_top10_holders` | 筹码持仓 |
| `TS_MONEYFLOW` | `ts_moneyflow` | 资金流向 |
| `TS_MONEYFLOW_THS` | `ts_moneyflow_ths` | 资金流向 |
| `TS_MONEYFLOW_CNT_THS` | `ts_moneyflow_cnt_ths` | 资金流向 |
| `TS_MONEYFLOW_IND_THS` | `ts_moneyflow_ind_ths` | 资金流向 |
| `TS_MONEYFLOW_MKT_DC` | `ts_moneyflow_mkt_dc` | 资金流向 |
| `TS_MARGIN` | `ts_margin` | 融资融券 |
| `TS_MARGIN_DETAIL` | `ts_margin_detail` | 融资融券 |
| `TS_EXPRESS` | `ts_express` | 业绩预告 |
| `TS_FORECAST` | `ts_forecast` | 业绩预告 |
| `TS_DIVIDEND` | `ts_dividend` | 分红股本 |
| `TS_TOP_LIST` | `ts_top_list` | 龙虎榜 |
| `TS_TOP_INST` | `ts_top_inst` | 龙虎榜 |
| `TS_STK_FACTOR_PRO` | `ts_stk_factor_pro` | 技术面 |
| `TS_STK_AH_COMPARISON` | `ts_stk_ah_comparison` | 跨市场 |
| `TS_THS_INDEX` | `ts_ths_index` | 同花顺概念板块 |
| `TS_THS_MEMBER` | `ts_ths_member` | 同花顺概念板块 |
| `TS_THS_DAILY` | `ts_ths_daily` | 同花顺概念板块 |

> 枚举定义中还有其他类型（指数、基金、宏观、港股、美股、因子等），但目前它们对应的数据表没有数据维护，不建议在生产中使用。

也可通过代码查看完整列表：

```python
from jh_quant.data import DataTypes

for dt in DataTypes:
    print(f"{dt.name} = {dt.value}")
```
