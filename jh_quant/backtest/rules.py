"""风险规则模块。

提供 StopLoss / TrailingStop / TakeProfit / ATRTrailingStop 等常用风控规则，
以及 MaxHoldingBars / MaxConsecutiveRisingBars 等持仓限制规则。

用法::

    from jh_quant.backtest import StopLossRule, MaxHoldingBarsRule

    rules = [StopLossRule(0.05), MaxHoldingBarsRule(10)]
    positions = apply_rules(df, buy, sell, rules=rules)

自定义规则::

    from jh_quant.backtest import RiskRule, PositionState

    class MyRule(RiskRule):
        def should_sell(self, state, price, prev_price):
            return price < 5.0
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class PositionState:
    """持仓状态，由各风险规则共享读取和更新。"""

    in_position: bool = False
    entry_price: Optional[float] = None
    highest_price: Optional[float] = None
    holding_bars: int = 0
    consecutive_up: int = 0
    consecutive_down: int = 0

    def reset(self) -> None:
        self.in_position = False
        self.entry_price = None
        self.highest_price = None
        self.holding_bars = 0
        self.consecutive_up = 0
        self.consecutive_down = 0

    def enter(self, price: float) -> None:
        self.in_position = True
        self.entry_price = price
        self.highest_price = price
        self.holding_bars = 0
        self.consecutive_up = 0
        self.consecutive_down = 0


class RiskRule(ABC):
    """风险规则基类。

    每个规则实现三个 hook（均可选，should_sell 必须实现）：
    - ``on_enter``：买入时调用，初始化规则内部状态
    - ``on_tick``：每个 bar 调用，更新规则内部状态（在 should_sell 之前）
    - ``should_sell``：判断是否触发强制卖出
    """

    def on_enter(self, state: PositionState, price: float) -> None:
        pass

    def on_tick(
        self,
        state: PositionState,
        current_price: float,
        prev_price: Optional[float],
    ) -> None:
        pass

    @abstractmethod
    def should_sell(
        self,
        state: PositionState,
        current_price: float,
        prev_price: Optional[float],
    ) -> bool: ...


# ── 止损 / 止盈类 ──────────────────────────────────────────────────────────


class StopLossRule(RiskRule):
    """固定止损：现价相对入场价跌幅超过 *pct* 时卖出。"""

    def __init__(self, pct: float) -> None:
        self.pct = pct

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        return (current_price - state.entry_price) / state.entry_price <= -self.pct


class TakeProfitRule(RiskRule):
    """固定止盈：现价相对入场价涨幅超过 *pct* 时卖出。"""

    def __init__(self, pct: float) -> None:
        self.pct = pct

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        return (current_price - state.entry_price) / state.entry_price >= self.pct


class TrailingStopRule(RiskRule):
    """移动止损：现价相对持仓以来最高价回撤超过 *pct* 时卖出。"""

    def __init__(self, pct: float) -> None:
        self.pct = pct

    def on_tick(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> None:
        state.highest_price = max(state.highest_price, current_price)

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        return (current_price - state.highest_price) / state.highest_price <= -self.pct


class ATRTrailingStopRule(RiskRule):
    """ATR 移动止损：以 *multiplier* × ATR 作为止损距离。

    ATR 基于 high-low-close 的真实波幅计算，*window* 控制平滑窗口。
    止损价位只上移不下移（ratchet），跌破即卖出。
    """

    def __init__(self, multiplier: float = 3.0, window: int = 20) -> None:
        self.multiplier = multiplier
        self.window = window
        self._stop_level: Optional[float] = None

    def update_stop(self, atr_value: float, highest_price: float) -> None:
        new_stop = highest_price - self.multiplier * atr_value
        if self._stop_level is None or new_stop > self._stop_level:
            self._stop_level = new_stop

    def on_enter(self, state: PositionState, price: float) -> None:
        self._stop_level = None

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        if self._stop_level is None:
            return False
        return current_price <= self._stop_level


# ── 持仓时长限制类 ──────────────────────────────────────────────────────────


class MaxHoldingBarsRule(RiskRule):
    """最大持仓 bar 数：持有 bar 数达到上限时卖出。

    适用于任意时间频率（日线、小时线、月线等）。
    """

    def __init__(self, bars: int) -> None:
        self.max_bars = bars

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        return state.holding_bars >= self.max_bars


class MaxConsecutiveRisingBarsRule(RiskRule):
    """连续上涨 bar 数限制：连续上涨达到上限时卖出。"""

    def __init__(self, bars: int) -> None:
        self.max_bars = bars

    def on_tick(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> None:
        if prev_price is None:
            return
        if current_price > prev_price:
            state.consecutive_up += 1
        else:
            state.consecutive_up = 0

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        return state.consecutive_up >= self.max_bars

    def on_enter(self, state: PositionState, price: float) -> None:
        state.consecutive_up = 0


class MaxConsecutiveFallingBarsRule(RiskRule):
    """连续下跌 bar 数限制：连续下跌达到上限时卖出。"""

    def __init__(self, bars: int) -> None:
        self.max_bars = bars

    def on_tick(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> None:
        if prev_price is None:
            return
        if current_price < prev_price:
            state.consecutive_down += 1
        else:
            state.consecutive_down = 0

    def should_sell(
        self, state: PositionState, current_price: float, prev_price: Optional[float]
    ) -> bool:
        return state.consecutive_down >= self.max_bars

    def on_enter(self, state: PositionState, price: float) -> None:
        state.consecutive_down = 0


# ── 核心引擎 ─────────────────────────────────────────────────────────────────


def apply_rules(
    stock_price: pd.DataFrame,
    buy_signal: pd.Series,
    sell_signal: pd.Series,
    rules: List[RiskRule] | None = None,
) -> List[int]:
    """对单只股票执行风险管理，根据买卖信号和风险规则生成持仓序列。

    Args:
        stock_price: 单只股票的价格数据，需包含 ``close`` 列。
                     若使用 ATRTrailingStopRule 还需 ``high``、``low``。
        buy_signal: 买入信号序列（索引对齐 stock_price）。
        sell_signal: 卖出信号序列（索引对齐 stock_price）。
        rules: 风险规则列表，可为 None（不启用风控）。

    Returns:
        与输入行数等长的持仓列表，1 表示持仓，0 表示空仓。
    """
    rules = rules or []
    state = PositionState()
    positions: List[int] = []
    prev_price: Optional[float] = None

    atr_series = maybe_compute_atr(stock_price, rules)

    for idx in stock_price.index.tolist():
        current_price = float(stock_price.loc[idx, "close"])
        atr_val = float(atr_series.loc[idx]) if atr_series is not None else None
        buy = int(buy_signal.loc[idx]) == 1
        sell = int(sell_signal.loc[idx]) == 1

        if state.in_position:
            state.holding_bars += 1

            # 更新 ATR 止损价位（ratchet 上移）
            if atr_val is not None:
                for rule in rules:
                    if isinstance(rule, ATRTrailingStopRule):
                        rule.update_stop(atr_val, state.highest_price)

            for rule in rules:
                rule.on_tick(state, current_price, prev_price)

            force_sell = any(
                rule.should_sell(state, current_price, prev_price) for rule in rules
            )
        else:
            force_sell = False

        if state.in_position and (sell or force_sell):
            state.reset()
            positions.append(0)
        elif buy and not state.in_position:
            state.enter(current_price)
            for rule in rules:
                rule.on_enter(state, current_price)
            if atr_val is not None:
                for rule in rules:
                    if isinstance(rule, ATRTrailingStopRule):
                        rule.update_stop(atr_val, current_price)
            positions.append(1)
        else:
            positions.append(1 if state.in_position else 0)

        prev_price = current_price

    return positions


def maybe_compute_atr(
    stock_price: pd.DataFrame, rules: List[RiskRule]
) -> Optional[pd.Series]:
    """如果规则列表中包含 ATRTrailingStopRule，预计算 ATR 序列。"""
    has_atr = any(isinstance(r, ATRTrailingStopRule) for r in rules)
    if not has_atr:
        return None

    window = 14
    for r in rules:
        if isinstance(r, ATRTrailingStopRule):
            window = r.window
            break

    high = stock_price["high"]
    low = stock_price["low"]
    close = stock_price["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = true_range.rolling(window=window, min_periods=1).mean()
    return atr
