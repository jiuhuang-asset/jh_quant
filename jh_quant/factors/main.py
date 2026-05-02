"""
Factor Calculation Framework Main Entry

Provides unified interface for factor return and exposure calculations.

设计：每个因子类型对应一个数据准备类 (FactorReturnData子类)
"""

from typing import Optional, List, Dict, Union
import pandas as pd
from .config import FactorType, CalculationMethod, TimePeriod, DEFAULT_N_JOBS
from .data.base import get_factor_data_class
from .factors.general import GeneralFactorCalculator
from .exposure import StockExposureCalculator, calculate_stock_exposures


class FactorEngine:
    """
    Main factor calculation engine.

    支持所有因子模型的计算:
    - FF3, FF5, CARHART, NOVY_MARX
    - HOU_XUE_ZHANG, DHS
    """

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        """
        Initialize the factor engine.

        Args:
            api_key: API密钥（可选，从环境变量读取）
            api_url: API地址（可选）
        """
        self.api_key = api_key
        self.api_url = api_url

    def calculate_factor_returns(
        self,
        factor_type: FactorType = FactorType.FF3,
        method: CalculationMethod = CalculationMethod.SIMPLE,
        period: TimePeriod = TimePeriod.MONTHLY,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        n_jobs: Optional[int] = None,
        verbose: bool = True,
        use_polars: bool = True,
    ) -> pd.DataFrame:
        """
        Calculate factor returns.

        Args:
            factor_type: Type of factor model
            method: Calculation method (CLASSIC or SIMPLE)
            period: Time period (MONTHLY or DAILY)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            symbols: Optional list of stock symbols
            verbose: Whether to print progress
            use_polars: Whether to use Polars acceleration (default True)

        Returns:
            DataFrame with factor returns (date as index)
        """
        if verbose:
            print(f"Calculating {factor_type.value} factors...")
            print(f"  Method: {method.value}")
            print(f"  Period: {period.value}")
            print(f"  Date range: {start_date} to {end_date}")
            print(f"  N Jobs: {n_jobs or DEFAULT_N_JOBS}")
        data_class = get_factor_data_class(factor_type)
        data_provider = data_class(api_key=self.api_key, api_url=self.api_url)

        prepared = data_provider.prepare_data(
            period=period, start_date=start_date, end_date=end_date, symbols=symbols
        )

        stock_returns = prepared.get("stock_returns")

        # CAPM uses market_return instead of market_cap
        if factor_type == FactorType.CAPM:
            market_cap = prepared.get("market_return")
        else:
            market_cap = prepared.get("market_cap")

        fundamentals = {
            k: v
            for k, v in prepared.items()
            if k not in ["stock_returns", "market_cap", "market_return"]
        }

        calculator = GeneralFactorCalculator(
            factor_type=factor_type,
            method=method,
            period=period,
            n_jobs=n_jobs,
            use_polars=use_polars,
        )

        factor_returns = calculator.calculate(
            stock_returns=stock_returns,
            market_cap=market_cap,
            fundamentals=fundamentals,
        )

        if verbose:
            period_label = "days" if period == TimePeriod.DAILY else "months"
            print(
                f"\nCalculated {len(factor_returns)} {period_label} of factor returns"
            )

        return factor_returns

    def calculate_all_factors(
        self,
        factor_types: Optional[List[FactorType]] = None,
        method: CalculationMethod = CalculationMethod.SIMPLE,
        period: TimePeriod = TimePeriod.MONTHLY,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        n_jobs: Optional[int] = None,
        verbose: bool = True,
        use_polars: bool = True,
    ) -> Dict[FactorType, pd.DataFrame]:
        """
        Calculate multiple factor returns at once.

        Args:
            factor_types: List of factor types to calculate
            method: Calculation method
            start_date: Start date
            end_date: End date
            symbols: Stock symbols
            verbose: Whether to print progress
            use_polars: Whether to use Polars acceleration (default True)

        Returns:
            Dict mapping factor type to factor returns DataFrame
        """
        if factor_types is None:
            factor_types = FactorType.list_all()

        results = {}
        for ft in factor_types:
            if verbose:
                print(f"\n{'='*40}")
            try:
                results[ft] = self.calculate_factor_returns(
                    factor_type=ft,
                    method=method,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                    n_jobs=n_jobs,
                    verbose=verbose,
                    use_polars=use_polars,
                )
            except Exception as e:
                if verbose:
                    print(f"Failed to calculate {ft.value}: {e}")

        return results

    def calculate_stock_exposures(
        self,
        stock_returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        n_jobs: int = 4,
        verbose: bool = True,
    ) -> pd.DataFrame:
        """
        Calculate stock factor exposures.

        Args:
            stock_returns: DataFrame with [symbol, date, return]
            factor_returns: DataFrame with factor returns
            n_jobs: Parallel jobs
            verbose: Whether to print progress

        Returns:
            DataFrame with factor exposures
        """
        if verbose:
            print("Calculating stock factor exposures...")

        if stock_returns.empty:
            raise ValueError("stock_returns is empty")

        calculator = StockExposureCalculator(n_jobs=n_jobs)
        exposures = calculator.calculate_all_exposures(
            stock_returns, factor_returns, verbose=verbose
        )

        return exposures


def calculate_factor_returns(
    factor_type: Union[str, FactorType] = FactorType.FF3,
    method: Union[str, CalculationMethod] = CalculationMethod.SIMPLE,
    period: Union[str, TimePeriod] = TimePeriod.MONTHLY,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    n_jobs: Optional[int] = 1,
    use_polars: bool = True,
    **kwargs,
) -> pd.DataFrame:
    """
    Convenience function to calculate factor returns.

    Usage:
        # 计算FF3
        from jh_factors import calculate_factor_returns
        ff3 = calculate_factor_returns('ff3', start_date='2020-01-01', end_date='2024-12-31')

        # 计算所有因子
        all_factors = calculate_factor_returns('all')

    Args:
        factor_type: Factor type ('ff3', 'ff5', 'carhart', 'novy_marx', 'hxz', 'sy', 'dhs', 'betaplus', 'all')
        method: Calculation method ('classic' or 'simple')
        period: Time period ('M' or 'D')
        start_date: Start date
        end_date: End date
        symbols: Stock symbols
        api_key: API密钥
        api_url: API地址
        n_jobs: 并行任务数，默认为1
        use_polars: 是否使用Polars加速（默认True）
        **kwargs: Additional parameters

    Returns:
        DataFrame or Dict of factor returns
    """
    if isinstance(factor_type, str):
        if factor_type.lower() == "all":
            factor_types = FactorType.list_all()
        else:
            factor_types = [FactorType.from_value(factor_type)]
    else:
        factor_types = [factor_type]

    if isinstance(method, str):
        method = CalculationMethod(method)
    if isinstance(period, str):
        period = TimePeriod(period)

    engine = FactorEngine(api_key=api_key, api_url=api_url)

    if len(factor_types) == 1:
        return engine.calculate_factor_returns(
            factor_type=factor_types[0],
            method=method,
            period=period,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            n_jobs=n_jobs,
            verbose=kwargs.get("verbose", True),
            use_polars=use_polars,
        )
    else:
        return engine.calculate_all_factors(
            factor_types=factor_types,
            method=method,
            period=period,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            n_jobs=n_jobs,
            verbose=kwargs.get("verbose", True),
            use_polars=use_polars,
        )


def calculate_exposures(
    stock_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    period: str = "M",
    lookback: Optional[int] = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Convenience function to calculate stock factor exposures.

    Args:
        stock_returns: DataFrame with [symbol, date, return]
        factor_returns: DataFrame with factor returns
        period: Period of factor return ('D' or 'M'), determines the default lookback window to calculate exposures
        lookback: Lookback window for exposures
        **kwargs: Additional parameters

    Returns:
        DataFrame with factor exposures
    """
    return calculate_stock_exposures(
        stock_returns, factor_returns, period, lookback, **kwargs
    )
