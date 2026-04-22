"""
Core data models for the signalgateway trading system.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StockHoldRecord(BaseModel):
    """持仓记录（内存中）"""

    symbol: str
    volume: int
    avg_cost: float = 0.0
    market_value: float = 0.0
    buy_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


class Positions(BaseModel):
    """持仓汇总"""

    total: float
    available_balance: float
    total_profit: Optional[float] = None
    daily_profit: Optional[float] = None
    holds: List[StockHoldRecord]


class Order(BaseModel):
    """订单"""

    symbol: str
    price: float
    volume: int
    trade_type: str = "BUY"  # BUY or SELL


class Trade(BaseModel):
    """成交记录"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trade_id: str
    session_id: str
    trade_date: pd.Timestamp | str
    symbol: str
    trade_type: str  # BUY or SELL
    price: float
    quantity: int
    amount: float  # price * quantity
    commission: float = 0.0
    slippage: float = 0.0
    total_cost: float
    signal_reason: Optional[str] = None
    order_id: Optional[str] = None

    @field_validator("trade_date", mode="before")
    @classmethod
    def _coerce_trade_date(cls, v):
        if isinstance(v, str):
            return pd.Timestamp(v)
        return v


class DailyPerformance(BaseModel):
    """日度表现（可从 snapshots/trades 计算，保留以支持历史数据兼容）"""

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
    """持仓快照（持久化）"""

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
