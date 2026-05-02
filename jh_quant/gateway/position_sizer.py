"""
Position sizing strategies with a Protocol interface for plugin compatibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .signalgateway import PositionSizer

# Re-export the protocol for external implementers
__all__ = ["PositionSizer", "ATRPositionSizer", "FixedWeightPositionSizer"]


@runtime_checkable
class PositionSizer(Protocol):
    """头寸计算器协议

    实现此协议可以自定义不同的头寸计算策略。
    用户实现的 PositionSizer 可通过 service.configure_position_sizer() 注入。

    Example:
        from jh_quant.gateway.position_sizer import PositionSizer

        class MyPositionSizer:
            def calculate(
                self,
                candidates: pd.DataFrame,
                price_df: pd.DataFrame,
                latest_prices: pd.Series,
                available_balance: float,
                total_equity: float,
            ) -> pd.DataFrame:
                # custom logic
                ...
    """

    def calculate(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series,
        available_balance: float,
        total_equity: float,
    ) -> pd.DataFrame:
        """计算头寸

        Args:
            candidates: 候选股票（含 symbol, score）
            price_df: 价格数据
            latest_prices: 最新价格
            available_balance: 可用资金
            total_equity: 总权益

        Returns:
            包含 symbol 和 target_qty 的 DataFrame
        """
        ...


class ATRPositionSizer:
    """
    基于波动率（ATR）的风险对齐头寸计算器

    逻辑：
    1. 基础头寸 = (总权益 * 风险单位) / ATR * 策略得分
    2. 风险封顶 = min(基础头寸, 总权益 * max_position_weight)
    3. A股最小买卖单位100股，取整后分配
    """

    def __init__(
        self,
        risk_unit: float = 0.01,
        max_position_weight: float = 0.2,
    ):
        """
        Args:
            risk_unit: 风险单位（默认1%）
            max_position_weight: 单只股票最大仓位占比（默认20%）
        """
        self.risk_unit = risk_unit
        self.max_position_weight = max_position_weight

    def calculate(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series,
        available_balance: float,
        total_equity: float,
    ) -> pd.DataFrame:
        if candidates.empty:
            return pd.DataFrame()

        if total_equity <= 0 or available_balance <= 0:
            return pd.DataFrame()

        # ATR 计算
        def compute_atr(group: pd.DataFrame) -> float:
            try:
                df = group.sort_values("date").reset_index(drop=True)
                if len(df) < 14:
                    return np.nan
                high_low = df["high"] - df["low"]
                high_close = np.abs(df["high"] - df["close"].shift())
                low_close = np.abs(df["low"] - df["close"].shift())
                true_range = np.maximum(high_low, np.maximum(high_close, low_close))
                atr = true_range.rolling(window=14).mean()
                return atr.iloc[-1]
            except Exception:
                return np.nan

        candidate_symbols = candidates["symbol"].unique()
        price_df_filtered = price_df[price_df["symbol"].isin(candidate_symbols)]
        atr_series = (
            price_df_filtered.groupby("symbol")
            .apply(compute_atr, include_groups=False)
            .dropna()
        )

        result = candidates.copy()
        result = result.merge(
            latest_prices.to_frame("current_price"),
            left_on="symbol",
            right_index=True,
            how="left",
        )
        result = result.merge(
            atr_series.to_frame("atr_value"),
            left_on="symbol",
            right_index=True,
            how="left",
        )

        result = result.dropna(subset=["current_price", "atr_value"])
        result = result[result["atr_value"] > 0].copy()

        if result.empty:
            return pd.DataFrame()

        # ATR 风险对齐
        risk_amount = total_equity * self.risk_unit
        max_value_per_stock = total_equity * self.max_position_weight

        result["risk_value"] = (risk_amount / result["atr_value"]) * result["score"]
        result["risk_value"] = result["risk_value"].clip(upper=max_value_per_stock)

        # 按 score 排序，高 score 优先分配
        result = result.sort_values("score", ascending=False)

        selected_rows = []
        current_spent = 0.0

        for idx, row in result.iterrows():
            if row["score"] <= 0:
                continue

            price = row["current_price"]
            risk_qty = (row["risk_value"] // price // 100) * 100

            if risk_qty == 0:
                remaining = available_balance - current_spent
                if remaining >= price * 100:
                    risk_qty = 100
                else:
                    continue

            cost = risk_qty * price
            if current_spent + cost <= available_balance:
                selected_rows.append({"symbol": row["symbol"], "target_qty": risk_qty})
                current_spent += cost
            else:
                remaining = available_balance - current_spent
                possible_qty = (remaining // price // 100) * 100
                if possible_qty >= 100:
                    selected_rows.append(
                        {"symbol": row["symbol"], "target_qty": possible_qty}
                    )
                    current_spent += possible_qty * price
                else:
                    continue

        if not selected_rows:
            return pd.DataFrame()

        return pd.DataFrame(selected_rows)


class FixedWeightPositionSizer:
    """等权重头寸计算器"""

    def __init__(self, max_stocks: int = 10):
        self.max_stocks = max_stocks

    def calculate(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series,
        available_balance: float,
        total_equity: float,
    ) -> pd.DataFrame:
        if candidates.empty:
            return pd.DataFrame()

        top_candidates = candidates.sort_values("score", ascending=False).head(
            self.max_stocks
        )

        if top_candidates.empty:
            return pd.DataFrame()

        weight_per_stock = available_balance / len(top_candidates)

        result = top_candidates.copy()
        result = result.merge(
            latest_prices.to_frame("current_price"),
            left_on="symbol",
            right_index=True,
            how="left",
        )
        result = result.dropna(subset=["current_price"])

        result["target_qty"] = (
            weight_per_stock // result["current_price"] // 100
        ) * 100
        result = result[result["target_qty"] > 0]

        return result[["symbol", "target_qty"]].reset_index(drop=True)
