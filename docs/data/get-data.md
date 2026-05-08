# get_data 详解

`JHData.get_data()` 是 jh_quant.data 最核心的方法，提供统一的数据获取体验。本章详细介绍其所有功能和参数。

## 方法签名

```python
def get_data(
    self,
    data_type: DataTypes,
    bypass_cache: bool = False,
    **kwargs,
) -> JhDataType  # 包装了 pd.DataFrame
```

## 时间参数（start / end）

### 基本用法

通过 `start` 和 `end` 参数指定数据的时间范围：

```python
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2024-01-01",
    end="2024-12-31",
)
```

### 支持的时间颗粒度

系统会根据数据提供方自动验证日期格式：

| 日期格式 | 示例 | 适用数据源 |
|----------|------|-----------|
| `YYYY-MM-DD` | `"2024-01-01"` | 所有数据源 |
| `YYYY-MM` | `"2024-01"` | `ak_` 数据源 |
| `YYYY-MM-DD HH:MM:SS` | `"2024-01-01 09:30:00"` | `ak_` 分钟线 |

- **akshare 源**（`ak_` 前缀）：支持三种格式，可灵活使用日、月、精确时间
- **tushare 源**（`ts_` 前缀）：仅支持 `YYYY-MM-DD` 格式
- **JiuHuang 源**（`jh_` 前缀）：仅支持 `YYYY-MM-DD` 格式

如果传入的日期格式不匹配，会抛出 `ValueError` 并提示正确格式。

```python
# 按月查询宏观经济数据
df = jh.get_data(
    DataTypes.AK_MACRO_CHINA_CPI,
    start="2024-01",
    end="2024-12",
)
```


## symbol 参数

### 单个标的

```python
df = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001")
```

### 批量查询（逗号分隔）

`symbol` 支持逗号分隔多个标的，一次请求获取多只股票数据：

```python
# 批量获取多只股票日线
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519,300750",
    start="2024-01-01",
    end="2024-12-31",
)
```

底层会将逗号分隔的值转换为 SQL `IN (...)` 条件，一次查询返回所有标的的数据。

同样的机制也适用于 tushare 源的 `ts_code` 参数：

```python
# tushare 源批量查询
df = jh.get_data(
    DataTypes.TS_DAILY_QFQ,
    ts_code="000001.SZ,600519.SH,300750.SZ",
    start="2024-01-01",
    end="2024-12-31",
)
```

### symbol 格式

- **akshare 源**：纯数字代码，如 `"000001"`、`"600519"`
- **tushare 源**：带交易所后缀，如 `"000001.SZ"`、`"600519.SH"`
- symbol 长度不能超过 12 个字符

### 批量分片

当 symbol 列表很长时，系统也会自动将列表二分，分批下载后合并：

```python
# 大批量标的会自动分片
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,000002,000004,...,688981",  # 多个标的
    start="2024-01-01",
    end="2024-12-31",
)
```

## 缓存机制
### 缓存命中逻辑

调用 `get_data()` 时的默认行为：

1. **查询远程总数**：先调用 API 获取符合条件的数据总量
2. **比较本地缓存**：查询本地缓存中符合条件的记录数
3. **缓存命中**：本地数量 == 远程数量 → 直接返回缓存数据，**不发起网络请求**
4. **缓存过期**：本地数量 > 远程数量 → 清除缓存表后重新下载（远程数据始终是权威来源）
5. **缓存未命中**：本地数量 < 远程数量 → 从 API 下载数据，写入缓存


### 跳过缓存（强制远程）

如果需要强制从 API 获取最新数据，设置 `bypass_cache=True`：

```python
# 强制从远程下载，绕过缓存
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2024-01-01",
    end="2024-12-31",
    bypass_cache=True,
)
```
> 对于实时数据, 比如`DataTypes.AK_STOCK_ZH_A_SPOT`， 建议使用bypass_cache=True

### 表结构初始化

首次查询某数据类型时，系统会自动从 API 获取 DDL（建表语句），在 DuckDB 中创建对应的缓存表。整个过程对用户透明。

### 手动清除缓存

```python
# 清除某个数据类型的全部缓存
jh.clear_cache(DataTypes.AK_STOCK_ZH_A_HIST_QFQ)
```

## bypass_cache 参数

| `bypass_cache` 值 | 行为 |
|-------------|------|
| `False`（默认） | 优先使用本地缓存，缓存未命中时才从 API 下载 |
| `True` | 跳过缓存检查，强制从 API 下载数据，并直接返回远程结果 |

**注意**：当 `bypass_cache=True` 时，数据不会读写本地缓存；只有 `bypass_cache=False` 才会使用缓存命中和写回。


## 返回值

`get_data()` 返回 `JhDataType`（即 `_JHDataWrapper`），一个包装了 `pd.DataFrame` 的对象：

```python
df = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001")

# 和普通 DataFrame 一样使用
print(df.head())
print(df["close"].mean())

# 额外的便捷属性
print(df.jh_dt)          # DataTypes.AK_STOCK_ZH_A_HIST_QFQ
print(df.code_col)       # "symbol"
print(df.date_col)       # "date"
print(df.code_date_col)  # ("symbol", "date")

# 转回普通 DataFrame
plain = df.to_df()
```

## get_data_total（预查数据量）

在正式下载前查看数据总量，避免拉取过多数据：

```python
# 预查数据量
total = jh.get_data_total(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2020-01-01",
    end="2024-12-31",
)
print(f"共 {total} 条数据")

if total < 100000:
    df = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001",
                     start="2020-01-01", end="2024-12-31")
```

## 完整示例

```python
from jh_quant.data import JHData, DataTypes

jh = JHData()

# 1. 先看看数据量
total = jh.get_data_total(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519",
    start="2020-01-01",
    end="2024-12-31",
)
print(f"预计获取 {total} 条数据")

# 2. 获取数据（优先缓存）
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519",
    start="2020-01-01",
    end="2024-12-31",
)

# 3. 使用数据
print(f"获取到 {len(df)} 条数据")
print(f"code 列: {df.code_col}, date 列: {df.date_col}")
print(df.groupby("symbol")["close"].describe())

# 4. 强制刷新
df_fresh = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001,600519",
    start="2024-12-01",
    end="2024-12-31",
    bypass_cache=True,
)
```
