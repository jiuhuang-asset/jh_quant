import pandas as pd
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime


# StockDataSchema is now just a list of column names for validation
STOCK_DATA_COLUMNS = [
    "date", "symbol", "open", "close", "high", "low", "volume",
    "amount", "amplitude", "pct_chg", "chg", "turnover_rate", "created_at"
]


def get_stock_data_schema_fields():
    """Get all field names from StockDataSchema."""
    return STOCK_DATA_COLUMNS


class StockHoldRecord(BaseModel):
    symbol: str
    volume: int
    avg_cost: float = 0.0  # 平均成本
    market_value: float = 0.0  # 市场价值
    buy_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


class Positions(BaseModel):
    total: float
    available_balance: float
    total_profit: Optional[float] = Field(default=None)
    daily_profit: Optional[float] = Field(default=None)
    holds: List[StockHoldRecord]


class Order(BaseModel):
    symbol: str
    price: float
    volume: int
    trade_type: str = "BUY"  # BUY or SELL


# ==================== 回测记录相关模型 ====================


class Trade(BaseModel):
    """交易记录"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trade_id: str
    session_id: str
    trade_date: pd.Timestamp
    symbol: str
    trade_type: str  # BUY or SELL
    price: float
    quantity: int
    amount: float  # price * quantity
    commission: float = 0.0
    slippage: float = 0.0
    total_cost: float  # amount + commission + slippage
    signal_reason: Optional[str] = None
    order_id: Optional[str] = None


class DailyPerformance(BaseModel):
    """日度表现"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    performance_id: str
    session_id: str
    trade_date: pd.Timestamp
    portfolio_value: float
    cash_balance: float
    position_value: float
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    daily_pnl: Optional[float] = None
    num_positions: int = 0


class PositionSnapshot(BaseModel):
    """持仓快照"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    snapshot_id: str
    session_id: str
    trade_date: pd.Timestamp
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None


class BacktestSession(BaseModel):
    """回测会话"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    strategy_id: str
    strategy_name: Optional[str] = None
    start_time: pd.Timestamp
    end_time: Optional[pd.Timestamp] = None
    initial_capital: float
    final_balance: Optional[float] = None
    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Optional[float] = None
    total_trades: int = 0
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    profit_factor: Optional[float] = None
