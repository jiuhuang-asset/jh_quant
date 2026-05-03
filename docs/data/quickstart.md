# 快速开始

## 安装

```bash
pip install jh-quant
```

jh_quant 依赖 `duckdb`、`pandas`、`httpx`、`rich` 等包，pip 会自动安装这些依赖。

## 配置

### API Key

使用 JHData 需要 JiuHuang API Key。通过环境变量配置：

```bash
export JIUHUANG_API_KEY="your-api-key"
```

API URL 默认指向 `https://data.jiuhuang.xyz`，如需自定义：

```bash
export JIUHUANG_API_URL="https://your-custom-url"
```

也可以使用 `.env` 文件（项目根目录或当前工作目录），jh_quant 会在初始化时自动加载：

```
JIUHUANG_API_KEY=your-api-key
JIUHUANG_API_URL=https://data.jiuhuang.xyz
```

### 缓存目录

JHData 会在 `~/.jiuhuang/` 下创建 DuckDB 缓存数据库 `cache_data.db`。首次下载数据后会缓存到本地，后续相同查询直接从本地读取。

## 基本用法

### 初始化 JHData

```python
from jh_quant.data import JHData

# 自动从环境变量读取 api_key 和 api_url
jh = JHData()

# 或显式指定参数
jh = JHData(
    api_key="your-api-key",
    api_url="https://data.jiuhuang.xyz",
)
```

### DuckDB 并发说明

如果多个进程同时使用 JHData，DuckDB 数据库可能被锁定。JHData 会自动检测并切换到 **DuckDB 服务模式**：

- **默认模式（auto）**：先尝试直接连接 DuckDB，失败则自动启动服务模式
- **强制服务模式**：`JHData(as_service=True)` — 通过 HTTP 服务访问缓存
- **强制直连模式**：`JHData(as_service=False)` — 直接连接 DuckDB 文件

```python
# 多进程场景，推荐显式指定服务模式
jh = JHData(as_service=True)
```

一般情况下不需要关心这个参数，自动模式已经能覆盖绝大多数场景。

### 获取数据

```python
from jh_quant.data import JHData, DataTypes

jh = JHData()

# 获取 A 股日线数据（前复权）
df = jh.get_data(
    DataTypes.AK_STOCK_ZH_A_HIST_QFQ,
    symbol="000001",
    start="2024-01-01",
    end="2024-12-31",
)
print(df.head())
```

输出为一个 pandas DataFrame，包含 `symbol`、`date`、`open`、`high`、`low`、`close`、`volume` 等标准字段。

### DataFrame 便捷属性

返回的 DataFrame 经过了包装，可以方便地获取 code 列和 date 列名：

```python
df = jh.get_data(DataTypes.AK_STOCK_ZH_A_HIST_QFQ, symbol="000001")

# 获取 code 列名
print(df.code_col)      # "symbol"

# 获取 date 列名
print(df.date_col)      # "date"

# 同时获取两者
print(df.code_date_col) # ("symbol", "date")

# 查看数据类型
print(df.jh_dt)         # DataTypes.AK_STOCK_ZH_A_HIST_QFQ

# 转回普通 DataFrame
plain_df = df.to_df()
```

这些属性会根据数据来源自动适配 — akshare 数据返回 `symbol`/`date`，tushare 数据返回 `ts_code`/`trade_date`。

## 下一步

- 了解如何使用 [DataTypes](./datatypes.md) 选择数据类型
- 深入理解 [get_data 方法](./get-data.md) 的各项参数
- 查看 [akshare/tushare 兼容接口](./compatibility.md)
