from dataclasses import dataclass
from typing import Optional, List


@dataclass
class RiskManagementParams:
    max_holding_days: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    max_consecutive_rising_days: Optional[int] = None  # 最大连续上涨天数限制
    max_consecutive_falling_days: Optional[int] = None  # 最大连续下降天数限制


def risk_manage_single(
    stock_price,
    buy_signal,
    sell_signal,
    rmp: RiskManagementParams,
) -> List[int]:
    """
    Risk management function for one stock code.
    """
    position = 0
    positions = []
    holding_days = (0,)
    entry_price = (None,)
    highest_price_since_entry = (None,)
    consecutive_rising_days = (0,)  # 连续上涨天数计数器
    consecutive_falling_days = (0,)  # 连续下降天数计数器
    previous_price = None  # 记录前一个交易日价格
    for i, idx in enumerate(stock_price.index.tolist()):
        current_price = stock_price.loc[idx, "close"]
        should_force_sell = False
        if rmp.max_holding_days is not None and position == 1:
            holding_days += 1
            if holding_days >= rmp.max_holding_days:
                should_force_sell = True
        if rmp.stop_loss_pct is not None and position == 1 and entry_price is not None:
            if (current_price - entry_price) / entry_price <= -rmp.stop_loss_pct:
                should_force_sell = True

        # Trailing stop loss - sell if current price falls below highest price by trailing_stop_pct
        if (
            rmp.trailing_stop_pct is not None
            and position == 1
            and highest_price_since_entry is not None
        ):
            if (
                current_price - highest_price_since_entry
            ) / highest_price_since_entry <= -rmp.trailing_stop_pct:
                should_force_sell = True

        # 连续上涨天数限制 - 如果持仓中且连续上涨天数超过限制，则卖出
        if (
            rmp.max_consecutive_rising_days is not None
            and position == 1
            and previous_price is not None
        ):
            if current_price > previous_price:  # 当前价格高于前一日价格
                consecutive_rising_days += 1
                if consecutive_rising_days >= rmp.max_consecutive_rising_days:
                    should_force_sell = True
            else:  # 价格未上涨，重置计数器
                consecutive_rising_days = 0

        # 连续下降天数限制 - 如果持仓中且连续下降天数超过限制，则卖出
        if (
            rmp.max_consecutive_falling_days is not None
            and position == 1
            and previous_price is not None
        ):
            if current_price < previous_price:  # 当前价格低于前一日价格
                consecutive_falling_days += 1
                if consecutive_falling_days >= rmp.max_consecutive_falling_days:
                    should_force_sell = True
            else:  # 价格未下降，重置计数器
                consecutive_falling_days = 0

        # Update highest price for trailing stop
        if position == 1 and highest_price_since_entry is not None:
            highest_price_since_entry = max(highest_price_since_entry, current_price)

        # Check if we should sell (exit position)
        # Use index-based access (.loc) so signals align with the original DataFrame index
        if int(sell_signal.loc[idx]) == 1 or should_force_sell:
            position = 0
            holding_days = 0
            entry_price = None
            highest_price_since_entry = None
            consecutive_rising_days = 0  # 重置连续上涨天数计数器
            consecutive_falling_days = 0  # 重置连续下降天数计数器
            previous_price = current_price
        # Check if we should buy (enter position)
        elif (
            int(buy_signal.loc[idx]) == 1 and position == 0
        ):  # Only buy if not already in position
            position = 1
            holding_days = 0
            entry_price = current_price
            highest_price_since_entry = current_price
            consecutive_rising_days = 0  # 重置连续上涨天数计数器
            consecutive_falling_days = 0  # 重置连续下降天数计数器
            previous_price = current_price
        positions.append(position)
        previous_price = current_price  # 更新前一个价格

    return positions