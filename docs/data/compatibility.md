# akshare / tushare 兼容接口

jh_quant.data 提供了对 **akshare** 和 **tushare** 风格的兼容层，使得原有使用这两个库的代码可以**几乎零修改**地迁移到 JiuHuang 数据服务，同时享受本地缓存和统一接口的便利。

## 快速对比

| 特性 | jh_quant.data | 原生 akshare / tushare |
|------|---------------|---------------------|
| 数据源 | JiuHuang API | 东方财富 / 各券商 |
| 本地缓存 | 内置 DuckDB | 无 |
| 字段命名 | 可切换到中文/英文 | 中文（ak） / 英文（ts） |
| API Key | 需要 | akshare 不需要，tushare 需要 |
| 返回格式 | JhDataType（可当 DataFrame 用） | DataFrame |

## akshare 兼容接口

### 导入

```python
from jh_quant.data.data_providers import akshare as ak
```

或者通过顶层导入：

```python
from jh_quant.data import akshare as ak
```

akshare 实例在模块加载时自动创建，首次调用方法时会懒初始化 JHData 连接。

### 使用方式

兼容接口通过动态方法分发实现，调用方式与原生 akshare **完全相同**：

```python
# 获取 A 股日线（前复权）
df = ak.stock_zh_a_hist(
    symbol="000001",
    period="daily",
    start_date="20240101",
    end_date="20241231",
    adjust="qfq",
)
```

akshare 兼容接口会自动：
1. 将 `start_date`/`end_date` 标准化为 `YYYY-MM-DD` 格式（同时兼容 `YYYYMMDD` 格式输入）
2. 根据方法名和 `adjust` 参数查找对应的 `DataTypes`
3. 调用 JHData 获取数据
4. 将返回的数据反向还原为 akshare 的中文字段名和日期格式

### 参数映射

| akshare 参数 | 映射到 JHData 参数 | 说明 |
|-------------|-------------------|------|
| `start_date` | `start` | 自动标准化日期格式 |
| `end_date` | `end` | 自动标准化日期格式 |
| `symbol` | `symbol` | 直接传递 |
| `adjust` | （转换到 DataType） | `"qfq"` → `AK_STOCK_ZH_A_HIST_QFQ` |
| `period` | — | 仅支持 `"daily"`，指定其他值会报错 |

### 数据格式

兼容接口返回的 DataFrame 保留了原始的**中文字段名**，与原生 akshare 完全一致：

```python
df = ak.stock_zh_a_hist(symbol="000001", start_date="20240101", end_date="20240110", adjust="qfq")
print(df.columns)
# Index(['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率'], ...)
```

返回结果依然是 `JhDataType`，可以使用 `to_df()`、`code_col` 等属性。

### 支持的方法

所有 `ak_` 前缀的 DataTypes 都有对应的 akshare 兼容方法。例如：

```python
# 实时行情
df = ak.stock_zh_a_spot_em()

# ETF 历史
df = ak.fund_etf_hist_em(symbol="510050", start_date="20240101", end_date="20241231")

# 个股资金流向
df = ak.stock_individual_fund_flow(stock="000001")

# 利润表
df = ak.stock_lrb_em(symbol="000001", date="20241231")

# 资产负债表
df = ak.stock_zcfz_em(symbol="000001", date="20241231")

# 现金流量表
df = ak.stock_xjll_em(symbol="000001", date="20241231")

# CPI
df = ak.macro_china_cpi()

# PMI
df = ak.macro_china_pmi()

# GDP
df = ak.macro_china_gdp()
```

### 暂不支持的方法

如果调用的 akshare 方法尚未被 JiuHuang 覆盖，会抛出 `NotSupportedError`：

```python
>>> df = ak.some_unsupported_method()
NotSupportedError: API not supported yet: `some_unsupported_method`
```

## tushare 兼容接口

### 导入

```python
from jh_quant.data.data_providers import tushare as ts
```

或：

```python
from jh_quant.data import tushare as ts
```

### 两种调用方式

兼容层同时支持 tushare 的两种调用风格：

**方式一：直接调用（推荐）**

```python
df = ts.daily(
    ts_code="000001.SZ",
    start_date="20240101",
    end_date="20241231",
)
```

`tushare.xxx()` 会自动代理到 `tushare.pro.xxx()`。

**方式二：pro 对象调用**

```python
df = ts.pro.daily(
    ts_code="000001.SZ",
    start_date="20240101",
    end_date="20241231",
)
```

与原生 tushare `pro = ts.pro_api(); pro.daily(...)` 风格完全一致。

### 参数映射

| tushare 参数 | 映射到 JHData 参数 | 说明 |
|-------------|-------------------|------|
| `start_date` | `start` | 自动标准化日期格式 |
| `end_date` | `end` | 自动标准化日期格式 |
| `ts_code` | `ts_code` | 直接传递（如 `000001.SZ`） |
| `trade_date` | `trade_date` | 自动标准化日期格式 |
| `fields` | `fields` | 直接传递 |

### pro_bar 方法

兼容层提供了 `pro_bar()` 方法的完整实现：

```python
df = ts.pro.pro_bar(
    ts_code="000001.SZ",
    start_date="20240101",
    end_date="20241231",
    asset="E",   # E=股票
    freq="D",    # D=日线, W=周线, M=月线
)
```

| `asset` + `freq` | 对应 DataType |
|------------------|---------------|
| `E` + `D` | `TS_DAILY` |
| `E` + `W` | `TS_WEEKLY` |
| `E` + `M` | `TS_MONTHLY` |

### 数据格式

tushare 兼容接口返回的 DataFrame 保留了 tushare 的数据格式：

- 日期列格式为 `YYYYMMDD`（如 `20240101`）
- `ts_code` 格式为 `代码.交易所`（如 `000001.SZ`）

返回结果依然是 `JhDataType`，支持 `to_df()`、`code_col` 等属性。

### 支持的方法

所有 `ts_` 前缀的 DataTypes 都有对应的 tushare 兼容方法。例如：

```python
# 日线行情
df = ts.daily(ts_code="000001.SZ")

# 日线（前复权）
df = ts.daily_qfq(ts_code="000001.SZ")

# 周线 / 月线
df = ts.weekly(ts_code="000001.SZ")
df = ts.monthly(ts_code="000001.SZ")

# 每日指标
df = ts.daily_basic(ts_code="000001.SZ")

# 股票基本信息
df = ts.stock_basic()

# 利润表 / 资产负债表 / 现金流量表
df = ts.income(ts_code="000001.SZ")
df = ts.balancesheet(ts_code="000001.SZ")
df = ts.cashflow(ts_code="000001.SZ")

# 财务指标
df = ts.fina_indicator(ts_code="000001.SZ")

# 分红送股
df = ts.dividend(ts_code="000001.SZ")

# 指数日线
df = ts.index_daily(ts_code="000001.SH")

# 龙虎榜
df = ts.top_list(trade_date="20240101")
```

## 数据格式转换函数

### reverse_ak / process_ak

```python
from jh_quant.data import reverse_ak, process_ak

# JHData 返回的数据 → akshare 格式（中文字段名 + 原始日期格式）
ak_format = reverse_ak(df)

# akshare 格式 → JHData 标准格式（英文字段名 + 标准化日期）
standard = process_ak(df)
```

### reverse_ts / process_ts

```python
from jh_quant.data import reverse_ts, process_ts

# JHData 返回的数据 → tushare 格式（YYYYMMDD 日期）
ts_format = reverse_ts(df)

# tushare 格式 → JHData 标准格式（YYYY-MM-DD 日期）
standard = process_ts(df)
```

### 用法场景

```python
from jh_quant.data import JHData, DataTypes
from jh_quant.data import process_ak, reverse_ts

jh = JHData()

# 场景：获取标准格式数据，然后转为 tushare 格式
df = jh.get_data(DataTypes.TS_DAILY, ts_code="000001.SZ")
ts_style = reverse_ts(df)  # 日期变回 20240101

# 场景：获取标准格式数据，然后转为 akshare 格式
df = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001")
ak_style = reverse_ak(df)  # 列名变回中文
```

## 代码转换工具

```python
from jh_quant.data.utils import ak_symbol_to_ts_code, ts_code_to_ak_symbol

# akshare symbol → tushare ts_code
print(ak_symbol_to_ts_code("000001"))   # 000001.SZ
print(ak_symbol_to_ts_code("600519"))   # 600519.SH

# tushare ts_code → akshare symbol
print(ts_code_to_ak_symbol("000001.SZ"))  # 000001
print(ts_code_to_ak_symbol("600519.SH"))  # 600519
```

## 自定义 JHData 实例

默认的 `akshare` 和 `tushare` 全局实例使用自动配置的 JHData。如果需要自定义（如指定不同的 API Key），可以使用 `init_wrappers()`：

```python
from jh_quant.data.data_providers import init_wrappers
from jh_quant.data import JHData

# 用自定义 JHData 实例初始化兼容接口
jh = JHData(api_key="custom-key")
init_wrappers(jh)

# 现在 akshare 和 tushare 都使用这个 JHData 实例来获取数据
```

## 从原生库迁移

### 从 akshare 迁移

```python
# 原代码
# import akshare as ak
# df = ak.stock_zh_a_hist(symbol="000001", period="daily",
#                         start_date="20240101", end_date="20241231", adjust="qfq")

# 迁移后（只需修改 import）
from jh_quant.data.data_providers import akshare as ak
df = ak.stock_zh_a_hist(symbol="000001", period="daily",
                        start_date="20240101", end_date="20241231", adjust="qfq")
# 其余代码无需修改！
```

### 从 tushare 迁移

```python
# 原代码
# import tushare as ts
# pro = ts.pro_api("your-token")
# df = pro.daily(ts_code="000001.SZ", start_date="20240101", end_date="20241231")

# 迁移后
from jh_quant.data.data_providers import tushare as ts
df = ts.daily(ts_code="000001.SZ", start_date="20240101", end_date="20241231")
# 无需 token！数据通过 JiuHuang API Key 授权
```

## 注意事项

1. **period 限制**：akshare 兼容接口目前仅支持 `period="daily"`（日线），传其他值会报错
2. **adjust 参数**：复权方式通过 `adjust` 参数指定（`"qfq"`、`"hfq"`），不使用 `period` 控制
3. **日期格式**：兼容接口自动处理日期格式转换，输入 `YYYYMMDD` 或 `YYYY-MM-DD` 都可以
4. **方法覆盖**：仅 DataTypes 中定义的数据类型有对应兼容方法，未覆盖的方法会抛出 `NotSupportedError`
5. **懒加载**：兼容接口实例在首次调用方法时才初始化 JHData 连接，不会在 import 时触发缓存访问
