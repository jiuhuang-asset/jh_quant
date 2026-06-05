# jh_quant.trading

`jh_quant.trading` 是交易运行层，负责把选股、策略信号、组合优化、风险规则、订单执行、持久化、API 和 Dashboard 串成一个可运行的模拟盘或实盘服务。

## 核心原则

- `TradingEngine` 不依赖 akshare、tushare 或 xtquant 的原始字段。
- 所有进入交易执行层的行情数据必须先转换为统一的 trading price schema。
- 数据源差异只允许停留在 `market_data` provider / adapter 内部。
- 新用户优先使用 bootstrap template；高级用户可以直接组装 `MarketDataService`、`SelectionProvider`、`Broker` 和 `SessionServiceConfig`。

## 文档导航

- [快速开始](quickstart.md)：运行 `run_paper.py` 和 `run_live.py`。
- [Bootstrap 模板](bootstrap.md)：模板、backend、策略场景、Dashboard 自动打开。
- [高级自定义运行](advanced-usage.md)：不使用 bootstrap，手动配置完整模拟盘和实盘。
- [行情数据 Schema](market-data-schema.md)：trading 需要的字段、转换边界和 TuShare/AkShare 适配规则。
- [TradingEngine](trading-engine.md)：执行层如何消费统一行情数据。
- [配置指南](configuration.md)：Session、策略、风控、选股器、组合优化配置。
- [服务层](service-layer.md)：SessionService / MultiSessionService / REST API。
- [持久化](persistence.md)：SQLite / PostgreSQL 持久化配置。
- [组合优化](portfolio.md)：Riskfolio 组合优化与再平衡。
- [扩展开发](customization.md)：自定义策略、选股器、风控规则和数据源。
