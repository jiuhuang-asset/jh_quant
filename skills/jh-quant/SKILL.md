---
name: "jh-quant"
description: "jh_quant 量化交易平台的开发助手。覆盖数据获取、策略回测、因子计算、模拟/实盘交易、数据同步、可视化仪表盘等全部模块。"
argument-hint: "[task description | module name]"
user-invocable: true
disable-model-invocation: false
context: inline
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
metadata:
  version: "1.0.0"
  tags: [quant, a-share, backtest, trading, factors, finance]
  category: finance
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## 🚨 核心定位

**你是帮助用户「调用 jh_quant 库」的助手，不是「修改 jh_quant 库」的开发者。**

- `jh_quant/` 是已安装的库代码，用户通过 `pip install` 使用。**禁止修改 `jh_quant/` 下的任何文件。**
- 你的工作是：帮助用户编写**独立的新脚本**，import 库的 API 来完成数据获取、策略回测、因子计算等任务。
- 需要新的策略？→ 创建 `my_strategy.py`，import `Strategy` 基类来实现。
- 需要新的因子？→ 创建 `my_factor.py`，import `FactorEngine` 来使用。
- 所有输出都是用户工作目录下的**独立文件**，不触碰库源码。

## 概述

**jh_quant** 是一个 A 股量化交易研究与执行平台，基于 Python 3.10+，通过 `pip install` 安装使用。包含以下模块：

| 模块 | 包路径 | 说明 |
|------|--------|------|
| data | `jh_quant.data` | JHData API 客户端 + DuckDB 本地缓存（可用 `jh-quant del <数据类型>` 清理缓存，服务端 news 通知数据变更时会提示缓存失效） |
| backtest | `jh_quant.backtest` | 回测引擎 + 11 种内置策略 |
| factors | `jh_quant.factors` | 因子引擎 + 11 种因子模型 |
| trading | `jh_quant.trading` | 交易服务编排 + Bootstrap + CLI |
| sync | `jh_quant.trading.sync` | 本地 SQLite → 远程 Postgres 同步 |
| dashboard | `jh_quant.dashboard` | PyWebView 可视化仪表盘 |

## 工作流程

### 1. 识别任务模块

从用户输入中匹配关键词，确定涉及的模块：

| 关键词 | 模块 |
|--------|------|
| 数据、行情、日线、财务、get_data、JHData、DataTypes | data |
| 回测、策略、backtest、trading_history | backtest |
| 因子、FF3、FF5、Carhart、factor、alpha | factors |
| 交易、模拟盘、实盘、paper、live、session、选股 | trading |
| 同步、sync、postgres、neon | sync |
| 仪表盘、dashboard、可视化 | dashboard |
| CLI、jh-quant、命令行 | cli |

### 2. 查阅参考文档

确定模块后，阅读 `references/` 下对应的参考文档获取详细 API 和参数说明：

| 模块 | 参考文档 |
|------|---------|
| 架构/设计模式 | [references/architecture.md](references/architecture.md) |
| 数据获取 | [references/data.md](references/data.md) |
| 策略回测 | [references/backtest.md](references/backtest.md) |
| 因子计算 | [references/factors.md](references/factors.md) |
| 交易服务 | [references/trading.md](references/trading.md) |
| 数据同步 | [references/sync.md](references/sync.md) |
| 仪表盘 | [references/dashboard.md](references/dashboard.md) |
| 常见问题 | [references/faq.md](references/faq.md) |

### 3. 阅读项目代码

阅读对应的源代码理解实现细节。关键入口文件：

- 数据模块：`jh_quant/data/jh_data.py`、`jh_quant/data/datatypes.py`
- 回测模块：`jh_quant/backtest/backtest.py`、`jh_quant/backtest/strategy.py`
- 因子模块：`jh_quant/factors/main.py`（FactorEngine）、`jh_quant/factors/loaders.py`、`jh_quant/factors/factors/`
- 交易模块：`jh_quant/trading/bootstrap.py`、`jh_quant/trading/config.py`
- CLI：`jh_quant/cli/`

## 执行规则

### 编写代码前

1. 阅读 `references/` 下对应模块的参考文档，了解库的 API 用法
2. 阅读 `jh_quant/` 下对应模块的源码（只读），理解基类接口和参数签名
3. 检查项目根目录的 `CLAUDE.md` 了解项目整体结构
4. 如果是复杂任务，先创建 plan 文件：`plan__{目标}_{version}.md`

### 编写代码时

**禁止修改 `jh_quant/` 下的任何文件。** 所有代码写在用户工作目录下的**新文件**中，通过 `from jh_quant.xxx import ...` 调用库。

1. **命名约定**：类用 PascalCase（`StrategyTurtle`），函数/变量用 snake_case（`get_data()`），私有方法前缀 `_`（`_execute_one()`）
2. **自定义策略**：创建独立 `.py` 文件（如 `my_strategy.py`），`from jh_quant.backtest import Strategy`，实现 `_execute_one(self, data)` 方法
3. **自定义选股器**：创建独立 `.py` 文件，继承 `SelectionProvider`，通过 `register_selection_provider()` 注册
4. **注意数据安全**：
   - 避免 Look-Ahead Bias：因子特征值必须在收益期之前已知
   - 回测默认 `use_next_day_return=True`（今日信号→次日收益）
   - 财务数据须包含 `ann_date` 字段用于 PIT 匹配
5. **DataFrame 约定**：`symbol` 为股票代码列，`date` 为日期列；`buy_signal`/`sell_signal` 为 0/1 整数
6. **不要在 `__init__` 中做耗时操作**：策略实例会被 pickle 序列化以支持并行
7. **不要硬编码密钥**：API Key 通过 `JIUHUANG_API_KEY` 环境变量传入

### 编写代码后

1. 运行脚本验证：`python <新脚本>.py`
2. 确认 `import` 全部来自 `jh_quant`，没有修改库文件

## 核心设计模式速览

```
Strategy (backtest)      →  继承 Strategy，实现 _execute_one()，写在独立新文件中
Provider (trading)       →  继承 SelectionProvider / MarketDataProvider 等抽象基类
Builder (trading)        →  SessionServiceConfigBuilder 流式构建配置
DataFrame Wrapper (data) →  _JHDataWrapper 附加 .code_col, .date_col, .jh_dt
```

## 新增策略的标准做法

**❌ 错误**：直接修改 `jh_quant/backtest/strategy.py` 添加新策略类
**✅ 正确**：在项目根目录创建独立文件（如 `my_strategy.py`），从库中导入基类：

```python
# my_strategy.py（新建的独立文件）
from jh_quant.backtest.strategy import Strategy
import pandas as pd

class MyStrategy(Strategy):
    def __init__(self, param1=20):
        super().__init__()
        self.param1 = param1

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        # ... 策略逻辑 ...
        data["buy_signal"] = ...
        data["sell_signal"] = ...
        return data
```

然后在测试脚本中导入使用：
```python
from my_strategy import MyStrategy
strategies = {"我的策略": MyStrategy(param1=30)}
```

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `JIUHUANG_API_KEY` | 数据 API 密钥 | 是 |
| `JIUHUANG_API_URL` | 数据 API 地址（默认 `https://data.jiuhuang.xyz`） | 否 |
| `REMOTE_DB_URL` | Sync 远程 Postgres DSN | 否 |
| `MINIQMT_USERDATA_DIR` | MiniQMT userdata 目录（实盘） | 仅 live |
| `MINIQMT_STOCK_ACCOUNT` | 股票账户号（实盘） | 仅 live |
