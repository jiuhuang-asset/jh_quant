"""
信号网关 - 聚合多策略信号，执行交易

核心职责：
- 策略信号聚合
- 头寸计算
- 订单执行

设计：使用 MarketDataProvider 统一获取市场数据，支持回测和实盘
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional, Union

import pandas as pd

from .market_data import Frequency, MarketDataProvider
from .models import Order, Trade
from .oms import OMS
from .position_sizer import ATRPositionSizer, PositionSizer
from .strategy import Strategy
from .utils import rprint
from .config import Frequency


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
        strict_mode: bool = True,
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
        self.strict_mode = strict_mode
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

    def configure_position_sizer(self, sizer: PositionSizer) -> None:
        """动态更换头寸计算器

        Args:
            sizer: 实现 PositionSizer 协议的头寸计算器实例
        """
        self.position_sizer = sizer

    def get_price_data(
        self,
        symbols: List[str] = None,
        start_date: str = None,
        end_date: str = None,
        frequency: Frequency | str = Frequency.DAILY,
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

        price_df = self.market_data_provider.get_price_data(
            symbols=symbols,
            start_date=start_date or "1900-01-01",
            end_date=end_date or "2099-12-31",
        )

        if price_df is None or price_df.empty:
            return pd.DataFrame()

        return price_df.sort_values(["symbol", "date"]).reset_index(drop=True)

    def _normalize_frequency(self, frequency: Frequency | str | None) -> Frequency:
        return Frequency.from_value(frequency)

    def _frequency_max_age(self, frequency: Frequency | str) -> timedelta:
        frequency = self._normalize_frequency(frequency)
        mapping = {
            Frequency.DAILY: timedelta(hours=24),
            Frequency.HOUR_1: timedelta(hours=1),
            Frequency.MINUTE_60: timedelta(hours=1),
            Frequency.MINUTE_30: timedelta(minutes=30),
            Frequency.MINUTE_15: timedelta(minutes=15),
            Frequency.MINUTE_5: timedelta(minutes=5),
            Frequency.MINUTE_1: timedelta(minutes=1),
        }
        return mapping.get(frequency, timedelta(hours=24))

    def _normalize_reference_time(
        self, value: Optional[Union[str, datetime, pd.Timestamp]]
    ) -> pd.Timestamp:
        if value is None:
            return pd.Timestamp(datetime.now())
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return timestamp

    def validate_price_freshness(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
        strict_mode: Optional[bool] = None,
    ) -> bool:
        should_check = self.strict_mode if strict_mode is None else strict_mode
        if not should_check:
            return True
        if price.empty or "date" not in price.columns:
            rprint(
                label="Warning:",
                content="Price freshness check failed because no valid date column is available",
            )
            return False

        latest_timeindex = pd.Timestamp(price["date"].max())
        if latest_timeindex.tzinfo is not None:
            latest_timeindex = latest_timeindex.tz_localize(None)

        reference_ts = self._normalize_reference_time(reference_time)
        frequency = self._normalize_frequency(frequency)
        max_age = self._frequency_max_age(frequency)
        if reference_ts - latest_timeindex > max_age:
            rprint(
                label="Warning:",
                content=(
                    f"Latest market data is stale for frequency={frequency.value}. "
                    f"latest={latest_timeindex}, reference={reference_ts}, max_age={max_age}. "
                    "Skip current execution."
                ),
            )
            return False
        return True

    def _filter_to_symbol_latest_window(
        self, signal_df: pd.DataFrame, frequency: Frequency | str
    ) -> pd.DataFrame:
        if signal_df.empty or "symbol" not in signal_df.columns or "date" not in signal_df.columns:
            return signal_df

        normalized = signal_df.copy()
        normalized["date"] = pd.to_datetime(normalized["date"])
        latest_by_symbol = normalized.groupby("symbol")["date"].transform("max")
        max_age = self._frequency_max_age(frequency)
        return normalized.loc[normalized["date"] >= (latest_by_symbol - max_age)].copy()

    def aggregate_signals(
        self,
        price: pd.DataFrame,
        frequency: Frequency | str = Frequency.DAILY,
        signal_type: str = "buy",
    ) -> pd.DataFrame:
        """
        聚合策略信号

        Args:
            price: 股票价格数据
            frequency: 用于按每个symbol自己的最新时间窗口过滤信号的频率
            signal_type: 信号类型 "buy" 或 "sell"

        Returns:
            包含 'symbol' 和 'score' 的DataFrame
        """
        if not self.strategy_pool:
            rprint(label="Warning:", content="No strategies registered in signal gateway")
            return pd.DataFrame()

        signal_column = f"{signal_type}_signal"
        weighted_column = f"{signal_type}_signal_w"

        all_signals = []
        for strat in self.strategy_pool:
            signal_df = strat["strategy"](price)
            signal_df = self._filter_to_symbol_latest_window(signal_df, frequency)
            signal_df[weighted_column] = signal_df[signal_column] * strat["weight"]
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
        self, price: pd.DataFrame, frequency: Frequency | str = Frequency.DAILY
    ) -> pd.DataFrame:
        """聚合买入信号"""
        return self.aggregate_signals(price, frequency, "buy")

    def aggregate_sell_signals(
        self, price: pd.DataFrame, frequency: Frequency | str = Frequency.DAILY
    ) -> pd.DataFrame:
        """聚合卖出信号"""
        return self.aggregate_signals(price, frequency, "sell")

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
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
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
            price = self.get_price_data(
                start_date=start_date,
                end_date=end_date,
            )

        if price.empty:
            rprint(label="Warning:", content="无法获取价格数据")
            return pd.DataFrame()

        if not self.validate_price_freshness(
            price=price,
            frequency=frequency,
            reference_time=reference_time or end_date,
        ):
            return pd.DataFrame()


        raw_signals = self.aggregate_buy_signals(price=price, frequency=frequency)

        if raw_signals.empty:
            rprint(label="Info:", content="没有买入信号")
            return pd.DataFrame()

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
        frequency: Frequency | str = Frequency.DAILY,
        reference_time: Optional[Union[str, datetime, pd.Timestamp]] = None,
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
            price = self.get_price_data(
                symbols=hold_symbols,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            price = price[price["symbol"].isin(hold_symbols)].copy()

        if price.empty:
            return pd.DataFrame()

        if not self.validate_price_freshness(
            price=price,
            frequency=frequency,
            reference_time=reference_time or end_date,
        ):
            return pd.DataFrame()


        sell_signals = self.aggregate_sell_signals(price=price, frequency=frequency)

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
        slippage: float = 0.0,
    ) -> List[Trade]:
        """执行买入订单

        Args:
            orders: 订单 DataFrame
            slippage: 滑点比例（买入时价格上涨 slippage，A股建议0.001-0.003）
        """
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
            exec_price = price_val * (1 + slippage) if slippage > 0 else price_val

            try:
                order = Order(symbol=symbol, price=exec_price, volume=target_qty)
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
        slippage: float = 0.0,
    ) -> List[Trade]:
        """执行卖出订单

        Args:
            orders: 订单 DataFrame
            slippage: 滑点比例（卖出时价格下跌 slippage，A股建议0.001-0.003）
        """
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
            exec_price = price_val * (1 - slippage) if slippage > 0 else price_val
            holding_info = holdings_map.get(symbol)

            if holding_info is None:
                continue

            try:
                order = Order(symbol=symbol, price=exec_price, volume=target_qty)
                trade = self.oms.signal_sell(order)
                executed_trades.append(trade)

                pnl = (exec_price - holding_info.avg_cost) * target_qty
                pnl_pct = ((exec_price - holding_info.avg_cost) / holding_info.avg_cost * 100) if holding_info.avg_cost > 0 else 0
                rprint(
                    label="Trade:",
                    content=f"卖出 {symbol} {target_qty} 股 @ {exec_price:.2f}, "
                    f"成本: {holding_info.avg_cost:.2f}, PnL: {pnl:.2f} ({pnl_pct:.2f}%)",
                )
            except Exception as e:
                rprint(label="Error:", content=f"卖出 {symbol} 失败: {e}")
                continue

        rprint(label="Info:", content=f"成功执行 {len(executed_trades)} 个卖出订单")
        self.oms.save_state_snapshot()
        return executed_trades

    def execute_cycle(
        self,
        top_selections: List[str],
        price_start: str,
        cycle_date: str,
        frequency: Frequency | str = Frequency.DAILY,
        max_candidates: int = 10,
        price_slippage: float = 0.0,
    ) -> tuple[List[Trade], List[Trade], pd.DataFrame, pd.DataFrame]:
        """
        执行完整交易周期：卖出 -> 买入

        Args:
            top_selections: 候选股票列表
            price_start: 价格数据起始日期
            cycle_date: 结算日期
            frequency: 数据频率
            max_candidates: 最大买入候选数
            price_slippage: 滑点

        Returns:
            (executed_buys, executed_sells, long_candidates, short_candidates)
        """
        price = self.get_price_data(
            symbols=top_selections or None,
            start_date=price_start,
            end_date=cycle_date,
            frequency=frequency,
        )

        latest_prices = self.get_latest_prices(symbols=top_selections)
        if not latest_prices.empty:
            prices_dict = latest_prices.to_dict()
            if hasattr(self.oms, "update_position_market_value"):
                self.oms.update_position_market_value(prices_dict)

        short_candidates = self.get_short_candidates(
            start_date=price_start,
            end_date=cycle_date,
            price=price,
            frequency=frequency,
            reference_time=cycle_date,
        )
        executed_sells: List[Trade] = []
        if not short_candidates.empty:
            executed_sells = self.execute_short(short_candidates, price_slippage)

        long_candidates = self.get_long_candidates(
            start_date=price_start,
            end_date=cycle_date,
            max_candidates=max_candidates,
            price=price,
            frequency=frequency,
            reference_time=cycle_date,
        )
        executed_buys: List[Trade] = []
        if not long_candidates.empty:
            executed_buys = self.execute_long(long_candidates, price_slippage)

        return executed_buys, executed_sells, long_candidates, short_candidates