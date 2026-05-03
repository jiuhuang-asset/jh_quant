# 计算方法详解

框架提供两种因子计算方法 — **SIMPLE**（简化）和 **CLASSIC**（经典），以及多层级的性能优化选项。

## SIMPLE vs CLASSIC

| 维度 | SIMPLE（默认） | CLASSIC |
|------|---------------|---------|
| 分组方法 | 中位数二分 | 分位数断点（如 30%/70%） |
| 组合加权 | 等权平均 | 市值加权 |
| 分组维度 | 单变量独立排序 | 多变量独立排序 (2x3 等) |
| 计算速度 | 快 | 较慢 |
| 学术严谨性 | 一般 | 接近学术论文实现 |
| 适用场景 | 日常更新、快速迭代 | 研究严谨性要求高的场景 |

### SIMPLE 方法

每个因子按对应变量独立排序后二分（high / low），做多高组、做空低组：

```
smb = 小市值股票等权均值 - 大市值股票等权均值
hml = 高 BM 股票等权均值 - 低 BM 股票等权均值
```

优点：速度快、逻辑直观，适合快速验证和日常更新。

```python
# SIMPLE 是默认方法
ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    method='simple',  # 可省略，为默认值
)
```

### CLASSIC 方法

参考学术论文的经典实现：

- **分组**：按分位数断点（如 30%/70%）将股票分为 3 组（low/medium/high）
- **加权**：组合内按市值加权计算收益率
- **计算**：通过多维度交叉组合构建因子

以 FF3 CLASSIC 为例：

```
Size 分组: small（市值 <= 中位数）/ big（> 中位数）
Value 分组: low (bottom 30%) / medium / high (top 30%)

6个交叉组合的市值加权收益率:
  S/L S/M S/H  B/L B/M B/H

SMB = (S/L + S/M + S/H)/3 - (B/L + B/M + B/H)/3
HML = (S/H + B/H)/2 - (S/L + B/L)/2
```

```python
# 使用 CLASSIC 方法
ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    method='classic',
)
```

不同模型在 CLASSIC 下的分组配置：

| 模型 | 排序维度 | 分组断点 |
|------|---------|---------|
| FF3 | size(50%), bm(30%/70%) | 2x3 |
| FF5 | size(50%), bm(30%/70%), op(30%/70%), inv(30%/70%) | 2x3x3x3 |
| Carhart | size(50%), bm(30%/70%), momentum(30%/70%) | 2x3x3 |
| Novy-Marx | size(50%), bm_adj(30%/70%), gp_a(30%/70%), momentum(30%/70%) | 2x3 |
| HXZ | size(50%), asset_growth(30%/70%), roe(30%/70%) | 2x3x3 |
| DHS | size(50%), pead(30%/70%), fin(30%/70%) | 2x3 |
| SY4 | size(50%), mgmt(20%/80%), perf(20%/80%) | 2x5x5 |
| Reversal | size(50%), rev(30%/70%) | 2x3 |
| Low Vol | size(50%), ivol(30%/70%) | 2x3 |

## 日频 vs 月频

```python
# 月度因子（默认）
ff3_m = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    period='M',  # 或 TimePeriod.MONTHLY
)

# 日度因子
ff3_d = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    period='D',  # 或 TimePeriod.DAILY
)
```

| 方面 | 月频 | 日频 |
|------|------|------|
| 数据量 | 少（~120个月/10年） | 多（~2500日/10年） |
| 计算速度 | 快 | 较慢 |
| 噪音 | 较低 | 较高（需考虑微观结构） |
| 适用场景 | 资产定价研究、组合选择 | 高频回测、事件研究 |

日度计算默认启用 Polars 加速以获得更好性能。

## 性能优化

### Polars 加速

`use_polars=True`（默认）使用 Polars 的向量化操作替代 pandas 逐行计算，大幅提升日度因子计算速度：

```python
# 启用 Polars（默认）
ff5 = engine.calculate_factor_returns(
    factor_type=FactorType.FF5,
    use_polars=True,
)

# 禁用（使用纯 pandas）
ff5 = engine.calculate_factor_returns(
    factor_type=FactorType.FF5,
    use_polars=False,
)
```

Polars 使用线程并行，pandas 使用进程并行。如果遇到内存问题，可以尝试 `use_polars=False`。

### 并行任务数

`n_jobs` 控制并行计算的 worker 数量：

```python
# 自动检测（默认，最多 4 核）
ff3 = engine.calculate_factor_returns(factor_type=FactorType.FF3)

# 单线程（调试用）
ff3 = engine.calculate_factor_returns(factor_type=FactorType.FF3, n_jobs=1)

# 指定核数
ff3 = engine.calculate_factor_returns(factor_type=FactorType.FF3, n_jobs=8)
```

默认值：`min(cpu_count, 4)`。对于日度数据（日期多、单日数据少），多线程效果好；对于月度数据，收益一般。

## 数据过滤

计算过程中会自动执行以下过滤：

1. **收益过滤**：排除 `return <= -1` 或 `return >= 10` 的异常值
2. **缺失值处理**：NA 值归入 "low" 组
3. **最小股票数**：单日可用股票 < 20 只时跳过该日期
4. **财报匹配**：仅使用 `ann_date` 已知且不超过 6 个月的财报数据

## 无风险利率

框架支持传入 SHIBOR 作为无风险利率（用于计算超额收益）：

```python
ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    ...
    # risk_free_rate 通过 data provider 自动获取
)
```

- **月度计算**：使用 1 个月期 SHIBOR，转为月度利率（`rf = m1_rate / 100 / 12`）
- **日度计算**：使用隔夜 SHIBOR，转为日度利率（`rf = on_rate / 100 / 360`）

## 限定标的范围

通过 `symbols` 参数限定计算范围（如仅计算沪深300成分股）：

```python
hs300_stocks = ['000001', '000002', ..., '688981']

ff3 = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    symbols=hs300_stocks,
    start_date='2020-01-01',
    end_date='2024-12-31',
)
```

限定范围后因子收益可能因样本不同而产生偏差，适用于特定指数内的因子研究。
