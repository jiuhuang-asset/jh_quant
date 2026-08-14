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

`ts_code` 可传逗号分隔的多个代码，如 `"000001.SZ,600519.SH"`；`get_data` 支持 `fields` 筛选返回列。

## 配置

### API Key

```bash
export JIUHUANG_API_KEY="your-api-key"
export JIUHUANG_API_URL="https://data.jiuhuang.xyz"  # 可选，默认值
```

也可使用项目根目录的 `.env` 文件。

### 数据缓存

首次下载数据后缓存到本地 DuckDB（`~/.jiuhuang/cache_data.db`），后续相同查询直接从本地读取。

#### 清理缓存

```python
# 清空整表
jh.clear_cache(DataTypes.TS_DAILY)

# 按条件删除（start/end、代码列、任意字段等值筛选），返回删除行数
n = jh.delete_cache(DataTypes.TS_DAILY, ts_code="000001.SZ")

# dry-run：统计将删除的行数，不实际删除
n = jh.count_cache(DataTypes.TS_STOCK_BASIC, name="贵州茅台")
```

CLI 命令 `jh-quant del`（用法与 `delete_cache` 一致，整表删除需 `--yes` 确认）：

```bash
jh-quant del ts_daily --yes                      # 清空整表
jh-quant del ts_daily --ts-code 000001.SZ        # 按代码删除
jh-quant del ak_stock_zh_a_hist_qfq --symbol 000001
jh-quant del ts_daily --start 2020-01-01 --end 2020-12-31
jh-quant del ts_stock_basic --field name=贵州茅台 --dry-run   # 预演
```

#### 服务通知与缓存失效

`JHData` 初始化会请求服务端 `/news` 与 `/version`，用**黄色字体**打印服务通知；
若通知涉及**数据变更/远端数据更新**，会提示本地缓存可能已过期 → 用 `jh-quant del <数据类型>`
清理对应缓存后重新下载（下次 `get_data` 自动拉最新数据）。

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

## 常用工具函数

| 函数 | 说明 |
|------|------|
| `get_ts_price_data_type(period, price_adjust)` | 映射 `("M"/"D") + ("qfq"/"hfq"/"none")` → `(DataTypes, already_monthly)`，返回的 DataType 可直接用于 `get_data`；`already_monthly=True` 表示服务端已是月频 |
| `get_code_col(df)` / `get_code_date_col(df)` | 从 DataFrame 推断 code/date 列名 |
| `to_factor_input_frame` / `to_factor_stock_returns_frame` / `to_factor_market_cap_frame` 等 adapter | 把源数据转成因子计算要求的 canonical schema |

## DataTypes 分类

当前**有数据维护**的类型共 **86 个**（含复权变体）。`ts_` 前缀为 tushare 源（`ts_code`/`trade_date`），`ak_` 前缀为 akshare 源（`symbol`/`date`），`jh_` 前缀为 Jiuhuang 本地计算（`symbol`/`date`）。枚举定义中还有其他类型（基金、港股、美股等），但无数据维护，不建议使用。

### 行情数据

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_DAILY` / `TS_DAILY_QFQ` / `TS_DAILY_HFQ` | `ts_daily*` | A 股日线（不复权/前复权/后复权） |
| `TS_WEEKLY` / `TS_WEEKLY_QFQ` / `TS_WEEKLY_HFQ` | `ts_weekly*` | A 股周线 |
| `TS_MONTHLY` / `TS_MONTHLY_QFQ` / `TS_MONTHLY_HFQ` | `ts_monthly*` | A 股月线 |
| `TS_DAILY_BASIC` | `ts_daily_basic` | 日线基础指标（换手率、PE、PB 等） |
| `TS_MONTHLY_BASIC` | `ts_monthly_basic` | 月度基础指标（`ts_daily_basic` 衍生表，每股票每月取当月最后一个交易日，`trade_date` 与月线同约定，数据量约为日线的 1/20，适合月频因子） |
| `AK_STOCK_ZH_A_SPOT` | `ak_stock_zh_a_spot` | A 股实时行情（建议 `bypass_cache=True`） |

### 基本面

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_BALANCESHEET` | `ts_balancesheet` | 资产负债表 |
| `TS_INCOME` | `ts_income` | 利润表 |
| `TS_CASHFLOW` | `ts_cashflow` | 现金流量表 |
| `TS_FINA_INDICATOR` | `ts_fina_indicator` | 财务指标（ROE、ROA 等） |
| `TS_FINA_AUDIT` | `ts_fina_audit` | 财务审计意见 |

### 基础信息 / 新股与风险警示

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_STOCK_BASIC` | `ts_stock_basic` | 股票基本信息 |
| `TS_TRADE_CAL` | `ts_trade_cal` | 交易日历 |
| `TS_ADJ_FACTOR` | `ts_adj_factor` | 复权因子 |
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

### 融资融券 / 业绩预告快报 / 分红 / 龙虎榜 / 技术面

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_MARGIN` / `TS_MARGIN_DETAIL` | `ts_margin*` | 融资融券汇总 / 明细 |
| `TS_EXPRESS` / `TS_FORECAST` | `ts_express` / `ts_forecast` | 业绩快报 / 业绩预告 |
| `TS_DIVIDEND` | `ts_dividend` | 分红送股 |
| `TS_TOP_LIST` / `TS_TOP_INST` | `ts_top_list` / `ts_top_inst` | 龙虎榜每日 / 机构明细 |
| `TS_STK_FACTOR_PRO` | `ts_stk_factor_pro` | 技术面专业版（MACD、KDJ 等） |
| `TS_STK_AH_COMPARISON` | `ts_stk_ah_comparison` | AH 股比价 |

### 因子数据（jh_ 前缀，本地计算）

Jiuhuang 基于 tushare 数据本地计算的**学术因子模型**结果，当前只提供**月频**。每个模型两类表，命名 `jh_factor_{model}_returns_monthly` / `jh_factor_{model}_exposure_monthly`：

| 模型枚举值 | 说明 |
|-----------|------|
| `ff3` `ff5` `carhart` `nm` `hxz` `dhs` `capm` `ch3` `sy4` `reversal` `low_vol` | 对应各因子模型 |

- `date` 为当月最后一个实际交易日（与 `TS_MONTHLY_*` 同约定）；`symbol` 为 `ts_code` 风格。
- 枚举名形如 `JH_FACTOR_FF3_RETURNS_MONTHLY`、`JH_FACTOR_FF3_EXPOSURE_MONTHLY`。

```python
fr = jh.get_data(DataTypes.JH_FACTOR_FF3_RETURNS_MONTHLY, start="2020-01-01", end="2024-12-31")
ex = jh.get_data(DataTypes.JH_FACTOR_FF3_EXPOSURE_MONTHLY, start="2020-01-01", end="2024-12-31")
```

### 同花顺概念板块 / 指数 / 宏观

| 枚举名 | 值 | 说明 |
|--------|-----|------|
| `TS_THS_INDEX` / `TS_THS_MEMBER` / `TS_THS_DAILY` | `ts_ths_*` | 同花顺概念板块指数 / 成分股 / 日线行情 |
| `TS_INDEX_BASIC` | `ts_index_basic` | 指数基本信息 |
| `TS_INDEX_DAILY` | `ts_index_daily` | A 股指数日线（覆盖上证指数、深证成指、沪深300、中证500/1000、上证50、科创50 等 9 个主要指数） |
| `TS_INDEX_GLOBAL` | `ts_index_global` | 国际主要指数日线（标普500、道琼斯等） |
| `TS_SW_DAILY` | `ts_sw_daily` | 申万行业指数日线（默认申万2021版） |
| `TS_INDEX_DAILYBASIC` | `ts_index_dailybasic` | 指数日线基础指标 |
| `TS_DAILY_INFO` | `ts_daily_info` | 交易所股票交易统计 |
| `TS_SHIBOR` | `ts_shibor` | Shibor 利率（隔夜 `on`、1 个月 `f_1m` 等列） |
| `TS_SHIBOR_LPR` / `TS_SHIBOR_QUOTE` | `ts_shibor_lpr` / `ts_shibor_quote` | LPR / Shibor 报价 |
| `TS_LIBOR` / `TS_HIBOR` | `ts_libor` / `ts_hibor` | 伦敦 / 香港同业拆借利率 |
| `TS_CN_GDP` / `TS_CN_CPI` / `TS_CN_PPI` / `TS_CN_M` / `TS_CN_PMI` | `ts_cn_*` | 中国宏观：GDP / CPI / PPI / 货币供应 / PMI |
| `TS_US_TYCR` / `TS_US_TRYCR` / `TS_US_TBR` / `TS_US_TLTR` / `TS_US_TRLTR` | `ts_us_*` | 美国国债收益率曲线与利率 |

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

- **查看全部类型**：遍历 `DataTypes` 打印 `dt.name` / `dt.value`；以 `docs/data/datatypes.md` 的完整列表为准
- **新增 DataType**：在 `data_types.py` 中添加枚举成员，确认 API 端已支持对应数据表
- **修改缓存逻辑**：`jh_data.py` 中的 DuckDB 查询和缓存层
- **数据 schema 转换**：确保输出统一使用英文标准化字段（`open`、`high`、`low`、`close`、`volume`）
