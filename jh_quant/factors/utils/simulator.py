"""
Missing Data Simulator

Simulates missing historical data that is not available in jiuhuang-pysdk.

Notes on missing data:
1. Historical market cap - only current value available in stock_individual_info
2. Some fundamental metrics may be incomplete
3. Idiosyncratic volatility requires historical data to compute

This module provides simulation functions with clear documentation
that the data is simulated and should be used with caution.
"""
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# Flag to track simulated data usage
SIMULATED_DATA_WARNING = """
WARNING: This data is SIMULATED and not from actual market data.
Use with caution in production environments.
"""


def simulate_missing_data(
    data_type: str,
    reference_data: pd.DataFrame,
    **kwargs
) -> pd.DataFrame:
    """
    Simulate missing data based on available reference data.

    Args:
        data_type: Type of missing data ('historical_mkt_cap', 'bm', 'roe', etc.)
        reference_data: Reference DataFrame to base simulation on
        **kwargs: Additional parameters

    Returns:
        Simulated DataFrame

    Raises:
        ValueError: If data_type is not supported
    """
    if data_type == 'historical_mkt_cap':
        return simulate_historical_market_cap(reference_data, **kwargs)
    elif data_type == 'bm':
        return simulate_book_to_market(reference_data, **kwargs)
    elif data_type == 'roe':
        return simulate_roe(reference_data, **kwargs)
    elif data_type == 'idio_vol':
        return simulate_idiosyncratic_volatility(reference_data, **kwargs)
    else:
        raise ValueError(f"Unknown data type: {data_type}")


def simulate_historical_market_cap(
    current_mkt_cap: pd.DataFrame,
    dates: Optional[List[str]] = None,
    volatility: float = 0.3
) -> pd.DataFrame:
    """
    Simulate historical market cap based on current values.

    NOTE: jiuhuang-pysdk only provides current market cap (stock_individual_info),
    not historical values. This function simulates historical data using
    a random walk assumption.

    Args:
        current_mkt_cap: DataFrame with current market cap [symbol, mkt_cap]
        dates: List of dates to simulate (default: last 5 years monthly)
        volatility: Annual volatility of market cap (default 30%)

    Returns:
        DataFrame with [symbol, date, mkt_cap]

    Warning:
        This is simulated data - not actual historical market cap.
    """
    print(SIMULATED_DATA_WARNING)

    # Generate dates if not provided
    if dates is None:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 5)
        dates = pd.date_range(start=start_date, end=end_date, freq='M').strftime('%Y-%m-%d').tolist()

    if current_mkt_cap.empty:
        return pd.DataFrame(columns=['symbol', 'date', 'mkt_cap'])

    results = []

    # Monthly return standard deviation
    monthly_vol = volatility / np.sqrt(12)

    for _, row in current_mkt_cap.iterrows():
        symbol = row['symbol']
        current_cap = row.get('mkt_cap', row.get('market_cap', 1e9))

        if pd.isna(current_cap) or current_cap <= 0:
            current_cap = 1e9  # Default to 1B if missing

        # Simulate using random walk
        np.random.seed(hash(symbol) % (2**32))

        for date in dates:
            # Random walk with mean reversion
            change = np.random.normal(0, monthly_vol)
            cap = current_cap * (1 + change)

            results.append({
                'symbol': symbol,
                'date': date,
                'mkt_cap': cap,
                'is_simulated': True  # Flag to indicate simulated data
            })

            current_cap = cap

    df = pd.DataFrame(results)
    return df


def simulate_book_to_market(
    stock_info: pd.DataFrame,
    dates: Optional[List[str]] = None,
    bm_ratio: float = 0.5
) -> pd.DataFrame:
    """
    Simulate book-to-market ratio.

    NOTE: jiuhuang-pysdk may have incomplete book value data.
    This function provides a simulation based on industry averages.

    Args:
        stock_info: DataFrame with stock information
        dates: Dates to simulate
        bm_ratio: Target average BM ratio (default 0.5)

    Returns:
        DataFrame with [symbol, date, bm]
    """
    print(SIMULATED_DATA_WARNING)

    if dates is None:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 5)
        dates = pd.date_range(start=start_date, end=end_date, freq='M').strftime('%Y-%m-%d').tolist()

    if stock_info.empty:
        return pd.DataFrame(columns=['symbol', 'date', 'bm'])

    results = []

    for _, row in stock_info.iterrows():
        symbol = row['symbol']

        # Generate BM with some variation around target
        np.random.seed(hash(symbol) % (2**32))
        base_bm = bm_ratio + np.random.normal(0, 0.2)

        for date in dates:
            # Add time variation
            monthly_var = np.random.normal(0, 0.05)
            bm = max(0.1, base_bm + monthly_var)  # Ensure positive

            results.append({
                'symbol': symbol,
                'date': date,
                'bm': bm,
                'is_simulated': True
            })

    df = pd.DataFrame(results)
    return df


def simulate_roe(
    stock_info: pd.DataFrame,
    dates: Optional[List[str]] = None,
    avg_roe: float = 0.10
) -> pd.DataFrame:
    """
    Simulate Return on Equity (ROE).

    NOTE: ROE requires profitability data which may be incomplete.
    This provides a simulation based on typical A-share averages.

    Args:
        stock_info: DataFrame with stock information
        dates: Dates to simulate
        avg_roe: Target average ROE (default 10%)

    Returns:
        DataFrame with [symbol, date, roe]
    """
    print(SIMULATED_DATA_WARNING)

    if dates is None:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 5)
        dates = pd.date_range(start=start_date, end=end_date, freq='M').strftime('%Y-%m-%d').tolist()

    if stock_info.empty:
        return pd.DataFrame(columns=['symbol', 'date', 'roe'])

    results = []

    for _, row in stock_info.iterrows():
        symbol = row['symbol']

        # Generate ROE with mean reversion to industry average
        np.random.seed(hash(symbol) % (2**32))
        base_roe = avg_roe + np.random.normal(0, 0.05)

        for date in dates:
            # Add autocorrelation and noise
            roe = base_roe + np.random.normal(0, 0.02)
            roe = max(-0.5, min(0.5, roe))  # Clip extreme values

            results.append({
                'symbol': symbol,
                'date': date,
                'roe': roe,
                'is_simulated': True
            })

            # Mean reversion
            base_roe = 0.7 * base_roe + 0.3 * avg_roe

    df = pd.DataFrame(results)
    return df


def simulate_idiosyncratic_volatility(
    stock_returns: pd.DataFrame,
    window: int = 252
) -> pd.DataFrame:
    """
    Simulate idiosyncratic volatility.

    NOTE: Computing true idiosyncratic volatility requires factor models
    and historical data. This provides a simplified estimate.

    Args:
        stock_returns: DataFrame with [symbol, date, return]
        window: Rolling window for volatility calculation

    Returns:
        DataFrame with [symbol, date, idio_vol]
    """
    if stock_returns.empty:
        return pd.DataFrame(columns=['symbol', 'date', 'idio_vol'])

    results = []

    for symbol in stock_returns['symbol'].unique():
        stock_data = stock_returns[stock_returns['symbol'] == symbol].copy()
        stock_data = stock_data.sort_values('date')

        # Calculate rolling standard deviation
        stock_data['idio_vol'] = stock_data['return'].rolling(window=window).std()

        # Add some noise for stocks with insufficient history
        np.random.seed(hash(symbol) % (2**32))
        stock_data['idio_vol'] = stock_data['idio_vol'].fillna(
            np.random.uniform(0.02, 0.05)
        )

        stock_data['is_simulated'] = stock_data['idio_vol'].isna()

        results.append(stock_data[['symbol', 'date', 'idio_vol', 'is_simulated']])

    df = pd.concat(results, ignore_index=True)
    return df
