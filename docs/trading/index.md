# jh_quant.trading 模块文档

`jh_quant.trading` 是 jh_quant 的交易运行核心模块，提供从信号聚合、订单执行到组合优化、REST 服务的完整交易链路。

## 核心组件

| 组件 | 说明 |
|------|------|
| **TradingEngine** | 信号聚合与交易执行核心，汇总多策略信号，计算仓位，评估风险规则 |
| **SessionService** | 单会话全生命周期管理：配置、调度、执行、状态查询 |
| **MultiSessionService** | 多会话管理器，支持同时运行多个策略组合 |
| **MarketDataProvider** | 行情数据抽象层，内置 JHMarketDataProvider 对接 JHData |
| **OMS (MockOMS)** | 模拟订单管理系统，支持 T+1 规则、持仓跟踪、状态导出 |
| **PositionSizer** | 仓位计算，内置 ATR 波动率对齐和固定权重两种模式 |
| **PersistenceCoordinator** | 数据持久化门面，支持 SQLite / PostgreSQL / MemFireCloud |
| **Portfolio Optimizer** | 基于 Riskfolio-Lib 的组合优化，支持多种目标函数和风险模型 |



## 文档导航

- [快速开始](quickstart.md) — 5 分钟跑通第一个模拟交易会话
- [配置指南](configuration.md) — Session、策略、风险规则、选股器、组合优化配置详解
- [TradingEngine](trading-engine.md) — 信号聚合、候选生成、仓位计算、交易执行
- [组合优化](portfolio.md) — Riskfolio 组合优化与再平衡
- [服务层](service-layer.md) — SessionService / MultiSessionService / REST API 接口
- [数据持久化](persistence.md) — SQLite / PostgreSQL 持久化配置
- [扩展开发](customization.md) — 自定义策略、选股器、风险规则、OMS、行情源
