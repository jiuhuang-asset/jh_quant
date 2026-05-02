"""
Data Transformation Utilities

Provides data transformation functions for factor calculations.
"""

from typing import Optional, List
import pandas as pd
import numpy as np


def daily_to_monthly(
    df: pd.DataFrame,
    price_columns: Optional[List[str]] = None,
    volume_columns: Optional[List[str]] = None,
    trade_dates: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Convert daily data to monthly data.

    Args:
        df: Daily data DataFrame with 'date', 'symbol', 'close' columns minimum
        price_columns: Price columns to aggregate (default: ['open', 'close', 'high', 'low'])
        volume_columns: Volume columns to aggregate (default: ['volume', 'amount'])
        trade_dates: Optional trading dates DataFrame with 'trade_date' column.
                     If provided, uses the last trade date of each month as the month end date.

    Returns:
        Monthly aggregated DataFrame

    Example:
        >>> daily_df = get_stock_daily(start_date='2020-01-01')
        >>> monthly_df = daily_to_monthly(daily_df)
    """
    if df.empty:
        return df.copy()

    df = df.copy()

    # Ensure date format
    df["date"] = pd.to_datetime(df["date"])

    # Default columns
    if price_columns is None:
        price_columns = ["open", "close", "high", "low"]
    if volume_columns is None:
        volume_columns = ["volume", "amount"]

    df = df.sort_values(["symbol", "date"])

    # Add year-month identifier
    df["year_month"] = df["date"].dt.to_period("M")

    # Define aggregation rules
    agg_rules = {}

    for col in price_columns:
        if col in df.columns:
            if col == "open":
                agg_rules[col] = "first"  # Month start price
            elif col == "close":
                agg_rules[col] = "last"  # Month end price
            elif col == "high":
                agg_rules[col] = "max"  # Monthly high
            elif col == "low":
                agg_rules[col] = "min"  # Monthly low

    for col in volume_columns:
        if col in df.columns:
            agg_rules[col] = "sum"  # Monthly total

    # Execute groupby aggregation (date column will be replaced with actual month end)
    monthly_df = (
        df.groupby(["symbol", "year_month"], sort=False).agg(agg_rules).reset_index()
    )

    # Calculate month end date
    if trade_dates is not None and "trade_date" in trade_dates.columns:
        # Use the last trade date of each month from trading calendar
        trade_dates = trade_dates.copy()
        trade_dates["trade_date"] = pd.to_datetime(trade_dates["trade_date"])
        trade_dates["year_month"] = trade_dates["trade_date"].dt.to_period("M")
        month_end_trade_dates = (
            trade_dates.groupby("year_month")["trade_date"].max().reset_index()
        )
        month_end_trade_dates.columns = ["year_month", "month_end_date"]

        # Merge to get the month end date for each year_month
        monthly_df = monthly_df.merge(
            month_end_trade_dates, on="year_month", how="left"
        )
        monthly_df["date"] = monthly_df["month_end_date"]
        monthly_df = monthly_df.drop(columns=["year_month", "month_end_date"])
    else:
        # Calculate actual month end date (same for all stocks)
        monthly_df["date"] = monthly_df["year_month"].dt.end_time
        monthly_df = monthly_df.drop(columns=["year_month"])

    return monthly_df


def calculate_returns(
    df: pd.DataFrame, price_column: str = "close", method: str = "simple"
) -> pd.DataFrame:
    """
    Calculate stock returns.

    Args:
        df: DataFrame with 'symbol' and price column
        price_column: Price column name
        method: 'simple' for simple returns, 'log' for log returns

    Returns:
        DataFrame with 'return' column added
    """
    df = df.copy()
    df = df.sort_values(["symbol", "date"])

    # Ensure price column is numeric
    df[price_column] = pd.to_numeric(df[price_column], errors="coerce")

    if method == "simple":
        df["return"] = df.groupby("symbol")[price_column].pct_change()
    elif method == "log":
        df["return"] = np.log(df[price_column]).groupby(df["symbol"]).diff()
    else:
        raise ValueError(f"Unknown method: {method}")

    return df


def calculate_log_returns(
    df: pd.DataFrame, price_column: str = "close"
) -> pd.DataFrame:
    """
    Calculate log returns.

    Args:
        df: DataFrame with price data
        price_column: Price column name

    Returns:
        DataFrame with 'log_return' column added
    """
    return calculate_returns(df, price_column, method="log")


def calculate_cumulative_returns(
    df: pd.DataFrame, return_column: str = "return"
) -> pd.DataFrame:
    """
    Calculate cumulative returns.

    Args:
        df: DataFrame with return data
        return_column: Return column name

    Returns:
        DataFrame with cumulative returns
    """
    df = df.copy()
    df = df.sort_values(["symbol", "date"])

    df["cumulative_return"] = (1 + df[return_column]).groupby(
        df["symbol"]
    ).cumprod() - 1

    return df


def resample_to_period(
    df: pd.DataFrame,
    freq: str = "M",
    price_columns: Optional[List[str]] = None,
    agg_method: str = "last",
) -> pd.DataFrame:
    """
    Resample data to different frequency.

    Args:
        df: DataFrame with date column
        freq: Frequency ('M' for monthly, 'W' for weekly, 'Q' for quarterly)
        price_columns: Price columns to aggregate
        agg_method: Aggregation method ('last', 'mean', 'sum')

    Returns:
        Resampled DataFrame
    """
    if df.empty:
        return df.copy()

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    if price_columns is None:
        price_columns = [
            col for col in df.columns if col not in ["symbol", "year_month"]
        ]

    if "symbol" in df.columns:
        pieces = []
        for symbol, group in df.groupby("symbol", sort=False):
            group = group.sort_values("date").set_index("date")
            if agg_method == "last":
                resampled = group[price_columns].resample(freq).last()
            elif agg_method == "mean":
                resampled = group[price_columns].resample(freq).mean()
            elif agg_method == "sum":
                resampled = group[price_columns].resample(freq).sum()
            else:
                raise ValueError(f"Unknown agg_method: {agg_method}")
            resampled = resampled.reset_index()
            resampled["symbol"] = symbol
            pieces.append(resampled)

        if not pieces:
            return pd.DataFrame(columns=["date", "symbol"] + price_columns)

        return pd.concat(pieces, ignore_index=True)

    df = df.sort_values("date").set_index("date")
    if agg_method == "last":
        resampled = df[price_columns].resample(freq).last()
    elif agg_method == "mean":
        resampled = df[price_columns].resample(freq).mean()
    elif agg_method == "sum":
        resampled = df[price_columns].resample(freq).sum()
    else:
        raise ValueError(f"Unknown agg_method: {agg_method}")

    return resampled.reset_index()


def align_dates(
    target_df: pd.DataFrame, source_df: pd.DataFrame, date_column: str = "date"
) -> pd.DataFrame:
    """
    Align dates between two DataFrames.

    Args:
        target_df: DataFrame to align to
        source_df: DataFrame to get dates from
        date_column: Date column name

    Returns:
        Aligned target DataFrame
    """
    target_dates = pd.to_datetime(target_df[date_column])
    source_dates = pd.to_datetime(source_df[date_column])
    common_dates = pd.Index(target_dates.drop_duplicates()).intersection(
        pd.Index(source_dates.drop_duplicates())
    )
    return target_df[target_dates.isin(common_dates)]


def get_month_end_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Get month-end dates for each stock.

    Args:
        df: DataFrame with date and symbol columns

    Returns:
        DataFrame with month-end dates
    """
    if df.empty:
        return df.copy()

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])
    df["year_month"] = df["date"].dt.to_period("M")

    month_end = (
        df.groupby(["symbol", "year_month"], sort=False)["date"].max().reset_index()
    )
    month_end.columns = ["symbol", "year_month", "month_end_date"]

    return month_end
