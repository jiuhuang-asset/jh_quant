import webview
import pandas as pd
import os
from rich import print as rprint
from jh_quant.data import get_code_date_col

class BacktestingView:
    def __init__(
        self,
        trading_hist: pd.DataFrame,
        perf_data: pd.DataFrame,
    ):  
        code_column, dt_column = get_code_date_col(trading_hist)
        self.code_column = code_column
        self.dt_column = dt_column
        cols = [
            code_column,
            dt_column,
            "open",
            "high",
            "low",
            "close",
            "volume",
            "buy_signal",
            "sell_signal",
            "strategy",
            "strategy_return",
            "cumulative_return",
            "drawdown",
        ]
        # 确保日期列存在
        available_cols = [c for c in cols if c in trading_hist.columns]
        self.trading_hist = (
            trading_hist[available_cols]
            .rename(columns={dt_column: "date"})
            .assign(date=lambda x: x["date"].astype(str))
            .to_dict(orient="records")
        )
        # 区分数值字段和非数值字段，分别填充
        non_numeric_cols = ["symbol", "strategy", "name", "industry"]
        numeric_cols = [c for c in perf_data.columns if c not in non_numeric_cols]
        perf_filled = perf_data.copy()
        perf_filled[numeric_cols] = perf_filled[numeric_cols].fillna(0)
        perf_filled[non_numeric_cols] = perf_filled[non_numeric_cols].fillna("-")
        self.perf_data = perf_filled.to_dict(orient="records")

    def init_data(self):
        return {
            "trading_hist": self.trading_hist,
            "perf_data": self.perf_data,
            "code_column": self.code_column,
            "dt_column": self.dt_column,
        }


def display_backtesting(
    trading_hist: pd.DataFrame, perf_data: pd.DataFrame
):
    """显示回测结果可视化看板。

    使用 PyWebView 打开本地 HTML 页面展示回测的交易历史和策略表现指标。
    支持日频和分钟级数据的时间字段。

    Args:
        trading_hist: 回测交易历史数据 DataFrame，需包含以下列：
        perf_data: 策略表现指标 DataFrame，包含各策略的绩效指标

    Returns:
        None: 该函数直接打开可视化窗口，不返回值
    """
    rprint("[cyan]  Starting backtesting visualization...")
    api = BacktestingView(trading_hist, perf_data)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(current_dir, "front_src", "bt-dash", "index.html")

    window = webview.create_window("回测结果", html_path, js_api=api)
    webview.start()



class FactorsView:
    def __init__(
        self,
        factor_returns: pd.DataFrame,
    ):
        self._check_input(factor_returns)
        fr = factor_returns.copy()
        fr["date"] = fr["date"].astype(str)
        fr["factor_return"] = fr["factor_return"].fillna(0)
        self.factor_returns = fr.to_dict(orient="records")

    def _check_input(self, factor_returns):
        for col in ["date", "model_name", "factor_name", "factor_return"]:
            if col not in factor_returns.columns:
                raise ValueError(f"Column {col} not found in factor_returns")

    def init_data(self):
        return {
            "factor_returns": self.factor_returns,
        }   
    

def display_factors(
    factor_returns: pd.DataFrame
):
    rprint("[cyan]  Starting factor analysis visualization...")
    api = FactorsView(factor_returns)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(current_dir, "front_src", "factors-dash", "index.html")

    window = webview.create_window("因子分析", html_path, js_api=api)
    webview.start()