"""
信号网关 - 聚合多策略信号，执行交易

核心职责：
- 策略信号聚合
- 头寸计算
- 订单执行

设计：使用 MarketDataProvider 统一获取市场数据，支持回测和实盘
"""
import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import List, Optional
from .strategy import Strategy
from .oms import OMS
from .models import Order, Trade
from .utils import rprint
from .market_data import MarketDataProvider


class PositionSizer(ABC):
    """
    头寸计算器抽象基类

    实现此接口可以自定义不同的头寸计算策略：
    - ATR风险对齐（默认）
    - 固定金额
    - 等权重
    """

    @abstractmethod
    def calculate(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series,
        available_balance: float,
        total_equity: float,
    ) -> pd.DataFrame:
        """
        计算头寸

        Args:
            candidates: 候选股票（含 symbol, score）
            price_df: 价格数据
            latest_prices: 最新价格
            available_balance: 可用资金
            total_equity: 总权益

        Returns:
            包含 symbol 和 target_qty 的 DataFrame
        """
        pass


class ATRPositionSizer(PositionSizer):
    """
    基于波动率（ATR）的风险对齐头寸计算器

    逻辑：
    1. 基础头寸 = (总权益 * 风险单位) / ATR * 策略得分
    2. 风险封顶 = min(基础头寸, 总权益 * max_position_weight)
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
        def compute_atr(group):
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
        atr_series = price_df_filtered.groupby("symbol").apply(compute_atr).dropna()

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

        rprint(
            label="Debug:",
            content=f"calculate_position_size: candidates={len(candidates)}, "
            f"latest_prices={len(latest_prices)}, atr_series={len(atr_series)}, "
            f"after_dropna={len(result)}",
        )

        # 计算头寸
        risk_amount = total_equity * self.risk_unit
        result["raw_position_value"] = (risk_amount / result["atr_value"]) * result["score"]

        # 单仓位上限
        max_value_per_stock = total_equity * self.max_position_weight
        result["capped_position_value"] = result["raw_position_value"].clip(upper=max_value_per_stock)

        # 计算目标股数（向下取整至100股）
        result["target_qty"] = (
            result["capped_position_value"] // result["current_price"] // 100
        ) * 100
        result = result[result["target_qty"] > 0].copy()

        if result.empty:
            return pd.DataFrame()

        # 现金约束
        result = result.sort_values("score", ascending=False)
        selected_indices = []
        current_spent = 0

        for idx, row in result.iterrows():
            cost = row["target_qty"] * row["current_price"]
            if current_spent + cost <= available_balance:
                selected_indices.append(idx)
                current_spent += cost
            else:
                remaining = available_balance - current_spent
                possible_qty = (remaining // row["current_price"] // 100) * 100
                if possible_qty >= 100:
                    result.loc[idx, "target_qty"] = possible_qty
                    selected_indices.append(idx)
                break

        return result.loc[selected_indices, ["symbol", "target_qty"]].reset_index(drop=True)


class FixedWeightPositionSizer(PositionSizer):
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

        # 取 top N
        top_candidates = candidates.sort_values("score", ascending=False).head(self.max_stocks)

        # 等权重分配
        weight_per_stock = available_balance / len(top_candidates)

        result = top_candidates.copy()
        result = result.merge(
            latest_prices.to_frame("current_price"),
            left_on="symbol",
            right_index=True,
            how="left",
        )
        result = result.dropna(subset=["current_price"])

        result["target_qty"] = (weight_per_stock // result["current_price"] // 100) * 100
        result = result[result["target_qty"] > 0]

        return result[["symbol", "target_qty"]].reset_index(drop=True)


class SignalGateway:
    """
    通用信号网关：负责聚合多策略信号，并执行交易。

    数据通过 MarketDataProvider 获取，交易状态由OMS管理。
    头寸计算通过 PositionSizer 插件化。
    """

    def __init__(
        self,
        oms: OMS,
        market_data_provider: MarketDataProvider = None,
        position_sizer: PositionSizer = None,
    ):
        """
        初始化信号网关

        Args:
            oms: 订单管理系统实例，必须提供
            market_data_provider: 市场数据提供者（用于获取K线数据）
            position_sizer: 头寸计算器（默认使用 ATR 方式）
        """
        if oms is None:
            raise ValueError("SignalGateway requires an OMS instance")

        self.oms = oms
        self.market_data_provider = market_data_provider
        self.position_sizer = position_sizer or ATRPositionSizer()
        self.strategy_pool: List[dict] = []

    def add_strategy(self, strategy: Strategy, name: str, weight: float = 1.0):
        """添加策略到信号池"""
        self.strategy_pool.append({
            "name": name,
            "strategy": strategy,
            "weight": weight,
        })

    def replace_strategies(self, strategies: List[dict]):
        """Replace the registered strategy pool in one call."""
        self.strategy_pool = []
        for item in strategies:
            self.add_strategy(
                strategy=item["strategy"],
                name=item["name"],
                weight=item.get("weight", 1.0),
            )

    def get_price_data(
        self,
        symbols: List[str] = None,
        start_date: str = None,
        end_date: str = None,
    ) -> pd.DataFrame:
        """
        从数据提供者获取股票价格数据

        Args:
            symbols: 股票代码列表，None表示获取全部
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            股票价格DataFrame
        """
        if self.market_data_provider is None:
            raise ValueError("MarketDataProvider not configured")

        if symbols is None:
            positions = self.oms.get_positions()
            position_symbols = [h.symbol for h in positions.holds]
            symbols = position_symbols or None

        bars_dict = self.market_data_provider.get_bars(
            symbols=symbols,
            start_date=start_date or "1900-01-01",
            end_date=end_date or "2099-12-31",
        )

        dfs = []
        for symbol, bars in bars_dict.items():
            for bar in bars:
                dfs.append({
                    "symbol": bar.symbol,
                    "date": bar.datetime,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "amount": bar.amount,
                })

        if not dfs:
            return pd.DataFrame()

        return pd.DataFrame(dfs)

    def aggregate_signals(
        self,
        price: pd.DataFrame,
        latest_timeindex: str,
        signal_type: str = "buy",
    ) -> pd.DataFrame:
        """
        聚合策略信号

        Args:
            price: 股票价格数据
            latest_timeindex: 最新时间戳
            signal_type: 信号类型 "buy" 或 "sell"

        Returns:
            包含 'symbol' 和 'score' 的DataFrame
        """
        if not self.strategy_pool:
            rprint(label="Warning:", content="No strategies registered in signal gateway")
            return pd.DataFrame()

        signal_column = f"{signal_type}_signal"
        weighted_column = f"{signal_type}_signal_w"

        rprint(
            label="Debug:",
            content=f"price shape={price.shape}, latest_timeindex={latest_timeindex}",
        )

        all_signals = []
        for strat in self.strategy_pool:
            signal_df = strat["strategy"](price)
            before_filter_len = len(signal_df)
            buy_sum = signal_df[signal_column].sum() if signal_column in signal_df.columns else 0
            signal_df[weighted_column] = signal_df[signal_column] * strat["weight"]
            signal_df = signal_df.loc[signal_df["date"] >= pd.to_datetime(latest_timeindex)]
            rprint(
                label="Debug:",
                content=f"  strategy={strat['name']}: before_filter={before_filter_len}, "
                f"buy_signal_sum={buy_sum}, after_filter={len(signal_df)}",
            )
            all_signals.append(signal_df[["symbol", weighted_column]])

        if not all_signals:
            return pd.DataFrame(columns=["symbol", "score"])

        combined = (
            pd.concat(all_signals)
            .groupby("symbol")[weighted_column]
            .sum()
            .reset_index()
        )
        combined.rename(columns={weighted_column: "score"}, inplace=True)
        return combined

    def aggregate_buy_signals(
        self, price: pd.DataFrame, latest_timeindex: str
    ) -> pd.DataFrame:
        """聚合买入信号"""
        return self.aggregate_signals(price, latest_timeindex, "buy")

    def aggregate_sell_signals(
        self, price: pd.DataFrame, latest_timeindex: str
    ) -> pd.DataFrame:
        """聚合卖出信号"""
        return self.aggregate_signals(price, latest_timeindex, "sell")

    def get_latest_prices(self, symbols: List[str] = None) -> pd.Series:
        """
        获取最新价格

        Args:
            symbols: 股票代码列表，None表示所有持仓

        Returns:
            pd.Series {symbol: price}
        """
        if symbols is None:
            positions = self.oms.get_positions()
            symbols = [h.symbol for h in positions.holds]

        if not symbols:
            return pd.Series(dtype=float)

        if self.market_data_provider:
            prices = self.market_data_provider.get_latest_prices(symbols)
            return pd.Series(prices)

        return pd.Series(dtype=float)

    def calculate_position_size(
        self,
        candidates: pd.DataFrame,
        price_df: pd.DataFrame,
        latest_prices: pd.Series = None,
    ) -> pd.DataFrame:
        """
        计算头寸（委托给 PositionSizer）

        Args:
            candidates: 候选股票
            price_df: 价格数据
            latest_prices: 最新价格
        """
        positions = self.oms.get_positions()
        total_equity = positions.total
        available_balance = positions.available_balance

        if latest_prices is None:
            latest_prices = price_df.groupby("symbol")["close"].last()

        return self.position_sizer.calculate(
            candidates=candidates,
            price_df=price_df,
            latest_prices=latest_prices,
            available_balance=available_balance,
            total_equity=total_equity,
        )

    def get_long_candidates(
        self,
        start_date: str = None,
        end_date: str = None,
        max_candidates: int = 5,
        price: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """
        获取买入候选股票（直接从provider获取数据）

        Args:
            start_date: 数据开始日期
            end_date: 数据结束日期
            max_candidates: 最大候选数量

        Returns:
            包含 symbol 和 target_qty 的 DataFrame
        """
        positions = self.oms.get_positions()
        rprint(
            label="Info:",
            content=f"总权益: {positions.total:.2f}, 可用资金: {positions.available_balance:.2f}",
        )

        if price is None:
            price = self.get_price_data(start_date=start_date, end_date=end_date)

        if price.empty:
            rprint(label="Warning:", content="无法获取价格数据")
            return pd.DataFrame()

        latest_timeindex = price["date"].max()

        raw_signals = self.aggregate_buy_signals(price=price, latest_timeindex=latest_timeindex)

        if raw_signals.empty:
            rprint(label="Info:", content="没有买入信号")
            return pd.DataFrame()

        rprint(
            label="Debug:",
            content=f"raw_signals before head: {len(raw_signals)} candidates, "
            f"top scores: {raw_signals.sort_values('score', ascending=False).head(5)[['symbol','score']].to_dict('records')}",
        )

        final_list = raw_signals.sort_values(by="score", ascending=False).head(max_candidates)

        if self.market_data_provider is not None:
            latest_prices = self.get_latest_prices(final_list["symbol"].tolist())
        else:
            latest_prices = (
                price[price["symbol"].isin(final_list["symbol"])]
                .sort_values(["symbol", "date"])
                .groupby("symbol")["close"]
                .last()
            )

        orders_df = self.calculate_position_size(final_list, price, latest_prices)

        return orders_df

    def get_short_candidates(
        self,
        start_date: str = None,
        end_date: str = None,
        price: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """
        获取卖出候选持仓
        """
        positions = self.oms.get_positions()
        rprint(
            label="Info:",
            content=f"总权益: {positions.total:.2f}, 持仓数: {len(positions.holds)}",
        )

        if not self.oms.executable_holds:
            rprint(label="Info:", content="没有持仓，无法执行卖出")
            return pd.DataFrame()

        hold_symbols = [h.symbol for h in self.oms.executable_holds]

        if price is None:
            price = self.get_price_data(symbols=hold_symbols, start_date=start_date, end_date=end_date)
        else:
            price = price[price["symbol"].isin(hold_symbols)].copy()

        if price.empty:
            return pd.DataFrame()

        latest_timeindex = price["date"].max()

        sell_signals = self.aggregate_sell_signals(price=price, latest_timeindex=latest_timeindex)

        if sell_signals.empty:
            rprint(label="Info:", content="没有卖出信号")
            return pd.DataFrame()

        holdings_map = {h.symbol: h for h in self.oms.executable_holds}

        sell_candidates = sell_signals[
            (sell_signals["symbol"].isin(holdings_map.keys()))
            & (sell_signals["score"] > 1)
        ].copy()

        if sell_candidates.empty:
            return pd.DataFrame()

        sell_orders = []
        for _, row in sell_candidates.iterrows():
            symbol = row["symbol"]
            qty = holdings_map[symbol].volume
            sell_orders.append({"symbol": symbol, "target_qty": qty})

        return pd.DataFrame(sell_orders)

    def execute_long(
        self,
        orders: pd.DataFrame,
        latest_prices: pd.Series = None,
    ) -> List[Trade]:
        """执行买入订单"""
        if latest_prices is None:
            symbols = orders["symbol"].tolist() if not orders.empty else []
            latest_prices = self.get_latest_prices(symbols)

        executed_trades = []
        for _, row in orders.iterrows():
            symbol = row["symbol"]
            target_qty = row["target_qty"]

            if symbol not in latest_prices.index:
                rprint(label="Warning:", content=f"无法获取 {symbol} 的最新价格")
                continue

            price_val = latest_prices[symbol]

            try:
                order = Order(symbol=symbol, price=price_val, volume=target_qty)
                trade = self.oms.signal_buy(order)
                executed_trades.append(trade)
            except Exception as e:
                rprint(label="Error:", content=f"买入 {symbol} 失败: {e}")
                continue

        self.oms.save_state_snapshot()
        return executed_trades

    def execute_short(
        self,
        orders: pd.DataFrame,
        latest_prices: pd.Series = None,
    ) -> List[Trade]:
        """执行卖出订单"""
        if latest_prices is None:
            symbols = orders["symbol"].tolist() if not orders.empty else []
            latest_prices = self.get_latest_prices(symbols)

        positions = self.oms.get_positions()
        holdings_map = {h.symbol: h for h in positions.holds}

        executed_trades = []
        for _, row in orders.iterrows():
            symbol = row["symbol"]
            target_qty = row["target_qty"]

            if symbol not in latest_prices.index:
                rprint(label="Warning:", content=f"无法获取 {symbol} 的最新价格")
                continue

            price_val = latest_prices[symbol]
            holding_info = holdings_map.get(symbol)

            if holding_info is None:
                continue

            try:
                order = Order(symbol=symbol, price=price_val, volume=target_qty)
                trade = self.oms.signal_sell(order)
                executed_trades.append(trade)

                pnl = (price_val - holding_info.avg_cost) * target_qty
                pnl_pct = ((price_val - holding_info.avg_cost) / holding_info.avg_cost * 100) if holding_info.avg_cost > 0 else 0
                rprint(
                    label="Trade:",
                    content=f"卖出 {symbol} {target_qty} 股 @ {price_val:.2f}, "
                    f"成本: {holding_info.avg_cost:.2f}, PnL: {pnl:.2f} ({pnl_pct:.2f}%)",
                )
            except Exception as e:
                rprint(label="Error:", content=f"卖出 {symbol} 失败: {e}")
                continue

        rprint(label="Info:", content=f"成功执行 {len(executed_trades)} 个卖出订单")
        self.oms.save_state_snapshot()
        return executed_trades

    def run_trading_cycle(
        self,
        start_date: str = None,
        end_date: str = None,
    ) -> dict:
        """
        运行完整交易周期（卖出 -> 买入）

        数据从 MarketDataProvider 自动获取

        Args:
            start_date: 数据开始日期
            end_date: 数据结束日期

        Returns:
            包含 executed_buys 和 executed_sells 的字典
        """
        latest_prices = self.get_latest_prices()

        # 卖出
        sell_candidates = self.get_short_candidates(start_date, end_date)
        executed_sells = []
        if not sell_candidates.empty:
            executed_sells = self.execute_short(sell_candidates, latest_prices)

        # 买入
        long_candidates = self.get_long_candidates(start_date, end_date)
        executed_buys = []
        if not long_candidates.empty:
            executed_buys = self.execute_long(long_candidates, latest_prices)

        return {
            "executed_buys": executed_buys,
            "executed_sells": executed_sells,
        }
