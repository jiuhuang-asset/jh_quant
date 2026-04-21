import pandas as pd
import quantstats as qs
import numpy as np
from jh_quant.data import get_code_date_col

__all__ = ["cal_metrics_from_returns"]


def calculate_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate daily returns for each stock.

    Args:
        df: DataFrame with stock data

    Returns:
        DataFrame with added 'return' column
    """
    # Get code column and dt column from df
    code_col, dt_col = get_code_date_col(df)
    result_df = df.sort_values([code_col, dt_col]).reset_index(drop=True)
    result_df["return"] = result_df.groupby(code_col)["close"].pct_change().fillna(0)
    return result_df


def calculate_strategy_returns(
    df: pd.DataFrame,
    commission_rate: float = 0,
    stamp_tax_rate: float = 0,
) -> pd.DataFrame:
    """Calculate strategy returns based on position and market returns, including transaction fees.

    Args:
        df: DataFrame with stock data and positions
        commission_rate: 买卖双向手续费率
        stamp_tax_rate: 印花税率，仅对卖出收取 (默认 0.0005 = 0.05%)

    Returns:
        DataFrame with added 'strategy_return' column
    """

    code_col, _ = get_code_date_col(df)

    result_df = calculate_returns(df)

    result_df["strategy_return"] = result_df["return"] * result_df["position"]

    result_df["prev_position"] = (
        result_df.groupby(code_col)["position"].shift(1).fillna(0)
    )
    result_df["is_selling"] = (result_df["position"] == 0) & (
        result_df["prev_position"] == 1
    )
    result_df["commission_fee"] = (
        (result_df["position"] != result_df["prev_position"])
        & (result_df["position"] == 1)
    ) * commission_rate  # 买入时的手续费

    # 卖出时的总费用 = 手续费 + 印花税
    result_df["selling_fee"] = result_df["is_selling"] * (
        commission_rate + stamp_tax_rate
    )
    result_df["total_fees"] = result_df["commission_fee"] + result_df["selling_fee"]

    result_df["strategy_return"] = (
        result_df["strategy_return"] - result_df["total_fees"]
    )

    # Calculate cumulative return
    result_df["cumulative_return"] = result_df.groupby(code_col)[
        "strategy_return"
    ].transform(lambda x: (1 + x).cumprod() - 1)

    # Calculate max drawdown
    result_df["drawdown"] = result_df.groupby(code_col)["cumulative_return"].transform(
        lambda x: (x.cummax() - x) / (1 + x.cummax())
    )

    result_df = result_df.drop(
        ["prev_position", "is_selling", "commission_fee", "selling_fee", "total_fees"],
        axis=1,
    )

    return result_df


def cal_metrics_from_returns(df: pd.DataFrame) -> pd.Series:
    """Calculate metrics from already computed strategy returns.

    Args:
        df: DataFrame with stock data and 'strategy_return' column already calculated.

    Returns:
        pd.Series with multi-level index (metric_name, code).
    """

    code_col, dt_col = get_code_date_col(df)

    metrics = [
        "累积收益率",
        "最大回撤",
        "胜率",
        "夏普比率",
        "卡玛比率",
        "索提诺比率",
        "收益率标准差",
        "风险价值(VaR)",
        "条件VaR(CVaR)",
        "盈亏比",
        "欧米伽比率",
    ]

    results = []
    for code, group in df.groupby(code_col):
        returns = group.set_index(dt_col)["strategy_return"]

        cumulative_return = group.groupby(code_col)["cumulative_return"].last().iloc[0]
        max_dd = qs.stats.max_drawdown(returns)
        win_rate = (returns > 0).mean()
        sharpe = qs.stats.sharpe(returns)
        calmar = qs.stats.calmar(returns) if max_dd != 0 else np.nan
        sortino = qs.stats.sortino(returns)
        volatility = returns.std()
        var = qs.stats.value_at_risk(returns)
        cvar = qs.stats.cvar(returns)
        profit_factor = qs.stats.profit_factor(returns)
        omega = qs.stats.omega(returns)

        code_results = pd.Series(
            [
                cumulative_return,
                max_dd,
                win_rate,
                sharpe,
                calmar,
                sortino,
                volatility,
                var,
                cvar,
                profit_factor,
                omega,
            ],
            index=pd.MultiIndex.from_product([[code], metrics]),
        )
        results.append(code_results)

    combined_series = pd.concat(results)
    return combined_series