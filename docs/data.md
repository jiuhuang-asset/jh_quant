# jh_quant.data

数据获取模块，同时兼容**akshare**、**tushare**数据接口，提供统一的数据获取体验。

- **数据源**: JiuHuang API, 兼容**akshare**, **tushare**
- **缓存**: 使用duckdb本地缓存, 实现增量同步
- **统一接口**: 通过 `DataTypes` 枚举类管理数据类型，输出字段名标准化为英文

## 快速开始

### JHData 直接获取

```python
from jh_quant.data import JHData, DataTypes

jh = JHData()

# 获取股票日线数据（前复权）
stock_price = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2025-01-01",
    end="2025-01-10",
)
print(stock_price)
```

### akshare 兼容接口

```python
from jh_quant.data.data_providers import akshare as ak

stock_price = ak.stock_zh_a_hist(
    symbol="000001",
    start_date="20250101",
    end_date="20250110",
    adjust="qfq"
)
```

### tushare 兼容接口

```python
from jh_quant.data.data_providers import tushare as ts

daily_data = ts.daily(
    ts_code="000001.SZ",
    start_date="20250101",
    end_date="20250110"
)
```

## 主要功能

### 数据类型

通过 `DataTypes` 枚举访问所有支持的数据类型：

```python
from jh_quant.data import DataTypes

# 股票数据
DataTypes.AK_STOCK_ZH_A_HIST_QFQ  # 日线（前复权）
DataTypes.AK_STOCK_INDIVIDUAL_INFO_EM  # 股票基本信息

# 基金、宏观等多类型数据...
```

### 缓存机制

JHData 内置DuckDB缓存，相同查询不会重复请求API：

```python
jh = JHData()
# 首次调用从API获取并缓存
data = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001")
# 后续调用直接从缓存读取
```

## 核心类

### `JHData`

主数据获取类

```python
jh = JHData(api_key="...", api_url="...")
data = jh.get_data(data_type, symbol="...", start="...", end="...")
```

### `DataTypes`

枚举类，定义所有支持的数据类型。位于 `data_types.py`（自动从JHData服务同步）。

### 数据提供器

- `data_providers.akshare` - akshare风格接口
- `data_providers.tushare` - tushare风格接口
- `data_providers.reverse_ak()` / `data_providers.reverse_ts()` - 反向映射
- `data_providers.process_ak()` / `data_providers.process_ts()` - 数据处理
