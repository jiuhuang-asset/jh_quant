# Trading

`jh_quant.trading` 提供面向交易运行的核心能力，包括：

- `MultiSessionService` 多会话管理
- `SessionServiceConfigBuilder` 会话配置构建
- `TradingEngine` 信号聚合与交易执行
- `portfolio` 组合优化与再平衡
- `persistence` 持仓、订单与绩效持久化
- `service` FastAPI 服务接口

可结合仓库根目录的 `run_paper.py` 作为使用示例。
