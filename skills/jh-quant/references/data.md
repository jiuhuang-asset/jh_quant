# 数据获取模块 (data)

## 快速开始

```python
from jh_quant.data import JHData, DataTypes

jh = JHData()  # 自动从环境变量读取 JIUHUANG_API_KEY

df = jh.get_data(
    DataTypes.TS_DAILY_QFQ,
    ts_code="000001.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

## 配置

### API Key

```bash
export JIUHUANG_API_KEY="your-api-key"
export JIUHUANG_API_URL="https://data.jiuhuang.xyz"  # 可选，默认值
```

也可使用项目根目录的 `.env` 文件。

### 数据缓存

首次下载数据后缓存到本地 DuckDB（`~/.jiuhuang/cache_data.db`），后续相同查询直接从本地读取。

### DuckDB 并发说明

多进程场景下 DuckDB 可能被锁定。JHData 会自动检测并切换：

```python
# 自动模式（默认）
jh = JHData()

# 强制服务模式（多进程推荐）
jh = JHData(as_service=True)

# 强制直连模式
jh = JHData(as_service=False)
```

## DataFrame 便捷属性

返回的 DataFrame 经过 `_JHDataWrapper` 包装：

```python
df = jh.get_data(DataTypes.TS_DAILY_QFQ, ts_code="000001.SZ")

df.code_col       # tushare: "ts_code", akshare: "symbol"
df.date_col       # tushare: "trade_date", akshare: "date"
df.code_date_col  # ("ts_code", "trade_date")
df.jh_dt          # DataTypes.TS_DAILY_QFQ
df.to_df()        # 转回普通 DataFrame
```

## DataTypes 完整列表

共 40 种数据类型，含复权变体。`ts_` 前缀为 tushare 源，`ak_` 前缀为 akshare 源。

### 行情数据

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_DAILY` | `ts_daily` | A 股日线（不复权） |
| `TS_DAILY_QFQ` | `ts_daily_qfq` | A 股日线（前复权） |
| `TS_DAILY_HFQ` | `ts_daily_hfq` | A 股日线（后复权） |
| `TS_WEEKLY` | `ts_weekly` | A 股周线（不复权） |
| `TS_WEEKLY_QFQ` | `ts_weekly_qfq` | A 股周线（前复权） |
| `TS_WEEKLY_HFQ` | `ts_weekly_hfq` | A 股周线（后复权） |
| `TS_MONTHLY` | `ts_monthly` | A 股月线（不复权） |
| `TS_MONTHLY_QFQ` | `ts_monthly_qfq` | A 股月线（前复权） |
| `TS_MONTHLY_HFQ` | `ts_monthly_hfq` | A 股月线（后复权） |
| `TS_DAILY_BASIC` | `ts_daily_basic` | 日线基础指标（换手率、PE、PB 等） |
| `AK_STOCK_ZH_A_SPOT` | `ak_stock_zh_a_spot` | A 股实时行情 |

### 基本面

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_BALANCESHEET` | `ts_balancesheet` | 资产负债表 |
| `TS_INCOME` | `ts_income` | 利润表 |
| `TS_CASHFLOW` | `ts_cashflow` | 现金流量表 |
| `TS_FINA_INDICATOR` | `ts_fina_indicator` | 财务指标（ROE、ROA 等） |
| `TS_FINA_AUDIT` | `ts_fina_audit` | 财务审计意见 |

### 基础信息

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_STOCK_BASIC` | `ts_stock_basic` | 股票基本信息 |
| `TS_TRADE_CAL` | `ts_trade_cal` | 交易日历 |
| `TS_ADJ_FACTOR` | `ts_adj_factor` | 复权因子 |

### 新股与风险警示

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_NEW_SHARE` | `ts_new_share` | 新股列表 |
| `TS_STOCK_ST` | `ts_stock_st` | 风险警示股票 |
| `TS_SUSPEND_D` | `ts_suspend_d` | 停牌信息 |

### 筹码与持仓

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_CYQ_CHIPS` | `ts_cyq_chips` | 筹码分布 |
| `TS_CYQ_PERF` | `ts_cyq_perf` | 筹码穿透率 |
| `TS_STK_HOLDERTRADE` | `ts_stk_holdertrade` | 股东增减持 |
| `TS_TOP10_HOLDERS` | `ts_top10_holders` | 十大股东 |

### 资金流向

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_MONEYFLOW` | `ts_moneyflow` | 个股资金流向 |
| `TS_MONEYFLOW_THS` | `ts_moneyflow_ths` | 同花顺个股资金流向 |
| `TS_MONEYFLOW_CNT_THS` | `ts_moneyflow_cnt_ths` | 同花顺板块资金流向 |
| `TS_MONEYFLOW_IND_THS` | `ts_moneyflow_ind_ths` | 同花顺行业资金流向 |
| `TS_MONEYFLOW_MKT_DC` | `ts_moneyflow_mkt_dc` | 东方财富大盘资金流向 |

### 融资融券

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_MARGIN` | `ts_margin` | 融资融券汇总 |
| `TS_MARGIN_DETAIL` | `ts_margin_detail` | 融资融券明细 |

### 业绩预告与快报

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_EXPRESS` | `ts_express` | 业绩快报 |
| `TS_FORECAST` | `ts_forecast` | 业绩预告 |

### 其他

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_DIVIDEND` | `ts_dividend` | 分红送股 |
| `TS_TOP_LIST` | `ts_top_list` | 龙虎榜每日明细 |
| `TS_TOP_INST` | `ts_top_inst` | 龙虎榜机构明细 |
| `TS_STK_FACTOR_PRO` | `ts_stk_factor_pro` | 技术面专业版（MACD、KDJ 等） |
| `TS_STK_AH_COMPARISON` | `ts_stk_ah_comparison` | AH 股比价 |

## 兼容接口

兼容 tushare 调用风格：

```python
from jh_quant.data.data_providers import tushare as ts

df = ts.daily(ts_code="000001.SZ", start_date="20240101", end_date="20241231")
pro_df = ts.pro.pro_bar(ts_code="000001.SZ", start_date="20240101", end_date="20241231", asset="E", freq="D")
```

兼容 akshare 调用风格：

```python
from jh_quant.data.data_providers import akshare as ak

df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="20240101", end_date="20241231", adjust="qfq")
```

## 常见开发任务

- **新增 DataType**：在 `datatypes.py` 中添加枚举成员，确认 API 端已支持对应数据表
- **修改缓存逻辑**：`jh_data.py` 中的 DuckDB 查询和缓存层
- **数据 schema 转换**：确保输出统一使用英文标准化字段（`open`、`high`、`low`、`close`、`volume`）
