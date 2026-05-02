"""
因子有效性验证模块

提供两种验证方法:
1. 截距项验证 (Intercept Validation): OLS回归检验因子收益是否显著
2. Fama-MacBeth两步验证 (Fama-MacBeth Two-Step): 横截面回归检验因子风险溢价是否显著

设计原则:
- 依赖抽象接口，不依赖具体数据源
- 截距项验证接受已计算的因子收益率 DataFrame
- Fama-MacBeth验证接受股票收益率和因子暴露数据
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from ..exposure import StockExposureCalculator
from ..config import DEFAULT_MIN_OBSERVATIONS

# ============================================================================
# Data Classes for Validation Results
# ============================================================================


@dataclass
class FactorTestResult:
    """单个因子检验结果"""

    factor: str
    coefficient: float
    std_error: float
    std_error_nw: float  # Newey-West adjusted std error
    t_statistic: float
    t_statistic_nw: float  # Newey-West t-statistic
    p_value: float
    p_value_nw: float  # Newey-West p-value
    significant: bool  # p < 0.05


@dataclass
class InterceptValidationResult:
    """
    截距项验证结果

    对因子收益率序列进行单样本t检验（或对每个因子进行截距回归）
    检验每个因子的均值是否显著不为零
    """

    results: Dict[str, FactorTestResult] = field(default_factory=dict)
    summary: str = ""

    def is_all_significant(self) -> bool:
        """所有因子都显著"""
        return all(r.significant for r in self.results.values())

    def to_dataframe(self) -> pd.DataFrame:
        """转换为DataFrame便于查看"""
        rows = []
        for factor, res in self.results.items():
            rows.append(
                {
                    "factor": factor,
                    "coefficient": res.coefficient,
                    "std_error": res.std_error,
                    "std_error_nw": res.std_error_nw,
                    "t_statistic": res.t_statistic,
                    "t_statistic_nw": res.t_statistic_nw,
                    "p_value": res.p_value,
                    "p_value_nw": res.p_value_nw,
                    "significant_5pct": res.significant,
                }
            )
        return pd.DataFrame(rows).set_index("factor")


@dataclass
class FMFactorTestResult:
    """Fama-MacBeth单个因子检验结果"""

    factor: str
    # Step 1: lambda_t across months
    lambdas: pd.Series  # monthly factor prices (from cross-sectional reg)
    condition_numbers: (
        pd.Series
    )  # condition numbers for each cross-sectional regression
    # Step 2: time-series test
    mean_lambda: float
    std_lambda: float
    std_lambda_nw: float  # Newey-West adjusted std
    t_statistic: float
    t_statistic_nw: float  # Newey-West t-statistic
    p_value: float
    p_value_nw: float  # Newey-West p-value
    significant: bool


@dataclass
class FamaMacBethValidationResult:
    """
    Fama-MacBeth两步法验证结果

    Step 1: 每月横截面回归 R_i = λ'β + ε 得到 λ_t
    Step 2: λ_t 对时间序列回归，检验 λ 是否显著
    """

    results: Dict[str, FMFactorTestResult] = field(default_factory=dict)
    n_periods: int = 0
    n_stocks: int = 0
    summary: str = ""

    def is_all_significant(self) -> bool:
        """所有因子都显著"""
        return all(r.significant for r in self.results.values())

    def to_dataframe(self) -> pd.DataFrame:
        """转换为DataFrame便于查看"""
        rows = []
        for factor, res in self.results.items():
            rows.append(
                {
                    "factor": factor,
                    "mean_lambda": res.mean_lambda,  # mean_lambda其实就是因子风险溢价的估计值 可以直接用于beta加权（选股）
                    "std_lambda": res.std_lambda,
                    "std_lambda_nw": res.std_lambda_nw,
                    "t_statistic": res.t_statistic,
                    "t_statistic_nw": res.t_statistic_nw,
                    "p_value": res.p_value,
                    "p_value_nw": res.p_value_nw,
                    "significant_5pct": res.significant,
                    "n_periods": len(res.lambdas),
                }
            )
        return pd.DataFrame(rows).set_index("factor")


def _newey_west_intercept_se(
    values: np.ndarray, mean: float, n: int, lag: int
) -> tuple:
    """
    计算截距项检验的Newey-West调整后标准误

    Args:
        values: 时间序列值
        mean: 序列均值
        n: 样本数量
        lag: 滞后阶数

    Returns:
        (se_nw, t_stat_nw, p_value_nw)
    """
    from scipy import stats

    residuals = values - mean

    # gamma_0: 滞后0的方差（乘以n，保持与gamma_j一致）
    gamma_0 = np.sum(residuals**2)

    # Newey-West 方差估计
    q = gamma_0
    for j in range(1, lag + 1):
        gamma_j = np.sum(residuals[j:] * residuals[:-j])
        weight = 1.0 - j / (lag + 1)
        q = q + 2 * weight * gamma_j

    # NW标准误: sqrt(var(mean)) = sqrt(q / n^2)
    se_nw = np.sqrt(q) / n if q >= 0 else np.nan
    t_stat_nw = mean / se_nw if se_nw > 0 and not np.isnan(se_nw) else 0.0
    p_value_nw = 2 * (1 - stats.t.cdf(abs(t_stat_nw), df=n - 1))

    return se_nw, t_stat_nw, p_value_nw


# ============================================================================
# Intercept Validation (截距项验证)
# ============================================================================


def validate_factor_intercept(
    factor_returns: pd.DataFrame,
    alpha: float = 0.05,
    newey_west_lag: Optional[int] = None,
    period: str = "M",
    test_window: Optional[int] = None,
) -> InterceptValidationResult:
    """
    截距项验证：对因子收益率进行截距回归（单样本t检验）

    原理：对因子收益率序列做均值为零的单样本t检验
    H0: 因子收益率均值 = 0
    若拒绝H0，说明因子提供了显著的风险溢价

    也可以理解为对因子收益率对截距项做OLS回归：
    R_t = α + ε,  检验 α 是否显著不为零

    优化：使用Newey-West调整后的标准误修正自相关带来的偏差

    Args:
        factor_returns: 因子收益率 DataFrame
            - index: 日期 (datetime)
            - columns: 因子名称 (如 ['mkt', 'smb', 'hml'])
            - 例如 calculate_factor_returns 的返回值
        alpha: 显著性水平，默认 0.05
        newey_west_lag: Newey-West调整的滞后阶数
            - 若为None，自动根据period推断（M:3, D:21）
        period: 数据周期，用于自动推断NW滞后阶数
        test_window: 检验窗口，截取最近 N 期用于检验，默认为 None（使用所有数据）

    Returns:
        InterceptValidationResult，包含每个因子的检验结果

    Example:
        >>> ff3 = calculate_factor_returns('ff3', period='M')
        >>> result = validate_factor_intercept(ff3)
        >>> print(result.to_dataframe())
        >>> print(result.is_all_significant())
    """
    from scipy import stats

    if newey_west_lag is None:
        newey_west_lag = 3 if period == "M" else 21

    results: Dict[str, FactorTestResult] = {}

    for factor in factor_returns.columns:
        series_full = factor_returns[factor].dropna()

        # 截取最近 N 期用于检验
        if test_window is not None and len(series_full) > test_window:
            series = series_full.iloc[-test_window:]
        else:
            series = series_full

        if len(series) < 3:
            results[factor] = FactorTestResult(
                factor=factor,
                coefficient=np.nan,
                std_error=np.nan,
                std_error_nw=np.nan,
                t_statistic=np.nan,
                t_statistic_nw=np.nan,
                p_value=np.nan,
                p_value_nw=np.nan,
                significant=False,
            )
            continue

        n = len(series)
        # 单样本 t 检验: 检验均值是否显著不为零
        # 单样本 t 检验: 检验均值是否显著不为零
        mean = series.mean()
        std = series.std(ddof=1)
        n = len(series)
        se = std / np.sqrt(n)
        t_stat = mean / se if se > 0 else 0.0
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

        # Newey-West调整后的标准误
        se_nw, t_stat_nw, p_value_nw = _newey_west_intercept_se(
            series.values, mean, n, newey_west_lag
        )

        results[factor] = FactorTestResult(
            factor=factor,
            coefficient=mean,
            std_error=se,
            std_error_nw=se_nw,
            t_statistic=t_stat,
            t_statistic_nw=t_stat_nw,
            p_value=p_value,
            p_value_nw=p_value_nw,
            significant=p_value_nw < alpha,  # 使用NW调整后的p值判断显著性
        )

    # 生成 summary
    sig_count = sum(1 for r in results.values() if r.significant)
    total = len(results)
    summary = (
        f"截距项验证结果 (NW滞后={newey_west_lag}): {sig_count}/{total} 个因子显著 (α={alpha})\n"
        f"  显著因子: {[f for f, r in results.items() if r.significant]}\n"
        f"  不显著因子: {[f for f, r in results.items() if not r.significant]}"
    )

    return InterceptValidationResult(results=results, summary=summary)


# ============================================================================
# Fama-MacBeth Two-Step Validation (Machtheod步验证)
# ============================================================================


class FamaMacBethValidator:
    """
    Fama-MacBeth两步法因子有效性验证器

    Step 1: 每月横截面回归
        使用滚动窗口估计每只股票的 beta（用过去 lookback 期）
        然后对每月 t，进行横截面回归：
        R_i,t = λ_1,t * β_1,i + λ_2,t * β_2,i + ... + ε_i,t
        得到每月的因子价格向量 λ_t

    Step 2: 对 λ_t 在时间序列上检验是否显著
        λ_j = γ_0j + u_j
        检验 γ_0j 是否显著不为零

    Attributes:
        alpha: 显著性水平
        min_periods: 最小期数（少于该值不进行检验）
        lookback: 估计beta用的历史期数（默认: M=36, D=252）
        period: 'M' 或 'D'，用于自动推断lookback默认值
        newey_west_lag: Newey-West调整的滞后阶数（默认: period='M'时为3, 'D'时为21）
        standardize: 是否在截面回归前对因子暴露进行Z-Score标准化
        check_condition_number: 是否监控截面回归的条件数
        condition_threshold: 条件数阈值，超过则记录警告
        test_window: 检验窗口，默认为None，表示使用所有数据
    """

    def __init__(
        self,
        alpha: float = 0.05,
        min_periods: int = 12,
        lookback: Optional[int] = None,
        period: str = "M",
        newey_west_lag: Optional[int] = None,
        standardize: bool = True,
        check_condition_number: bool = True,
        condition_threshold: float = 30.0,
        test_window: Optional[int] = None,
    ):
        self.alpha = alpha
        self.min_periods = min_periods
        if lookback is None:
            lookback = 36 if period == "M" else 252
        self.lookback = lookback
        if newey_west_lag is None:
            newey_west_lag = 3 if period == "M" else 21
        self.newey_west_lag = newey_west_lag
        self.standardize = standardize
        self.check_condition_number = check_condition_number
        self.condition_threshold = condition_threshold
        self.test_window = test_window

    def validate(
        self,
        stock_returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        factor_names: Optional[List[str]] = None,
    ) -> FamaMacBethValidationResult:
        """
        执行Fama-MacBeth两步法验证

        内部自动用滚动窗口估计个股beta，然后做横截面回归。

        Args:
            stock_returns: 股票收益率
                - 必须包含列: ['symbol', 'date', 'return']
                - 通过 get_stock_returns() 获取
            factor_returns: 因子收益率
                - index: 日期 (datetime)
                - columns: 因子名称 (如 ['mkt', 'smb', 'hml'])
                - 通过 calculate_factor_returns 获取
            factor_names: 因子名称列表
                - 若为None，自动从 factor_returns.columns 获取

        Returns:
            FamaMacBethValidationResult，包含每个因子的检验结果

        Example:
            >>> stock_ret = get_stock_returns(...)
            >>> ff3 = calculate_factor_returns('ff3', period='M')
            >>> validator = FamaMacBethValidator(period='M')  # lookback=36
            >>> result = validator.validate(stock_ret, ff3)
            >>> print(result.to_dataframe())
        """
        # 确定因子名称
        if factor_names is None:
            factor_names = list(factor_returns.columns)

        # 数据准备
        stock_returns = stock_returns.copy()
        stock_returns["date"] = pd.to_datetime(stock_returns["date"])
        factor_returns = factor_returns.copy()
        if isinstance(factor_returns.index, pd.DatetimeIndex):
            factor_returns.index = pd.to_datetime(factor_returns.index)

        # 每月估计个股beta（滚动窗口）
        beta_df = self._estimate_rolling_betas(
            stock_returns, factor_returns, factor_names
        )

        # 合并用于截面回归
        merged = stock_returns[["symbol", "date", "return"]].merge(
            beta_df[["symbol", "date"] + factor_names],
            on=["symbol", "date"],
            how="inner",
        )

        if merged.empty:
            raise ValueError("股票收益率和beta数据无法匹配")

        n_stocks = merged["symbol"].nunique()
        n_periods = merged["date"].nunique()

        if n_periods < self.min_periods:
            raise ValueError(
                f"时间 period 数量 ({n_periods}) 少于最小要求 ({self.min_periods})"
            )

        # Step 1: 每月横截面回归，得到 lambda_t
        lambda_by_period = self._step1_cross_sectional(merged, factor_names)

        # Step 2: lambda_t 时间序列检验
        results = self._step2_timeseries_test(lambda_by_period, factor_names)

        summary = (
            f"Fama-MacBeth两步法结果: {sum(1 for r in results.values() if r.significant)}/{len(results)} "
            f"个因子显著 (α={self.alpha}, NW调整滞后={self.newey_west_lag})\n"
            f"  样本: {n_stocks} 只股票, {n_periods} 期, lookback={self.lookback}期\n"
            f"  显著因子: {[f for f, r in results.items() if r.significant]}\n"
            f"  不显著因子: {[f for f, r in results.items() if not r.significant]}"
        )

        return FamaMacBethValidationResult(
            results=results,
            n_periods=n_periods,
            n_stocks=n_stocks,
            summary=summary,
        )

    def _estimate_rolling_betas(
        self,
        stock_returns: pd.DataFrame,
        factor_returns: pd.DataFrame,
        factor_names: List[str],
    ) -> pd.DataFrame:
        """Estimate rolling betas by reusing the exposure calculator."""
        calculator = StockExposureCalculator(
            min_observations=min(DEFAULT_MIN_OBSERVATIONS, self.lookback), n_jobs=1
        )
        beta_df = calculator.calculate_all_exposures(
            stock_returns=stock_returns,
            factor_returns=factor_returns[factor_names],
            rolling=True,
            lookback_months=self.lookback,
            verbose=False,
        )
        if beta_df.empty:
            return beta_df
        cols = ["symbol", "date"] + factor_names
        return beta_df[[c for c in cols if c in beta_df.columns]].copy()

    def _step1_cross_sectional(
        self, data: pd.DataFrame, factor_names: List[str]
    ) -> Dict[str, pd.Series]:
        """
        Step 1: 每月横截面回归

        对每个月，运行：
        R_i = λ_1 * β_1,i + λ_2 * β_2,i + ... + ε_i

        使用OLS计算lambda

        优化点：
        1. Z-Score标准化：对因子暴露进行截面标准化，便于跨因子比较
        2. 条件数监控：检测多重共线性问题

        Returns:
            Dict[因子名 -> pd.Series(每月lambda)]
        """
        import warnings

        lambda_series: Dict[str, List[float]] = {f: [] for f in factor_names}
        condition_numbers: List[float] = []
        period_list: List[pd.Timestamp] = []

        for date, group in data.groupby("date"):
            period_list.append(pd.Timestamp(date))

            y = group["return"].values
            X = group[factor_names].values

            # 跳过数据不足的情况
            if len(y) < len(factor_names) + 2:
                for f in factor_names:
                    lambda_series[f].append(np.nan)
                condition_numbers.append(np.nan)
                continue

            try:
                valid = ~(np.isnan(y) | np.isnan(X).any(axis=1))
                y_valid = y[valid]
                X_valid = X[valid]
                if len(y_valid) < len(factor_names) + 2:
                    raise ValueError("insufficient valid observations")

                # Z-Score标准化（截面）
                if self.standardize:
                    X_mean = X_valid.mean(axis=0)
                    X_std = X_valid.std(axis=0)
                    X_std[X_std < 1e-10] = 1.0  # 避免除零
                    X_valid = (X_valid - X_mean) / X_std

                # 添加截距项
                X_with_const = np.column_stack([np.ones(len(X_valid)), X_valid])

                # 计算条件数（用于检测多重共线性）
                if self.check_condition_number:
                    try:
                        cond_num = np.linalg.cond(X_with_const)
                        condition_numbers.append(cond_num)
                        if cond_num > self.condition_threshold:
                            warnings.warn(
                                f"Date {date}: Condition number {cond_num:.1f} > {self.condition_threshold}, "
                                f"possible collinearity issue"
                            )
                    except Exception:
                        condition_numbers.append(np.nan)
                else:
                    condition_numbers.append(np.nan)

                params, *_ = np.linalg.lstsq(X_with_const, y_valid, rcond=None)
                for i, f in enumerate(factor_names):
                    lambda_series[f].append(float(params[i + 1]))
            except Exception:
                for f in factor_names:
                    lambda_series[f].append(np.nan)
                condition_numbers.append(np.nan)

        # 转换为 Series，index 为日期
        result: Dict[str, pd.Series] = {}
        for f in factor_names:
            result[f] = pd.Series(lambda_series[f], index=period_list).sort_index()

        # 存储条件数序列供后续使用
        self._last_condition_numbers = pd.Series(
            condition_numbers, index=period_list
        ).sort_index()

        return result

    def _step2_timeseries_test(
        self, lambda_by_period: Dict[str, pd.Series], factor_names: List[str]
    ) -> Dict[str, FMFactorTestResult]:
        """
        Step 2: λ_t 时间序列检验

        对每个因子 j:
        λ_j,t = γ_0j + u_j
        检验 γ_0j 是否显著不为零（双侧 t 检验）

        优化点：
        1. Newey-West调整：修正自相关带来的标准误偏差
        2. 报告调整前后的t统计量供对比

        Returns:
            Dict[因子名 -> FMFactorTestResult]
        """

    def _step2_timeseries_test(
        self, lambda_by_period: Dict[str, pd.Series], factor_names: List[str]
    ) -> Dict[str, FMFactorTestResult]:
        """
        Step 2: λ_t 时间序列检验
        ... (docstring remains same) ...
        """
        # print(123) # Remove debug print
        from scipy import stats

        results: Dict[str, FMFactorTestResult] = {}

        for factor in factor_names:
            lambdas_full = lambda_by_period[factor].dropna()

            # <--- 新增：截取最近 N 期用于检验
            if self.test_window is not None and len(lambdas_full) > self.test_window:
                lambdas = lambdas_full.iloc[-self.test_window :]
            else:
                lambdas = lambdas_full

            if len(lambdas) < 3:
                results[factor] = FMFactorTestResult(
                    factor=factor,
                    lambdas=lambdas_full,
                    condition_numbers=getattr(
                        self, "_last_condition_numbers", pd.Series()
                    ),
                    mean_lambda=np.nan,
                    std_lambda=np.nan,
                    std_lambda_nw=np.nan,
                    t_statistic=np.nan,
                    t_statistic_nw=np.nan,
                    p_value=np.nan,
                    p_value_nw=np.nan,
                    significant=False,
                )
                continue

            mean_lambda = lambdas.mean()
            std_lambda = lambdas.std(ddof=1)
            n = len(lambdas)

            # 原始标准误
            se = std_lambda / np.sqrt(n) if n > 0 else np.nan
            t_stat = mean_lambda / se if se > 0 and not np.isnan(se) else 0.0
            p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

            # Newey-West调整后的标准误
            effective_lag = min(self.newey_west_lag, n - 1) if n > 1 else 0

            std_lambda_nw, t_stat_nw, p_value_nw = self._newey_west_se(
                lambdas.values, mean_lambda, n, effective_lag
            )

            results[factor] = FMFactorTestResult(
                factor=factor,
                lambdas=lambdas,
                condition_numbers=getattr(self, "_last_condition_numbers", pd.Series()),
                mean_lambda=mean_lambda,
                std_lambda=std_lambda,
                std_lambda_nw=std_lambda_nw,
                t_statistic=t_stat,
                t_statistic_nw=t_stat_nw,
                p_value=p_value,
                p_value_nw=p_value_nw,
                significant=p_value_nw < self.alpha,
            )

        return results

    def _newey_west_se(
        self, lambdas: np.ndarray, mean_lambda: float, n: int, lag: int
    ) -> tuple:
        """
        计算Newey-West调整后的标准误

        Newey-West (1987) 调整用于修正一阶自相关带来的标准误低估问题

        Args:
            lambdas: lambda时间序列
            mean_lambda: lambda均值
            n: 样本数量
            lag: 滞后阶数

        Returns:
            (std_lambda_nw, t_stat_nw, p_value_nw)
        """
        from scipy import stats

        # 计算残差
        residuals = lambdas - mean_lambda

        # gamma_0: 滞后0的方差
        gamma_0 = np.sum(residuals**2)

        # Newey-West 方差估计
        q = gamma_0
        for j in range(1, lag + 1):
            gamma_j = np.sum(residuals[j:] * residuals[:-j])
            weight = 1.0 - j / (lag + 1)
            q = q + 2 * weight * gamma_j

        # NW标准误
        std_lambda_nw = np.sqrt(q) / n if q >= 0 else np.nan
        t_stat_nw = (
            mean_lambda / std_lambda_nw
            if std_lambda_nw > 0 and not np.isnan(std_lambda_nw)
            else 0.0
        )
        p_value_nw = 2 * (1 - stats.t.cdf(abs(t_stat_nw), df=n - 1))

        return std_lambda_nw, t_stat_nw, p_value_nw


# ============================================================================
# Convenience function
# ============================================================================


def validate_factor(
    factor_returns: pd.DataFrame,
    stock_returns: Optional[pd.DataFrame] = None,
    factor_exposures: Optional[pd.DataFrame] = None,
    method: str = "intercept",
    alpha: float = 0.05,
    newey_west_lag: Optional[int] = None,
    period: str = "M",
    test_window: Optional[int] = None,
) -> InterceptValidationResult | FamaMacBethValidationResult:
    """
    因子有效性验证的便捷入口

    Args:
        factor_returns: 因子收益率 DataFrame
        stock_returns: 股票收益率（FM验证需要）
        factor_exposures: 因子暴露（FM验证需要）
        method: 'intercept' 或 'fama_macbeth'
        alpha: 显著性水平
        newey_west_lag: Newey-West调整的滞后阶数（默认根据period推断）
        period: 数据周期，用于推断NW滞后阶数（M:3, D:21）
        test_window: 检验窗口，截取最近 N 期用于检验，默认为 None（使用所有数据）

    Returns:
        InterceptValidationResult 或 FamaMacBethValidationResult
    """
    if method == "intercept":
        return validate_factor_intercept(
            factor_returns, alpha, newey_west_lag, period, test_window
        )
    elif method == "fama_macbeth":
        if stock_returns is None or stock_returns.empty:
            raise ValueError("stock_returns is required for fama_macbeth validation")
        validator = FamaMacBethValidator(alpha=alpha, test_window=test_window)
        if factor_exposures is not None and not factor_exposures.empty:
            factor_names = [
                c for c in factor_returns.columns if c in factor_exposures.columns
            ]
            merged = stock_returns[["symbol", "date", "return"]].copy()
            merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
            exposures = factor_exposures.copy()
            exposures["date"] = pd.to_datetime(exposures["date"]).dt.strftime(
                "%Y-%m-%d"
            )
            merged = merged.merge(
                exposures[["symbol", "date"] + factor_names],
                on=["symbol", "date"],
                how="inner",
            )
            if merged.empty:
                raise ValueError("stock_returns and factor_exposures cannot be aligned")
            lambda_by_period = validator._step1_cross_sectional(merged, factor_names)
            results = validator._step2_timeseries_test(lambda_by_period, factor_names)
            return FamaMacBethValidationResult(
                results=results,
                n_periods=merged["date"].nunique(),
                n_stocks=merged["symbol"].nunique(),
                summary=(
                    f"Fama-MacBeth result (NW lag={validator.newey_west_lag}): "
                    f"{sum(1 for r in results.values() if r.significant)}/{len(results)} significant (alpha={alpha})\n"
                    f"  Sample: {merged['symbol'].nunique()} stocks, {merged['date'].nunique()} periods"
                ),
            )
        return validator.validate(stock_returns, factor_returns)
    else:
        raise ValueError(f"Unknown method: {method}")
