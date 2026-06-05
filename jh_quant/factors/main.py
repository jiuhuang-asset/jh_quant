"""
Factor calculation entry points.

The factor package works with canonical DataFrame schemas only. Data fetching and
source-specific column conversion should happen before calling these functions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Dict, List, Optional, Union

import pandas as pd

from jh_quant.schemas.factors import (
    normalize_factor_fundamentals,
    normalize_factor_market_cap_frame,
    normalize_factor_market_return_frame,
    normalize_factor_risk_free_rate_frame,
    normalize_factor_returns_frame,
    normalize_factor_stock_returns_frame,
)

from .config import CalculationMethod, FACTOR_CONFIGS, FactorType, TimePeriod
from .exposure import StockExposureCalculator, calculate_stock_exposures
from .factors.general import GeneralFactorCalculator


def _coerce_factor_types(
    factor_type: Union[str, FactorType],
) -> list[FactorType]:
    if isinstance(factor_type, str):
        if factor_type.lower() == "all":
            return FactorType.list_all()
        return [FactorType.from_value(factor_type)]
    return [factor_type]


def _coerce_method(method: Union[str, CalculationMethod]) -> CalculationMethod:
    return CalculationMethod(method) if isinstance(method, str) else method


def _coerce_period(period: Union[str, TimePeriod]) -> TimePeriod:
    return TimePeriod(period) if isinstance(period, str) else period


class FactorEngine:
    """Main factor calculation engine for normalized factor input frames."""

    def calculate_factor_returns(
        self,
        factor_type: FactorType = FactorType.FF3,
        stock_returns: Optional[pd.DataFrame] = None,
        market_cap: Optional[pd.DataFrame] = None,
        fundamentals: Optional[Mapping[str, pd.DataFrame]] = None,
        market_return: Optional[pd.DataFrame] = None,
        risk_free_rate: Optional[pd.DataFrame] = None,
        method: CalculationMethod = CalculationMethod.SIMPLE,
        period: TimePeriod = TimePeriod.MONTHLY,
        n_jobs: Optional[int] = None,
        verbose: bool = True,
        use_polars: bool = True,
    ) -> pd.DataFrame:
        """
        Calculate factor returns from canonical input frames.

        Required schemas:
        - stock_returns: [symbol, date, return]
        - market_cap: [symbol, date, mkt_cap]
        - fundamentals: {field_name: DataFrame with symbol/date/field_name}
        - market_return for CAPM: [date, mkt_excess]
        """
        if verbose:
            print(f"Calculating {factor_type.value} factors...")
            print(f"  Method: {method.value}")
            print(f"  Period: {period.value}")

        calculator = GeneralFactorCalculator(
            factor_type=factor_type,
            method=method,
            period=period,
            n_jobs=n_jobs,
            use_polars=use_polars,
        )

        if factor_type == FactorType.CAPM:
            if market_return is None:
                raise ValueError("market_return is required for CAPM factors")
            normalized_market_return = normalize_factor_market_return_frame(
                market_return
            )
            factor_returns = calculator.calculate(
                stock_returns=pd.DataFrame(),
                market_cap=normalized_market_return,
                fundamentals=None,
                risk_free_rate=None,
            )
            return normalize_factor_returns_frame(factor_returns)

        if stock_returns is None:
            raise ValueError("stock_returns is required")
        if market_cap is None:
            raise ValueError("market_cap is required")

        normalized_stock_returns = normalize_factor_stock_returns_frame(stock_returns)
        normalized_market_cap = normalize_factor_market_cap_frame(market_cap)
        normalized_fundamentals = normalize_factor_fundamentals(fundamentals)
        normalized_risk_free_rate = normalize_factor_risk_free_rate_frame(
            risk_free_rate
        )

        missing = self._missing_required_fields(
            factor_type,
            normalized_stock_returns,
            normalized_market_cap,
            normalized_fundamentals,
        )
        if missing:
            raise ValueError(
                f"{factor_type.value} factors require missing fields: "
                + ", ".join(missing)
            )

        factor_returns = calculator.calculate(
            stock_returns=normalized_stock_returns,
            market_cap=normalized_market_cap,
            fundamentals=normalized_fundamentals,
            risk_free_rate=normalized_risk_free_rate,
        )

        factor_returns = normalize_factor_returns_frame(factor_returns)

        if verbose:
            period_label = "days" if period == TimePeriod.DAILY else "months"
            print(f"Calculated {len(factor_returns)} {period_label} of factor returns")

        return factor_returns

    def calculate_all_factors(
        self,
        factor_types: Optional[List[FactorType]] = None,
        stock_returns: Optional[pd.DataFrame] = None,
        market_cap: Optional[pd.DataFrame] = None,
        fundamentals: Optional[Mapping[str, pd.DataFrame]] = None,
        market_return: Optional[pd.DataFrame] = None,
        risk_free_rate: Optional[pd.DataFrame] = None,
        method: CalculationMethod = CalculationMethod.SIMPLE,
        period: TimePeriod = TimePeriod.MONTHLY,
        n_jobs: Optional[int] = None,
        verbose: bool = True,
        use_polars: bool = True,
    ) -> Dict[FactorType, pd.DataFrame]:
        """Calculate multiple factor return sets from canonical input frames."""
        if factor_types is None:
            factor_types = FactorType.list_all()

        results: Dict[FactorType, pd.DataFrame] = {}
        for factor_type in factor_types:
            try:
                results[factor_type] = self.calculate_factor_returns(
                    factor_type=factor_type,
                    stock_returns=stock_returns,
                    market_cap=market_cap,
                    fundamentals=fundamentals,
                    market_return=market_return,
                    risk_free_rate=risk_free_rate,
                    method=method,
                    period=period,
                    n_jobs=n_jobs,
                    verbose=verbose,
                    use_polars=use_polars,
                )
            except Exception as exc:
                if verbose:
                    print(f"Failed to calculate {factor_type.value}: {exc}")

        return results

    def calculate_stock_exposures(
        self,
        stock_returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        n_jobs: int = 4,
        verbose: bool = True,
    ) -> pd.DataFrame:
        """Calculate stock factor exposures from canonical input frames."""
        if verbose:
            print("Calculating stock factor exposures...")

        stock_returns = normalize_factor_stock_returns_frame(stock_returns)
        factor_returns = normalize_factor_returns_frame(factor_returns)

        calculator = StockExposureCalculator(n_jobs=n_jobs)
        return calculator.calculate_all_exposures(
            stock_returns, factor_returns, verbose=verbose
        )

    @staticmethod
    def _missing_required_fields(
        factor_type: FactorType,
        stock_returns: pd.DataFrame,
        market_cap: pd.DataFrame,
        fundamentals: Mapping[str, pd.DataFrame],
    ) -> list[str]:
        missing = []
        available = set(stock_returns.columns) | set(market_cap.columns)
        available.update(fundamentals.keys())
        for field in FACTOR_CONFIGS[factor_type]["required_data"]:
            if field == "mkt_cap":
                continue
            if field not in available:
                missing.append(field)
        return missing


def calculate_factor_returns(
    factor_type: Union[str, FactorType] = FactorType.FF3,
    stock_returns: Optional[pd.DataFrame] = None,
    market_cap: Optional[pd.DataFrame] = None,
    fundamentals: Optional[Mapping[str, pd.DataFrame]] = None,
    market_return: Optional[pd.DataFrame] = None,
    risk_free_rate: Optional[pd.DataFrame] = None,
    method: Union[str, CalculationMethod] = CalculationMethod.SIMPLE,
    period: Union[str, TimePeriod] = TimePeriod.MONTHLY,
    n_jobs: Optional[int] = 1,
    use_polars: bool = True,
    verbose: bool = True,
    **kwargs,
) -> Union[pd.DataFrame, Dict[FactorType, pd.DataFrame]]:
    """Convenience function to calculate factor returns from canonical frames."""
    if kwargs:
        unsupported = ", ".join(sorted(kwargs))
        raise TypeError(
            "calculate_factor_returns no longer fetches source data. "
            f"Prepare schema-compatible DataFrames before calling it. "
            f"Unsupported arguments: {unsupported}"
        )

    factor_types = _coerce_factor_types(factor_type)
    method = _coerce_method(method)
    period = _coerce_period(period)
    engine = FactorEngine()

    if len(factor_types) == 1:
        return engine.calculate_factor_returns(
            factor_type=factor_types[0],
            stock_returns=stock_returns,
            market_cap=market_cap,
            fundamentals=fundamentals,
            market_return=market_return,
            risk_free_rate=risk_free_rate,
            method=method,
            period=period,
            n_jobs=n_jobs,
            verbose=verbose,
            use_polars=use_polars,
        )

    return engine.calculate_all_factors(
        factor_types=factor_types,
        stock_returns=stock_returns,
        market_cap=market_cap,
        fundamentals=fundamentals,
        market_return=market_return,
        risk_free_rate=risk_free_rate,
        method=method,
        period=period,
        n_jobs=n_jobs,
        verbose=verbose,
        use_polars=use_polars,
    )


def calculate_exposures(
    stock_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    period: str = "M",
    lookback: Optional[int] = None,
    **kwargs,
) -> pd.DataFrame:
    """Convenience function to calculate stock factor exposures."""
    stock_returns = normalize_factor_stock_returns_frame(stock_returns)
    factor_returns = normalize_factor_returns_frame(factor_returns)
    return calculate_stock_exposures(
        stock_returns, factor_returns, period, lookback, **kwargs
    )
