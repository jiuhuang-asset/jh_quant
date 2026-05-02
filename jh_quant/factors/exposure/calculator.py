"""
Stock Factor Exposure Calculator

Calculates individual stock factor exposures (factor betas)
using regression against factor returns.
"""

from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from ..config import DEFAULT_MIN_OBSERVATIONS, DEFAULT_N_JOBS


class StockExposureCalculator:
    """Calculator for stock factor exposures (betas)."""

    def __init__(
        self,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
        n_jobs: int = DEFAULT_N_JOBS,
    ):
        self.min_observations = min_observations
        self.n_jobs = n_jobs

    def _prepare_factor_matrix(
        self, factor_returns: pd.DataFrame
    ) -> tuple[pd.DataFrame, List[str]]:
        """Normalize factor-return input and keep factor columns only."""
        factor_returns = factor_returns.copy()
        if "date" in factor_returns.columns:
            factor_returns["date"] = pd.to_datetime(factor_returns["date"])
            factor_returns = factor_returns.set_index("date")
        if isinstance(factor_returns.index, pd.DatetimeIndex):
            factor_returns.index = pd.to_datetime(factor_returns.index)
        factor_returns = factor_returns.sort_index()
        factor_cols = [c for c in factor_returns.columns if c != "date"]
        return factor_returns[factor_cols], factor_cols

    def _nan_exposure_result(self, factor_columns: List[str]) -> Dict[str, float]:
        result = {factor: np.nan for factor in factor_columns}
        result["alpha"] = np.nan
        return result

    def _fit_exposure_from_arrays(
        self, y: np.ndarray, X: np.ndarray, factor_columns: List[str]
    ) -> Dict[str, float]:
        """Fit OLS via numpy.linalg.lstsq to reduce overhead."""
        if len(y) < self.min_observations:
            return self._nan_exposure_result(factor_columns)

        valid = ~(np.isnan(y) | np.isnan(X).any(axis=1))
        if not np.any(valid):
            return self._nan_exposure_result(factor_columns)

        y_valid = y[valid]
        X_valid = X[valid]
        if len(y_valid) < self.min_observations:
            return self._nan_exposure_result(factor_columns)

        X_with_const = np.column_stack([np.ones(len(X_valid)), X_valid])
        try:
            params, *_ = np.linalg.lstsq(X_with_const, y_valid, rcond=None)
        except np.linalg.LinAlgError:
            return self._nan_exposure_result(factor_columns)

        exposures = {"alpha": float(params[0])}
        for i, factor in enumerate(factor_columns):
            exposures[factor] = float(params[i + 1])
        return exposures

    def calculate_single_stock_exposure(
        self, stock_returns: pd.Series, factor_returns: pd.DataFrame
    ) -> Dict[str, float]:
        """Calculate pooled OLS exposure for a single stock."""
        factor_matrix, factor_cols = self._prepare_factor_matrix(factor_returns)
        common_index = stock_returns.index.intersection(factor_matrix.index)
        if len(common_index) < self.min_observations:
            return self._nan_exposure_result(factor_cols)

        y = stock_returns.loc[common_index].to_numpy(dtype=float, copy=False)
        X = factor_matrix.loc[common_index].to_numpy(dtype=float, copy=False)
        return self._fit_exposure_from_arrays(y, X, factor_cols)

    def _calculate_rolling_for_symbol(
        self,
        symbol: str,
        stock_data: pd.DataFrame,
        factor_matrix: pd.DataFrame,
        factor_cols: List[str],
        lookback: int,
    ) -> List[Dict]:
        """Calculate rolling exposures for a single symbol."""
        # Convert dates to YYYY-mm-dd string for consistent merging
        stock_dates = stock_data["date"].dt.strftime("%Y-%m-%d")
        factor_dates = factor_matrix.index.strftime("%Y-%m-%d")
        merged = (
            pd.DataFrame({"date": stock_dates, "return": stock_data["return"].values})
            .merge(
                pd.DataFrame({"date": factor_dates}).assign(
                    **{col: factor_matrix[col].values for col in factor_cols}
                ),
                on="date",
                how="inner",
            )
            .sort_values("date")
        )

        if len(merged) < self.min_observations:
            return []

        y_all = merged["return"].to_numpy(dtype=float, copy=False)
        X_all = merged[factor_cols].to_numpy(dtype=float, copy=False)
        dates = merged["date"].tolist()
        results: List[Dict] = []

        for end_idx, dt in enumerate(dates):
            start_idx = max(0, end_idx - lookback + 1)
            exposure = self._fit_exposure_from_arrays(
                y_all[start_idx : end_idx + 1],
                X_all[start_idx : end_idx + 1],
                factor_cols,
            )
            if np.isnan(exposure["alpha"]):
                continue
            row = {"symbol": symbol, "date": dt}
            row.update(exposure)
            results.append(row)

        return results

    def calculate_rolling_exposures(
        self,
        stock_returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        lookback_months: int = 24,
        symbols: Optional[List[str]] = None,
        verbose: bool = True,
    ) -> pd.DataFrame:
        """Calculate rolling factor exposures for all requested symbols."""
        if stock_returns is None or stock_returns.empty:
            raise ValueError("stock_returns is required")

        if symbols is None:
            symbols = stock_returns["symbol"].unique().tolist()

        stock_returns = stock_returns.copy()
        stock_returns["date"] = pd.to_datetime(stock_returns["date"])
        factor_matrix, factor_cols = self._prepare_factor_matrix(factor_returns)

        if verbose:
            print(
                f"Calculating rolling betas for {len(symbols)} stocks, lookback={lookback_months} periods..."
            )

        stock_groups = {
            symbol: grp.sort_values("date").reset_index(drop=True)
            for symbol, grp in stock_returns[
                stock_returns["symbol"].isin(symbols)
            ].groupby("symbol", sort=False)
        }

        tasks = [
            (symbol, stock_groups[symbol], factor_matrix, factor_cols, lookback_months)
            for symbol in symbols
            if symbol in stock_groups
        ]
        if self.n_jobs == 1:
            results = [self._calculate_rolling_for_symbol(*task) for task in tasks]
        else:
            with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
                results = list(
                    executor.map(
                        lambda args: self._calculate_rolling_for_symbol(*args), tasks
                    )
                )

        all_betas = [row for rows in results for row in rows]
        if not all_betas:
            return pd.DataFrame()
        return pd.DataFrame(all_betas)

    def calculate_all_exposures(
        self,
        stock_returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        symbols: Optional[List[str]] = None,
        verbose: bool = True,
        rolling: bool = True,
        lookback_months: int = 24,
    ) -> pd.DataFrame:
        """Calculate factor exposures for all stocks."""
        if stock_returns is None or stock_returns.empty:
            raise ValueError("stock_returns is required")

        if symbols is None:
            symbols = stock_returns["symbol"].unique().tolist()

        stock_returns = stock_returns.copy()
        stock_returns["date"] = pd.to_datetime(stock_returns["date"])

        if rolling:
            return self.calculate_rolling_exposures(
                stock_returns,
                factor_returns,
                lookback_months=lookback_months,
                symbols=symbols,
                verbose=verbose,
            )

        if verbose:
            print(f"Calculating factor exposures for {len(symbols)} stocks...")

        factor_matrix, factor_cols = self._prepare_factor_matrix(factor_returns)
        stock_groups = {
            symbol: grp.sort_values("date").reset_index(drop=True)
            for symbol, grp in stock_returns[
                stock_returns["symbol"].isin(symbols)
            ].groupby("symbol", sort=False)
        }

        tasks = [
            (symbol, stock_groups[symbol], factor_matrix, factor_cols, None)
            for symbol in symbols
            if symbol in stock_groups
        ]
        if self.n_jobs == 1:
            results = [self._calculate_for_symbol(*task) for task in tasks]
        else:
            with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
                results = list(
                    executor.map(lambda args: self._calculate_for_symbol(*args), tasks)
                )

        exposures = [result for result in results if result is not None]
        if not exposures:
            return pd.DataFrame()
        return pd.DataFrame(exposures)

    def _calculate_for_symbol(
        self,
        symbol: str,
        stock_data: pd.DataFrame,
        factor_returns: pd.DataFrame,
        factor_cols: List[str],
        lookback: Optional[int] = None,
    ) -> Optional[Dict]:
        """Calculate pooled exposure for one symbol."""
        # Convert dates to YYYY-mm-dd string for consistent merging
        stock_dates = stock_data["date"].dt.strftime("%Y-%m-%d")
        factor_dates = factor_returns.index.strftime("%Y-%m-%d")
        merged = (
            pd.DataFrame({"date": stock_dates, "return": stock_data["return"].values})
            .merge(
                pd.DataFrame({"date": factor_dates}).assign(
                    **{col: factor_returns[col].values for col in factor_cols}
                ),
                on="date",
                how="inner",
            )
            .sort_values("date")
        )

        if len(merged) < self.min_observations:
            return None

        if lookback is not None:
            merged = merged.iloc[-lookback:]

        exposure = self._fit_exposure_from_arrays(
            merged["return"].to_numpy(dtype=float, copy=False),
            merged[factor_cols].to_numpy(dtype=float, copy=False),
            factor_cols,
        )
        if np.isnan(exposure["alpha"]):
            return None

        row = {"symbol": symbol, "date": merged["date"].iloc[-1]}
        row.update(exposure)
        return row


def calculate_stock_exposures(
    stock_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    period: str = "M",
    lookback: Optional[int] = None,
    rolling: bool = True,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    n_jobs: int = DEFAULT_N_JOBS,
) -> pd.DataFrame:
    """Convenience function to calculate stock factor exposures."""
    if lookback is None:
        lookback = 36 if period == "M" else 252

    calculator = StockExposureCalculator(
        min_observations=min_observations, n_jobs=n_jobs
    )

    return calculator.calculate_all_exposures(
        stock_returns, factor_returns, rolling=rolling, lookback_months=lookback
    )
