# 快速开始

本文档帮助你 5 分钟内跑通第一个模拟交易会话。

## 环境要求

- Python 3.10+
- 已安装 `jh_quant` 及其依赖
- 如需组合优化功能，安装 `riskfolio-lib`

## 最小示例

以下是一个完整的最小示例 —— 对半导体股票池运行动量策略，并通过 Web 界面查看状态。

```python
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from jh_quant.trading import (
    JHMarketDataProvider,
    MultiSessionService,
    PersistenceCoordinator,
    SelectionProvider,
    SelectionSnapshot,
    SQLiteOrderRecorder,
    register_selection_provider,
    run_trading_app,
)
from jh_quant.trading.config import (
    ATRTrailingStopRuleConfig,
    MomentumStrategyConfig,
    RebalanceMode,
    RebalancePolicySpec,
    SessionServiceConfigBuilder,
)


# ① 定义选股器：指定要交易的股票池
@dataclass
class SemiConductorSelectionConfig:
    symbols: List[str] = field(default_factory=list)


class SemiConductorSelectionProvider(SelectionProvider):
    def __init__(self, config: SemiConductorSelectionConfig):
        self._symbols = list(config.symbols)
        self._config = config

    def select(self, as_of_date: str) -> SelectionSnapshot:
        return SelectionSnapshot(
            top_selections=list(self._symbols),
            metadata={"as_of_date": as_of_date, "provider": "semiconductor_static"},
        )

    @property
    def config(self) -> Dict[str, Any]:
        return asdict(self._config)


register_selection_provider(
    name="半导体自选",
    provider_cls=SemiConductorSelectionProvider,
    config_model=SemiConductorSelectionConfig,
)

# ② 准备股票池
SEMI_SYMBOLS = [
    "688981", "688041", "688256", "002371", "688795", "688012", "688802", "688347",
    "603986", "688008", "688820", "603501", "301308", "688521", "688072", "688783",
    "600584", "688525", "300604", "688702", "688498", "688082", "002156", "688729",
    # ... 更多标的
]

# ③ 组装并启动
def main():
    # 初始化持久化（SQLite）
    recorder = SQLiteOrderRecorder(db_path="mocktrade.db")
    persistence = PersistenceCoordinator(recorder=recorder)

    # 初始化行情
    md_provider = JHMarketDataProvider()

    # 初始化多会话管理器
    manager = MultiSessionService(
        max_sessions=4,
        persistence=persistence,
        market_data_provider=md_provider,
    )

    # 构建会话配置
    config = (
        SessionServiceConfigBuilder.defaults()
        .with_session(
            session_id="semi-momentum-a",
            mode="paper",
            price_slippage=0.001,
            cron_expression="0 16 * * 1-5",  # 每个交易日 16:00 运行
            enable_backfill=True,
            backfill_from="2025-10-01",
        )
        .with_selection(
            name="半导体自选",
            params=SemiConductorSelectionConfig(symbols=SEMI_SYMBOLS),
        )
        .with_portfolio(
            enabled=True,
            objective="MinRisk",
            rebalance_policy=RebalancePolicySpec(
                mode=RebalanceMode.DRIFT_THRESHOLD,
                drift_threshold=0.10,
            ),
        )
        .add_strategy(
            name="momentum",
            alias="momentum",
            weight=1.0,
            params=MomentumStrategyConfig(),
        )
        .add_risk_rule(
            name="atr_trailing_stop",
            params=ATRTrailingStopRuleConfig(multiplier=3.0, window=20),
        )
        .build()
    )

    # 创建会话（初始资金 10 万）
    manager.create_session(config=config, initial_capital=100_000)

    # 启动 Web 服务
    run_trading_app(manager=manager, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
```

## 运行

```bash
python run_paper.py
```

启动后访问 `http://127.0.0.1:8000/docs` 查看 Swagger API 文档。

## 关键步骤说明

### 1. 选股器（必需）

选股器决定了每个周期交易哪些标的。可以使用内置的 `FactorSelectionConfig`（基于因子选股），也可以像上面示例一样自定义静态选股器。详见[配置指南](configuration.md#选股器配置)和[扩展开发](customization.md#自定义选股器)。

### 2. 策略配置（必需）

通过 `.add_strategy()` 添加至少一个策略。内置 11 种策略（动量、均线交叉、布林带、RSI 等），详见[配置指南](configuration.md#策略配置)。

### 3. 风险规则（可选）

通过 `.add_risk_rule()` 添加风险规则。内置 7 种规则（止损、止盈、移动止损等）。

### 4. 组合优化（可选）

通过 `.with_portfolio()` 启用组合优化，自动根据目标函数计算最优权重。详见[组合优化](portfolio.md)。

## 下一步

- [配置指南](configuration.md) — 了解所有配置项
- [TradingEngine](trading-engine.md) — 深入引擎 API
- [服务层](service-layer.md) — REST API 接口详解
- [扩展开发](customization.md) — 自定义策略、选股器
