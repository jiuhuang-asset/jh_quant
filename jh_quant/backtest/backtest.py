from __future__ import annotations

from typing import Callable, Optional, Tuple

import pandas as pd
from rich import print as rprint
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from jh_quant.data import JhDataType, get_code_date_col

from .metrics import cal_metrics_from_returns, calculate_strategy_returns
from .rules import RiskRule, risk_manage_single
from .strategy import Strategy

def build_position(
    df: pd.DataFrame,
    buy_signal_name: str = "buy_signal",
    sell_signal_name: str = "sell_signal",
    use_next_day_return: bool = True,
    rules: list[RiskRule] | None = None,
) -> pd.DataFrame:
    """根据买卖信号构建持仓，结合风险管理规则。

    Args:
        df: 包含股票数据和信号的 DataFrame。
        buy_signal_name: 买入信号列名。
        sell_signal_name: 卖出信号列名。
        use_next_day_return: 是否将信号应用到次日持仓。
        rules: 风险规则列表，可为 None（不启用风控）。

    Returns:
        新增 'position' 列的 DataFrame。
    """
    code_col, dt_col = get_code_date_col(df)
    result_df = df.sort_values([code_col, dt_col]).reset_index(drop=True)

    if use_next_day_return:
        buy_signal = result_df.groupby(code_col)[buy_signal_name].shift(1).fillna(0)
        sell_signal = result_df.groupby(code_col)[sell_signal_name].shift(1).fillna(0)
    else:
        buy_signal = result_df[buy_signal_name].fillna(0)
        sell_signal = result_df[sell_signal_name].fillna(0)

    result_df["position"] = 0

    for code in result_df[code_col].unique():
        stock_mask = result_df[code_col] == code
        stock_data = result_df.loc[stock_mask].copy()
        stock_buy_signal = buy_signal.loc[stock_mask]
        stock_sell_signal = sell_signal.loc[stock_mask]
        positions = risk_manage_single(
            stock_data, stock_buy_signal, stock_sell_signal, rules
        )
        result_df.loc[stock_mask, "position"] = positions

    return result_df


def evaluate_strategies(
    price: pd.DataFrame,
    strategies: dict[str, Strategy],
    use_next_day_return: bool = True,
    metric_func: Callable = cal_metrics_from_returns,
    rules: dict[str, list[RiskRule]] | None = None,
    commission_rate: float = 0.0002,
    stamp_tax_rate: float = 0.0005,
) -> Tuple[pd.DataFrame, JhDataType]:
    """评估多个策略的表现。

    Args:
        price: 价格数据。
        strategies: 策略字典。
        use_next_day_return: 是否使用次日收益率。
        metric_func: 指标计算函数。
        rules: 每个策略对应的风险规则列表，键为策略名称。
        commission_rate: 佣金费率。
        stamp_tax_rate: 印花税率。

    Returns:
        (combined_performance, trading_history)。
    """
    if rules is None:
        rules = {}

    code_col, _ = get_code_date_col(price)
    perf_results: dict[str, pd.Series] = {}
    _trading_history_datas: list[pd.DataFrame] = []
    _extra_cols = [
        "buy_signal",
        "sell_signal",
        "position",
        "strategy",
        "strategy_return",
        "cumulative_return",
        "drawdown",
    ]
    _trading_history_cols = [
        c for c in price.columns.to_list() + _extra_cols if c != "created_at"
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task(
            f"[cyan]Evaluating {len(strategies)} strategies...", total=len(strategies)
        )
        for strat_name, strat in strategies.items():
            df_sig = strat(price)
            strat_rules = rules.get(strat_name)
            df_with_pos = build_position(
                df_sig,
                buy_signal_name="buy_signal",
                sell_signal_name="sell_signal",
                use_next_day_return=use_next_day_return,
                rules=strat_rules,
            )
            strat_trading_histroy = calculate_strategy_returns(
                df_with_pos, commission_rate, stamp_tax_rate
            )
            metric_series = metric_func(strat_trading_histroy)
            perf_results[strat_name] = metric_series
            strat_trading_histroy["strategy"] = strat_name
            _trading_history_datas.append(strat_trading_histroy)
            progress.update(task, advance=1)
    # Combine into a DataFrame. Use union of stock_codes present in any result
    combined = pd.DataFrame(perf_results)
    combined = combined.reset_index()
    combined_performance = combined.rename(
        columns={"level_0": code_col, "level_1": "metric"}
    )
    concated_trading_hist =  pd.concat(_trading_history_datas).reset_index()[_trading_history_cols]
    return (
        combined_performance,
        JhDataType(concated_trading_hist, price.jh_dt)

    )


def backtest(
    strategies: dict[str, Strategy],
    price_data: JhDataType,
    stock_info: Optional[pd.DataFrame] = None,
    rules: dict[str, list[RiskRule]] | None = None,
    commission_rate: float = 0.0002,
    stamp_tax_rate: float = 0.0005,
    metric_decimal: int = 2,
    use_next_day_return: bool = True,
) -> Optional[Tuple[JhDataType, pd.DataFrame]]:
    """回测策略表现。

    Args:
        strategies: 策略字典，键为策略名称，值为策略函数。
        price_data: 价格数据（JhDataType）。
        stock_info: 股票信息，可选。需包含 name、industry 列。
        rules: 每个策略对应的风险规则列表，键为策略名称。
        commission_rate: 佣金费率（默认 0.0002）。
        stamp_tax_rate: 印花税率（默认 0.0005）。
        metric_decimal: 指标小数位数（默认 2）。
        use_next_day_return: 是否使用次日收益率（默认 True）。

    Returns:
        (trading_history, reshaped_eval_results)，若无数据则返回 None。
    """
    if price_data.empty:
        rprint("[bold yellow]没有价格数据")
        return None

    if not strategies:
        rprint("[bold yellow]没有策略需要评估")
        return None

    code_col = price_data.code_col

    eval_results, trading_history = evaluate_strategies(
        price_data,
        strategies,
        rules=rules or {},
        use_next_day_return=use_next_day_return,
        commission_rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
    )
    eval_results = eval_results.round(metric_decimal)
    melted_eval_results = eval_results.melt(
        id_vars=[code_col, "metric"], var_name="strategy", value_name="value"
    )

    reshaped_eval_results = melted_eval_results.pivot_table(
        index=[code_col, "strategy"], columns="metric", values="value"
    ).reset_index()

    reshaped_eval_results.columns.name = None

    if stock_info is not None and not stock_info.empty:
        stock_info_clean = stock_info[[code_col, "name", "industry"]].drop_duplicates()
        reshaped_eval_results = reshaped_eval_results.merge(
            stock_info_clean,
            on=code_col,
            how="left",
        )

    return trading_history, reshaped_eval_results