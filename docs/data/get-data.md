# get_data 详解

`JHData.get_data()` 是 jh_quant.data 最核心的方法，提供统一的数据获取体验。本章详细介绍其所有功能和参数。

## 方法签名

```python
def get_data(
    self,
    data_type: DataTypes,
    remote: bool = False,
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

### 时间参数与分片下载

当数据量超过 **50 万条**（`SMALL_DOWNLOAD_THRESHOLD`）时，提供 `start` 和 `end` 参数会自动启用分片下载：

1. 系统将时间范围递归二分（先按年、再按月切分）
2. 每个子范围独立下载并增量写入缓存
3. 最终合并返回完整数据

这意味着获取大量数据时**不需要额外代码**，框架会自动处理分片。

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
    symbol="000001,000002,000004,...,688981",  # 成千上万个标的
    start="2024-01-01",
    end="2024-12-31",
)
```

## 缓存机制

### 缓存存储

JHData 使用 **DuckDB** 在 `~/.jiuhuang/cache_data.db` 中维护本地缓存。每种数据类型对应数据库中的一张表。

### 缓存命中逻辑

调用 `get_data()` 时的默认行为：

1. **查询远程总数**：先调用 API 获取符合条件的数据总量
2. **比较本地缓存**：查询本地缓存中符合条件的记录数
3. **缓存命中**：本地数量 == 远程数量 → 直接返回缓存数据，**不发起网络请求**
4. **缓存过期**：本地数量 > 远程数量 → 清除缓存表后重新下载（远程数据始终是权威来源）
5. **缓存未命中**：本地数量 < 远程数量 → 从 API 下载数据，写入缓存

```
总览：
  get_data(remote=False)
    |
    +-- 远程总数 vs 本地缓存数
          |
          +-- 相等 → 命中缓存，直接返回
          +-- 缓存更多 → 清除缓存，重新下载
          +-- 缓存更少 → API 下载，写入缓存
```

### 跳过缓存（强制远程）

如果需要强制从 API 获取最新数据，设置 `remote=True`：

```python
# 强制从远程下载，忽略缓存
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2024-01-01",
    end="2024-12-31",
    remote=True,
)
```

### 表结构初始化

首次查询某数据类型时，系统会自动从 API 获取 DDL（建表语句），在 DuckDB 中创建对应的缓存表。整个过程对用户透明。

### 数据导入（Upsert）

下载的数据通过 **upsert** 方式写入缓存表：基于唯一键（如 `(date, symbol)`）判断数据是否已存在，存在则更新，不存在则插入。这确保了：

- 更新已有数据不会产生重复行
- 增量数据自动合并

### 手动清除缓存

```python
# 清除某个数据类型的全部缓存
jh.clear_cache(DataTypes.AK_STOCK_ZH_A_HIST_QFQ)
```

## remote 参数

| `remote` 值 | 行为 |
|-------------|------|
| `False`（默认） | 优先使用本地缓存，缓存未命中时才从 API 下载 |
| `True` | 跳过缓存检查，强制从 API 下载数据 |

**注意**：当 `remote=True` 时，数据仍然会**写入缓存**，只是不会读取缓存来跳过下载。

## 大数量下载与自动分片

### 阈值

当远程数据量超过 **50 万条**（`SMALL_DOWNLOAD_THRESHOLD`），系统会自动分片：

1. **时间分片**：如果有 `start` 和 `end` 参数，按年/月递归二分
2. **标的分片**：如果 `symbol`/`ts_code` 是逗号分隔的列表，二分标的列表
3. **不可分片**：如果以上条件都不满足且数据量超阈值，抛出 `MemoryError`

### 分片下载流程

```
_fetch_recursive()
  |
  +-- total <= 500,000 → _download_single() → bulk_import → 返回
  |
  +-- total > 500,000 → _bisect_payload()
        |
        +-- 按 start/end 二分，或按 symbol 列表二分
        |
        +-- for each sub_payload:
              +-- 检查缓存是否已覆盖 → 跳过
              +-- _fetch_recursive(sub_payload, sub_total)  # 递归
        |
        +-- pd.concat(all_parts)
```

### 增量写入

大数据下载使用流式处理 + 增量写入。每 **5 万条**（`INCREMENTAL_BATCH_SIZE`）写入一次缓存，避免内存中积累过多数据。

## 进度显示

下载过程中会显示 Rich 进度条，包含：

- 当前下载的数据类型
- 进度百分比
- 预计剩余时间

```
Downloading ak_stock_zh_a_hist_qfq... ━━━━━━━━━━━━ 45% 0:00:03
```

分片下载时，还会显示每个子加载范围：

```
  sub range: {'start': '2024-01-01', 'end': '2024-06-30'}
  sub range: {'start': '2024-07-01', 'end': '2024-12-31'}
```

已缓存的子加载范围会被跳过并显示绿色提示：

```
  cache hit, skip: {'start': '2023-01-01', 'end': '2023-06-30'}
```

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
    start="2020-01-01",
    end="2024-12-31",
    remote=True,
)
```
