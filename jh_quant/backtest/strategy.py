import os
from abc import ABC, abstractmethod

import pandas as pd
from joblib import Parallel, delayed
from jh_quant.data import get_code_date_col

# Get the number of CPUs minus one
n_jobs = max(1, os.cpu_count() - 1)


class Strategy(ABC):
    """策略基类，定义策略执行的抽象接口

    所有具体策略类都应继承此类并实现 _execute_one 方法。
    策略基类负责:
    - 并行处理多个股票的数据
    - 验证买卖信号不会同时触发
    - 统一的数据排序和索引重置
    """

    def __init__(self):
        pass

    @abstractmethod
    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的执行策略逻辑，生成买卖信号

        Args:
            data: 包含单只股票历史数据的 DataFrame，需包含 close, high, low, volume 等列

        Returns:
            添加了 buy_signal 和 sell_signal 列的 DataFrame
        """
        pass

    def _execute_strategy(self, price: pd.DataFrame) -> pd.DataFrame:
        """并行执行策略逻辑，对多个标的分组处理

        Args:
            price: 包含多个股票历史数据的 DataFrame

        Returns:
            合并后的结果 DataFrame
        """
        code_col, dt_col = get_code_date_col(price)
        # 按股票代码和日期排序
        price_sorted = price.sort_values([code_col, dt_col]).reset_index(drop=True)
        # Group by symbol and apply parallel processing
        grouped = price_sorted.groupby(code_col)
        results = Parallel(n_jobs=n_jobs)(
            delayed(self._execute_one)(data) for _, data in grouped
        )

        result_df = pd.concat(results, ignore_index=True)
        return result_df

    def _validate_output(self, result: pd.DataFrame) -> pd.DataFrame:
        """验证买卖信号不会同时为1，如果同时出现则卖出信号优先

        Args:
            result: 包含买卖信号的 DataFrame

        Returns:
            验证后的 DataFrame
        """
        # Convert to regular DataFrame to avoid Arrow backend issues
        if "buy_signal" in result.columns and "sell_signal" in result.columns:
            simultaneous_mask = (result["buy_signal"] == 1) & (
                result["sell_signal"] == 1
            )
            if simultaneous_mask.any():
                print(
                    f"Warning: {simultaneous_mask.sum()} simultaneous buy/sell signals found. Resolving..."
                )
                result.loc[simultaneous_mask, "sell_signal"] = 0
        return result

    def __call__(self, price: pd.DataFrame) -> pd.DataFrame:

        result = self._execute_strategy(price)
        result = self._validate_output(result)
        return result


class StrategyTurtle(Strategy):
    """海龟交易策略

    经典的趋势跟踪策略，基于历史高点/低点突破入场。

    策略逻辑:
    - 入场条件: 当收盘价突破过去 N 天的最高价时买入
    - 出场条件: 当收盘价跌破过去 M 天的最低价时卖出

    参数:
    - entry_window: 入场窗口期，计算历史最高价的天数（默认20天）
    - exit_window: 出场窗口期，计算历史最低价的天数（默认10天）

    适用场景:
    - 趋势明显的市场
    - 波动性较大的品种
    - 长期趋势跟踪
    """

    def __init__(
        self, entry_window: int = 20, exit_window: int = 10
    ):
        super().__init__()
        self.entry_window = entry_window
        self.exit_window = exit_window

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生成海龟策略的买卖信号"""
        data = data.copy()

        # 计算滚动最高价和最低价
        data["entry_high"] = (
            data["high"].rolling(window=self.entry_window, min_periods=1).max()
        )
        data["exit_low"] = (
            data["low"].rolling(window=self.exit_window, min_periods=1).min()
        )

        # Generate signals
        data["buy_signal"] = (data["close"] > data["entry_high"].shift(1)).astype(int)
        data["sell_signal"] = (data["close"] < data["exit_low"].shift(1)).astype(int)

        # Clean up temporary columns
        data = data.drop(["entry_high", "exit_low"], axis=1)
        return data


class StrategyMovingAverageCrossover(Strategy):
    """移动平均线交叉策略

    经典的趋势跟踪策略，利用短期和长期均线的交叉来判断趋势。

    策略逻辑:
    - 入场条件: 短期均线从下向上突破长期均线（金叉）
    - 出场条件: 短期均线从上向下突破长期均线（死叉）

    参数:
    - short_window: 短期均线窗口期（默认50天）
    - long_window: 长期均线窗口期（默认200天）

    适用场景:
    - 中长期趋势跟踪
    - 趋势明显的市场
    - 需要结合市场环境使用，避免在震荡市中频繁交易
    """

    def __init__(
        self, short_window: int = 50, long_window: int = 200
    ):
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生成均线交叉策略的买卖信号"""
        data = data.copy()

        data["short_ma"] = (
            data["close"].rolling(window=self.short_window, min_periods=1).mean()
        )
        data["long_ma"] = (
            data["close"].rolling(window=self.long_window, min_periods=1).mean()
        )

        data["buy_signal"] = (
            (data["short_ma"] > data["long_ma"])
            & (data["short_ma"].shift(1) <= data["long_ma"].shift(1))
        ).astype(int)

        data["sell_signal"] = (
            (data["short_ma"] < data["long_ma"])
            & (data["short_ma"].shift(1) >= data["long_ma"].shift(1))
        ).astype(int)

        data = data.drop(["short_ma", "long_ma"], axis=1)
        return data


class StrategyBuyAndHold(Strategy):
    """买入持有策略

    最简单的长期投资策略，在起始日期买入后一直持有。

    策略逻辑:
    - 入场条件: 在数据起始日期买入（只触发一次）
    - 出场条件: 无卖出信号（持续持有）

    适用场景:
    - 长期投资
    - 作为策略表现的基准对比
    - 配合其他风险控制参数使用
    """

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生成买入持有信号"""
        data = data.copy()

        # 只在第一个日期创建买入信号
        data["buy_signal"] = 0
        data["sell_signal"] = 0
        data.iloc[0, data.columns.get_loc("buy_signal")] = 1

        return data


class StrategyVolumeTrend(Strategy):
    """成交量趋势策略

    基于成交量和价格趋势的策略，结合量价关系判断市场动向。

    策略逻辑:
    - 入场条件: 价格在均线之上 且 成交量显著放大 且 成交量趋势向上
    - 出场条件: 价格跌破均线 或 成交量萎缩 或 成交量趋势向下

    参数:
    - ma_window: 移动平均线窗口期（默认20天）
    - volume_window: 成交量平均窗口期（默认20天）
    - volume_threshold: 成交量放大阈值（默认1.2倍）
    - volume_trend_threshold: 成交量趋势阈值（默认0.1）
    - price_change_threshold: 价格变动阈值（默认0.02）

    适用场景:
    - 成交量活跃的市场
    - 需要结合量价关系判断趋势
    - 捕捉放量突破行情
    """

    def __init__(
        self,
        ma_window: int = 20,
        volume_window: int = 20,
        volume_threshold: float = 1.2,
        volume_trend_threshold: float = 0.1,
        price_change_threshold: float = 0.02,
    ):
        super().__init__()
        self.ma_window = ma_window
        self.volume_window = volume_window
        self.volume_threshold = volume_threshold
        self.volume_trend_threshold = volume_trend_threshold
        self.price_change_threshold = price_change_threshold

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生成成交量趋势策略的买卖信号"""
        data = data.copy()

        data["ma"] = data["close"].rolling(window=self.ma_window, min_periods=1).mean()
        data["avg_volume"] = (
            data["volume"].rolling(window=self.volume_window, min_periods=1).mean()
        )
        data["volume_trend"] = data["avg_volume"].pct_change()

        data["buy_signal"] = (
            (data["close"] > data["ma"])
            & (data["volume"] > data["avg_volume"] * self.volume_threshold)
            & (data["volume_trend"] > self.volume_trend_threshold)
        ).astype(int)

        data["sell_signal"] = (
            (data["close"] < data["ma"])
            | (data["volume"] < data["avg_volume"] * 0.8)
            | (data["volume_trend"] < -self.volume_trend_threshold)
        ).astype(int)

        return data


class StrategyVolumeDivergence(Strategy):
    """量价背离策略

    基于RSI指标和成交量背离的策略，捕捉价格与成交量的背离信号。

    策略逻辑:
    - 入场条件: RSI超卖 且 成交量趋势向上 且 价格下跌（底背离）
    - 出场条件: RSI超买 且 成交量趋势向下 且 价格上涨（顶背离）

    参数:
    - rsi_window: RSI计算窗口期（默认14天）
    - volume_window: 成交量平均窗口期（默认20天）
    - volume_trend_threshold: 成交量趋势阈值（默认0.05）
    - price_change_threshold: 价格变动阈值（默认0.02）
    - rsi_oversold: RSI超卖阈值（默认30）
    - rsi_overbought: RSI超买阈值（默认70）

    适用场景:
    - 震荡市场中的反转信号
    - 捕捉背离信号
    - 需要结合超买超卖指标使用
    """

    def __init__(
        self,
        rsi_window: int = 14,
        volume_window: int = 20,
        volume_trend_threshold: float = 0.05,
        price_change_threshold: float = 0.02,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
    ):
        super().__init__()
        self.rsi_window = rsi_window
        self.volume_window = volume_window
        self.volume_trend_threshold = volume_trend_threshold
        self.price_change_threshold = price_change_threshold
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产量价背离策略的买卖信号"""
        data = data.copy()

        data["pct_chg"] = data["close"].pct_change()

        delta = data["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=self.rsi_window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_window).mean()
        rs = gain / loss
        data["rsi"] = 100 - (100 / (1 + rs))

        data["avg_volume"] = (
            data["volume"].rolling(window=self.volume_window, min_periods=1).mean()
        )
        data["volume_trend"] = data["avg_volume"].pct_change()

        data["buy_signal"] = (
            (data["rsi"] < self.rsi_oversold)
            & (data["volume_trend"] > self.volume_trend_threshold)
            & (data["pct_chg"] < -self.price_change_threshold)
        ).astype(int)

        data["sell_signal"] = (
            (data["rsi"] > self.rsi_overbought)
            & (data["volume_trend"] < -self.volume_trend_threshold)
            & (data["pct_chg"] > self.price_change_threshold)
        ).astype(int)

        return data


class StrategyMeanReversion(Strategy):
    """均值回归策略

    基于价格偏离均值程度的策略，假设价格会回归到均值水平。

    策略逻辑:
    - 入场条件: 价格显著低于均线（负偏离）且RSI超卖
    - 出场条件: 价格显著高于均线（正偏离）且RSI超买

    参数:
    - ma_window: 均线窗口期（默认20天）
    - deviation_threshold: 价格偏离均线阈值（默认0.02，即2%）
    - rsi_window: RSI计算窗口期（默认14天）
    - rsi_oversold: RSI超卖阈值（默认30）
    - rsi_overbought: RSI超买阈值（默认70）

    适用场景:
    - 震荡市场
    - 价格波动后回归均值的行情
    - 适合区间震荡的股票
    """

    def __init__(
        self,
        ma_window: int = 20,
        deviation_threshold: float = 0.02,
        rsi_window: int = 14,
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
    ):
        super().__init__()
        self.ma_window = ma_window
        self.deviation_threshold = deviation_threshold
        self.rsi_window = rsi_window
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产均值回归策略的买卖信号"""
        data = data.copy()

        data["ma"] = data["close"].rolling(window=self.ma_window, min_periods=1).mean()
        data["price_deviation"] = (data["close"] - data["ma"]) / data["ma"]

        delta = data["close"].diff()
        gain = (
            delta.where(delta > 0, 0)
            .rolling(window=self.rsi_window, min_periods=1)
            .mean()
        )
        loss = (
            (-delta.where(delta < 0, 0))
            .rolling(window=self.rsi_window, min_periods=1)
            .mean()
        )
        rs = gain / loss
        data["rsi"] = 100 - (100 / (1 + rs))

        data["buy_signal"] = (
            (data["price_deviation"] < -self.deviation_threshold)
            & (data["rsi"] < self.rsi_oversold)
        ).astype(int)

        data["sell_signal"] = (
            (data["price_deviation"] > self.deviation_threshold)
            & (data["rsi"] > self.rsi_overbought)
        ).astype(int)

        data = data.drop(["ma", "price_deviation", "rsi"], axis=1)
        return data


class StrategyRSI(Strategy):
    """RSI 相对强弱指标策略

    基于RSI指标的超买超卖区域进行交易的策略。

    策略逻辑:
    - 入场条件: RSI从超卖区域回升（如RSI从30以下回到30以上）
    - 出场条件: RSI进入超买区域后回落（如RSI从70以上回到70以下）

    参数:
    - rsi_window: RSI计算窗口期（默认14天）
    - rsi_oversold: RSI超卖阈值（默认30）
    - rsi_overbought: RSI超买阈值（默认70）
    - rsi_exit_oversold: RSI超卖退出阈值（默认50）
    - rsi_exit_overbought: RSI超买退出阈值（默认50）

    适用场景:
    - 震荡市场
    - 捕捉价格的短期反弹和回调
    - 需要配合趋势判断避免逆势交易
    """

    def __init__(
        self,
        rsi_window: int = 14,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        rsi_exit_oversold: float = 50,
        rsi_exit_overbought: float = 50,
    ):
        super().__init__()
        self.rsi_window = rsi_window
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.rsi_exit_oversold = rsi_exit_oversold
        self.rsi_exit_overbought = rsi_exit_overbought

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产RSI策略的买卖信号"""
        data = data.copy()

        # 计算RSI
        delta = data["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=self.rsi_window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_window).mean()
        rs = gain / loss
        data["rsi"] = 100 - (100 / (1 + rs))

        # 入场信号: RSI从超卖区域回升到阈值以上
        data["buy_signal"] = (
            (data["rsi"] < self.rsi_oversold)
            & (data["rsi"].shift(1) >= self.rsi_exit_oversold)
        ).astype(int)

        # 出场信号: RSI从超买区域回落到阈值以下
        data["sell_signal"] = (
            (data["rsi"] > self.rsi_overbought)
            & (data["rsi"].shift(1) <= self.rsi_exit_overbought)
        ).astype(int)

        data = data.drop(["rsi"], axis=1)
        return data


class StrategyBollingerBands(Strategy):
    """布林带策略

    基于布林带上下轨突破进行交易的策略，利用价格统计分布原理。

    策略逻辑:
    - 入场条件: 价格突破布林带上轨或触及下轨后反弹
    - 出场条件: 价格跌破布林带中轨或触及上轨后回落

    参数:
    - window: 布林带中轨窗口期（默认20天）
    - num_std: 标准差倍数（默认2倍）
    - use_mean_reversion: 是否使用均值回归逻辑（默认False）

    适用场景:
    - 波动性较大的市场
    - 趋势反转的捕捉
    - 震荡区间突破行情
    """

    def __init__(
        self,
        window: int = 20,
        num_std: float = 2.0,
        use_mean_reversion: bool = False,
    ):
        super().__init__()
        self.window = window
        self.num_std = num_std
        self.use_mean_reversion = use_mean_reversion

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产布林带策略的买卖信号"""
        data = data.copy()

        # 计算布林带
        data["ma"] = data["close"].rolling(window=self.window, min_periods=1).mean()
        data["std"] = data["close"].rolling(window=self.window, min_periods=1).std()
        data["upper_band"] = data["ma"] + self.num_std * data["std"]
        data["lower_band"] = data["ma"] - self.num_std * data["std"]

        if self.use_mean_reversion:
            # 均值回归逻辑: 价格触及下轨买入，触及上轨卖出
            data["buy_signal"] = (
                (data["close"] <= data["lower_band"])
                & (data["close"].shift(1) > data["lower_band"].shift(1))
            ).astype(int)

            data["sell_signal"] = (
                (data["close"] >= data["upper_band"])
                & (data["close"].shift(1) < data["upper_band"].shift(1))
            ).astype(int)
        else:
            # 突破逻辑: 价格突破上轨买入，跌破中轨卖出
            data["buy_signal"] = (
                (data["close"] > data["upper_band"])
                & (data["close"].shift(1) <= data["upper_band"].shift(1))
            ).astype(int)

            data["sell_signal"] = (
                (data["close"] < data["ma"])
                & (data["close"].shift(1) >= data["ma"].shift(1))
            ).astype(int)

        data = data.drop(["ma", "std", "upper_band", "lower_band"], axis=1)
        return data


class StrategyMomentum(Strategy):
    """动量策略

    基于价格动量进行交易的策略，假设上涨的股票将继续上涨，下跌的将继续下跌。

    策略逻辑:
    - 入场条件: 价格动量指标（如ROC）超过阈值且为正
    - 出场条件: 价格动量指标转负或跌破均线

    参数:
    - momentum_window: 动量计算窗口期（默认20天）
    - momentum_threshold: 动量阈值（默认0.05，即5%）
    - ma_window: 均线窗口期（默认60天）

    适用场景:
    - 趋势明确的市场
    - 捕捉趋势的延续
    - 适合中长期交易
    """

    def __init__(
        self,
        momentum_window: int = 20,
        momentum_threshold: float = 0.05,
        ma_window: int = 60,
    ):
        super().__init__()
        self.momentum_window = momentum_window
        self.momentum_threshold = momentum_threshold
        self.ma_window = ma_window

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产动量策略的买卖信号"""
        data = data.copy()

        # 计算动量指标 (Rate of Change)
        data["momentum"] = data["close"].pct_change(periods=self.momentum_window)

        # 计算均线
        data["ma"] = data["close"].rolling(window=self.ma_window, min_periods=1).mean()

        # 入场信号: 动量超过阈值且价格在均线之上
        data["buy_signal"] = (
            (data["momentum"] > self.momentum_threshold)
            & (data["close"] > data["ma"])
            & (data["momentum"].shift(1) <= self.momentum_threshold)
        ).astype(int)

        # 出场信号: 动量转负或价格跌破均线
        data["sell_signal"] = (
            (data["momentum"] < 0)
            | (
                (data["close"] < data["ma"])
                & (data["close"].shift(1) >= data["ma"].shift(1))
            )
        ).astype(int)

        data = data.drop(["momentum", "ma"], axis=1)
        return data


class StrategyBreakout(Strategy):
    """突破策略

    基于价格突破历史高低点进行交易的策略，是经典的趋势跟踪策略。

    策略逻辑:
    - 入场条件: 价格突破过去N天的最高价
    - 出场条件: 价格跌破过去M天的最低价

    参数:
    - lookback_period: 回溯期，计算历史高低价的天数（默认20天）
    - atr_multiplier: ATR倍数，用于动态止损（默认2.0）
    - use_atr_stop: 是否使用ATR跟踪止损（默认False）

    适用场景:
    - 趋势明显的市场
    - 捕捉突破后的趋势行情
    - 适合短线和波段交易
    """

    def __init__(
        self,
        lookback_period: int = 20,
        atr_multiplier: float = 2.0,
        use_atr_stop: bool = False,
    ):
        super().__init__()
        self.lookback_period = lookback_period
        self.atr_multiplier = atr_multiplier
        self.use_atr_stop = use_atr_stop

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产突破策略的买卖信号"""
        data = data.copy()

        # 计算历史高低价
        data["highest"] = (
            data["high"].rolling(window=self.lookback_period, min_periods=1).max()
        )
        data["lowest"] = (
            data["low"].rolling(window=self.lookback_period, min_periods=1).min()
        )

        if self.use_atr_stop:
            # 计算ATR
            high_low = data["high"] - data["low"]
            high_close = abs(data["high"] - data["close"].shift())
            low_close = abs(data["low"] - data["close"].shift())
            data["tr"] = pd.concat([high_low, high_close, low_close], axis=1).max(
                axis=1
            )
            data["atr"] = (
                data["tr"].rolling(window=self.lookback_period, min_periods=1).mean()
            )
            data["atr_stop"] = data["close"] - data["atr"] * self.atr_multiplier

            # 入场信号: 价格突破历史最高价
            data["buy_signal"] = (
                (data["close"] > data["highest"].shift(1))
                & (data["close"].shift(1) <= data["highest"].shift(2))
            ).astype(int)

            # 出场信号: 价格跌破ATR跟踪止损位
            data["sell_signal"] = ((data["close"] < data["atr_stop"].shift(1))).astype(
                int
            )

            data = data.drop(["highest", "lowest", "tr", "atr", "atr_stop"], axis=1)
        else:
            # 入场信号: 价格突破历史最高价
            data["buy_signal"] = (
                (data["close"] > data["highest"].shift(1))
                & (data["close"].shift(1) <= data["highest"].shift(2))
            ).astype(int)

            # 出场信号: 价格跌破历史最低价
            data["sell_signal"] = (
                (data["close"] < data["lowest"].shift(1))
                & (data["close"].shift(1) >= data["lowest"].shift(2))
            ).astype(int)

            data = data.drop(["highest", "lowest"], axis=1)

        return data


class StrategyDualThrust(Strategy):
    """Dual Thrust 策略

    由Michael Chalek开发的经典日内交易策略，通过计算上下轨进行突破交易。

    策略逻辑:
    - 入场条件: 开盘后价格突破上轨（最高价-收盘价的N倍区间）
    - 出场条件: 价格跌破下轨或触及止损

    参数:
    - k1: 上轨系数（默认0.5）
    - k2: 下轨系数（默认0.5）
    - lookback_period: 回溯期（默认20天）

    适用场景:
    - 日内交易
    - 趋势明显的市场
    - 捕捉突破行情
    """

    def __init__(
        self,
        k1: float = 0.5,
        k2: float = 0.5,
        lookback_period: int = 20,
    ):
        super().__init__()
        self.k1 = k1
        self.k2 = k2
        self.lookback_period = lookback_period

    def _execute_one(self, data: pd.DataFrame) -> pd.DataFrame:
        """对单个标的生产Dual Thrust策略的买卖信号"""
        data = data.copy()

        # 计算历史周期的高低收
        data["hh"] = (
            data["high"].rolling(window=self.lookback_period, min_periods=1).max()
        )
        data["lc"] = (
            data["close"].rolling(window=self.lookback_period, min_periods=1).min()
        )
        data["ll"] = (
            data["low"].rolling(window=self.lookback_period, min_periods=1).min()
        )

        # 计算Range: max(HH-LL, HH-LC)
        range1 = data["hh"] - data["ll"]
        range2 = data["hh"] - data["lc"]
        data["range_val"] = range1.where(range1 > range2, range2)

        # 计算上下轨
        data["upper"] = data["open"] + self.k1 * data["range_val"]
        data["lower"] = data["open"] - self.k2 * data["range_val"]

        # 入场信号: 价格突破上轨
        data["buy_signal"] = (
            (data["close"] > data["upper"].shift(1))
            & (data["close"].shift(1) <= data["upper"].shift(2))
        ).astype(int)

        # 出场信号: 价格跌破下轨
        data["sell_signal"] = (
            (data["close"] < data["lower"].shift(1))
            & (data["close"].shift(1) >= data["lower"].shift(2))
        ).astype(int)

        data = data.drop(["hh", "lc", "ll", "range_val", "upper", "lower"], axis=1)
        return data