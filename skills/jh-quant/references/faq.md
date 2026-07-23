# 常见问题速查 (FAQ)

## 数据获取

### DuckDB 锁竞争

多进程场景下 DuckDB 可能被锁定。

**解决**：设置 `JHData(as_service=True)` 或环境变量 `JHDATA_SERVICE_MODE=1`。

### 数据为空

检查：
- API Key 是否有效（`echo $JIUHUANG_API_KEY`）
- 日期范围是否正确
- 股票代码是否带交易所后缀（`.SH`/`.SZ`/`.BJ`）

### 实时数据

使用 `DataTypes.AK_STOCK_ZH_A_SPOT`，建议 `bypass_cache=True`：

```python
spot = jh.get_data(DataTypes.AK_STOCK_ZH_A_SPOT, bypass_cache=True)
```

## 策略回测

### 策略无交易信号

检查：
- 参数是否过严（如 RSI 阈值 20/80 可能极少触发）
- 数据窗口是否足够大（如 60 日均线需要至少 60 天数据）
- 用 `print(df['buy_signal'].sum())` 检查各股票信号数量

### 回测结果为 NaN

- 检查数据是否有缺失值
- 确保使用 `use_next_day_return=True`（避免未来信息）

### 多股票并行注意事项

- 策略不要修改全局状态
- `_execute_one` 必须返回独立副本（`df.copy()`）
- 不要在 `__init__` 中执行耗时操作

## 因子计算

### Schema 拦截：缺少 ann_date

财务字段必须包含 `ann_date`。如果是自行准备数据，确保财务 DataFrame 包含该列。推荐使用 `load_ts_factor_inputs()` 自动处理。

### 特征滞后（lag_features）

`load_ts_factor_inputs()` 默认 `lag_features=True`，将特征值滞后一收益期。这确保特征值在收益期之前已知，避免 look-ahead bias。

### 计算太慢

尝试：
- 确保 `use_polars=True`（默认已启用）
- 限制股票范围：`symbols=["000001.SZ", "600519.SH"]`
- 使用 `CalculationMethod.SIMPLE`（比 CLASSIC 快很多）
- 减少 `n_jobs` 可能反而更快（避免多进程开销）

## 交易

### 实盘连接失败

检查 MiniQMT 环境变量：
```bash
echo $MINIQMT_USERDATA_DIR
echo $MINIQMT_STOCK_ACCOUNT
```

### session 不启动

- 检查 `auto_start=True`
- 检查 cron 表达式格式是否正确（5 段式）
- 查看日志确认是否有异常

### Dashboard 空白/加载失败

- 确认 API 服务已启动：`curl http://127.0.0.1:8000/docs`
- 端口是否一致（默认 8000）
- 网络防火墙是否阻止了本地连接

### 如何查看可用策略和风控规则

```python
from jh_quant.trading.config import list_strategy_definitions, list_risk_rule_definitions

for s in list_strategy_definitions():
    print(f"{s.name}: {s.description}")

for r in list_risk_rule_definitions():
    print(f"{r.name}: {r.description}")
```

## 数据同步

### 连接失败

检查：
- `REMOTE_DB_URL` 格式是否正确（`postgresql://user:pass@host/db`）
- Neon 项目是否已创建
- 网络是否能访问远程数据库

### 如何从头全量同步

```bash
jh-quant sync --from trade_paper.db --full-reset --yes-i-know
```

这会 TRUNCATE 远程所有表，然后全量重新灌入，水印也会重置。

### 只同步部分表

```bash
jh-quant sync --from trade_paper.db --tables trades,daily_performances
```

### 日志不详细

```bash
jh-quant sync --from trade_paper.db --log-level DEBUG
```

## 环境配置

### 在何处放置 .env 文件

项目根目录或当前工作目录均可。格式：
```
JIUHUANG_API_KEY=your-key
JIUHUANG_API_URL=https://data.jiuhuang.xyz
```

### 多项目/多环境切换

通过设置不同的环境变量或使用不同的 `.env` 文件：
```bash
JIUHUANG_API_KEY=key1 jh-quant paper --db-path project1.db
JIUHUANG_API_KEY=key2 jh-quant paper --db-path project2.db
```
