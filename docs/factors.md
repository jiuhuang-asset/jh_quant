# jh_quant.factors

因子计算框架，支持FF3/FF5/Carhart/Novy-Marx/q-factor/DHS等多种因子模型的计算与验证。

- **学术支撑**: FF3、FF5、Carhart、Novy-Marx、Hou-Xue-Zhang、DHS等经典模型
- **高效计算**: 支持Polars加速、多进程并行
- **暴露计算**: StockExposureCalculator 计算个股在因子上的暴露
- **因子验证**: Fama-MacBeth回归验证

## 安装

```bash
pip install -e .
```

环境变量（`.env`）:
- `JIUHUANG_API_KEY` - API令牌
- `JIUHUANG_API_URL` - 数据API地址（默认: `http://127.0.0.1:8080`）

## 快速开始

### 计算因子收益

```python
from jh_quant.factors import FactorEngine, FactorType, CalculationMethod, TimePeriod

engine = FactorEngine()

# 计算 FF3 因子收益（月度）
factor_returns = engine.calculate_factor_returns(
    factor_type=FactorType.FF3,
    method=CalculationMethod.SIMPLE,
    period=TimePeriod.MONTHLY,
    start_date="2020-01-01",
    end_date="2024-12-31",
)
print(factor_returns)
```

### 批量计算多个因子

```python
from jh_quant.factors import FactorEngine, FactorType

engine = FactorEngine()

# 批量计算 FF3、FF5、CARHART
results = engine.calculate_all_factors(
    factor_types=[FactorType.FF3, FactorType.FF5, FactorType.CARHART],
    start_date="2020-01-01",
    end_date="2024-12-31",
)

for factor_type, df in results.items():
    print(f"{factor_type.value}: {len(df)} rows")
```

### 计算个股因子暴露

```python
from jh_quant.factors import calculate_exposures

# 假设 stock_data 包含股票收益率和市场数据
exposures = calculate_exposures(
    stock_data=stock_df,
    factor_type=FactorType.FF3,
    start_date="2020-01-01",
    end_date="2024-12-31",
)
print(exposures)
```

### Fama-MacBeth 验证

```python
from jh_quant.factors import FamaMacBethValidator, FactorType

validator = FamaMacBethValidator()

result = validator.validate(
    factor_type=FactorType.FF3,
    start_date="2020-01-01",
    end_date="2024-12-31",
)

print(f"因子暴露 t 值: {result.factor_tvalues}")
print(f"显著性: {result.significance}")
```

## 支持的因子模型

| 因子模型 | 说明 | 论文 |
|----------|------|------|
| `FF3` | Fama-French 三因子 | Fama & French, 1993 |
| `FF5` | Fama-French 五因子 | Fama & French, 2015 |
| `CARHART` | Carhart 四因子 | Carhart, 1997 |
| `NOVY_MARX` | Novy-Marx 盈利因子 | Novy-Marx, 2013 |
| `HOU_XUE_ZHANG` | Hou-Xue-Zhang q因子 | Hou et al., 2020 |
| `DHS` | Daniel-Hirshleifer-Sun 因子 | Daniel et al., 2020 |
| `CAPM` | 资本资产定价模型 | Sharpe, 1964 |
| `SY4` | 剩余四因子 | - |
| `REVERSAL` | 反转因子 | - |
| `LOW_VOL` | 低波动因子 | - |

## 核心类

### `FactorEngine`

主入口类，协调数据准备、因子计算、暴露计算：

```python
from jh_quant.factors import FactorEngine, FactorType

engine = FactorEngine(api_key="...", api_url="...")

# 计算因子收益
factor_returns = engine.calculate_factor_returns(FactorType.FF3)

# 批量计算
all_results = engine.calculate_all_factors([FactorType.FF3, FactorType.FF5])
```

### `FactorReturnData` 子类

每个因子模型对应一个数据准备类（位于 `factors/` 目录）：

```python
from jh_quant.factors.data import FF3Data, FF5Data, get_factor_data_class

data_class = get_factor_data_class(FactorType.FF3)
data_provider = data_class(api_key="...", api_url="...")
prepared = data_provider.prepare_data(period=TimePeriod.MONTHLY, start_date="...", end_date="...")
```

### `GeneralFactorCalculator`

因子收益计算器：

```python
from jh_quant.factors.factors.general import GeneralFactorCalculator
from jh_quant.factors.config import FactorType, CalculationMethod, TimePeriod

calculator = GeneralFactorCalculator(
    factor_type=FactorType.FF3,
    method=CalculationMethod.SIMPLE,
    period=TimePeriod.MONTHLY,
)
```

### `StockExposureCalculator`

计算个股在因子上的暴露：

```python
from jh_quant.factors.exposure import StockExposureCalculator

calc = StockExposureCalculator(factor_type=FactorType.FF3)
exposures = calc.calculate(stock_data, factor_returns)
```

### `FamaMacBethValidator`

Fama-MacBeth回归验证：

```python
from jh_quant.factors.validators import FamaMacBethValidator

validator = FamaMacBethValidator()
result = validator.validate(factor_type=FactorType.FF3, start_date="...", end_date="...")
```

## 配置选项

### 计算方法

```python
from jh_quant.factors.config import CalculationMethod

CalculationMethod.CLASSIC  # 经典方法
CalculationMethod.SIMPLE   # 简化方法
```

### 时间周期

```python
from jh_quant.factors.config import TimePeriod

TimePeriod.MONTHLY  # 月度
TimePeriod.DAILY    # 日度
```

## 目录结构

```
factors/
├── __init__.py           # 主入口，导出所有公共接口
├── main.py               # FactorEngine 主类
├── config.py             # 因子配置（FactorType, CalculationMethod, TimePeriod）
├── data/                 # 数据准备类
│   ├── base.py           # 基类和工厂函数
│   ├── ff3.py            # FF3 数据
│   ├── ff5.py            # FF5 数据
│   └── ...
├── factors/              # 因子计算器
│   ├── general.py        # GeneralFactorCalculator
│   └── ...
├── exposure/             # 暴露计算
│   ├── __init__.py
│   └── stock_exposure.py
├── validators/          # 因子验证
│   ├── __init__.py
│   └── fama_macbeth.py
└── utils/                # 工具函数
```
