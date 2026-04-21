from typing import Optional, List
from dataclasses import dataclass
from jh_quant.data import JHData, DataTypes
from jh_quant.factors import FactorType
from jh_quant.factors import validate_factor
from jh_quant.factors import FACTOR_CONFIGS
import numpy as np
from rich.console import Console

console = Console()


@dataclass
class FactorSelectionResult:
    """因子选股结果"""
    top_stocks: List[str]  # 评分最高的股票代码列表
    bottom_stocks: List[str]  # 评分最低的股票代码列表
    weights: dict  # 因子权重 dict[factor_name, weight]
    fm_result: object  # FamaMacBeth验证结果
    top_scores: List[float]  # top_stocks对应的评分
    bottom_scores: List[float]  # bottom_stocks对应的评分
 

def get_data_type_by_factor(ft: FactorType, period: str = "M", type: str = "returns") -> DataTypes:
    """根据FactorType获取对应的DataType"""
    if period == "M":
        period = "monthly"
    elif period == "D":
        period = "daily"
    ft_value = ft.value
    if ft == FactorType.NOVY_MARX:
        ft_value = "nm"
    if ft == FactorType.HOU_XUE_ZHANG:
        ft_value = "hxz"
    return DataTypes(f"jh_factor_{ft_value}_{type}_{period}")


class JhSelector:
    def __init__(self, jh_data: JHData):
        self.jh_data = jh_data

    def select_by_factor(
        self,
        factor: FactorType,
        start: str,
        end: str,
        top_n: int = 100,
        bottom_n: int = 100,
        factor_alpha: float = 0.10,
        default_weight: float = 0.1,
        period: str = "M",
        insignificant_weight_ratio: float = 0.5,  
        missing_data_threshold: float = 0.10,      
        test_window: Optional[int] = 36,  # 用于FM验证的滚动窗口长度
        verbose: bool = True,
    ) -> FactorSelectionResult:
        """根据因子暴露评分选股，使用Fama-MacBeth回归系数作为权重

        原理：S_i = sum(w_j * beta_{i,j})
             权重归一化：sum(|w_j|) = 1

        显著因子：使用FM回归得到的Mean_Lambda作为权重
        不显著因子：使用 default_weight * avg(|mean_lambda|) * ratio 作为权重

        Args:
            factor: 因子类型 (FactorType枚举)
            start: 股票数据开始日期，格式"2015-01-01"
            end: 股票数据结束日期，格式"2026-01-01"
            top_n: 选取评分最高的股票数量
            bottom_n: 选取评分最低的股票数量
            factor_alpha: 显著性水平，默认0.10
            default_weight: 不显著因子使用的基准权重系数
            period: 数据周期，默认"M"（月度）
            insignificant_weight_ratio: 不显著因子的权重缩放比例 (0-1), <1.0 表示降低不显著因子的影响力
            missing_data_threshold: 当有效股票比例低于此值时发出警告 (默认 10%)
            test_window: FM验证的滚动窗口长度，默认None


        Returns:
            FactorSelectionResult: 包含top_stocks(List[str]), bottom_stocks(List[str]), weights, fm_result
                'top_stocks': DataFrame with top_n stocks and scores,
                'bottom_stocks': DataFrame with bottom_n stocks and scores,
                'weights': dict of factor -> normalized weight used,
                'fm_result': FamaMacBethValidationResult
            }
        """
        factor_names = FACTOR_CONFIGS[factor]["factors"]

        # 获取对应的DataType
        exposure_dtype = get_data_type_by_factor(factor, period, "exposure")
        returns_dtype = get_data_type_by_factor(factor, period, "returns")

        factor_returns = self.jh_data.get_data(returns_dtype, start=start, end=end).set_index('date')
        factor_exposures = self.jh_data.get_data(exposure_dtype, start=start, end=end)
        
        stock_price_dtype = DataTypes.AK_STOCK_ZH_A_HIST_QFQ_MON if period == "M" else DataTypes.AK_STOCK_ZH_A_HIST_QFQ
        stock_price_monthly = self.jh_data.get_data(
            stock_price_dtype,
            start=start,
            end=end
        )

        from .metrics import calculate_returns
        stock_returns = calculate_returns(stock_price_monthly)

        # Fama-MacBeth验证获取Mean_Lambda
        if test_window is None:
            test_window = 36 if period == "M" else 252
        fm_result = validate_factor(
            factor_returns=factor_returns,
            stock_returns=stock_returns,
            factor_exposures=factor_exposures,
            method="fama_macbeth",
            alpha=factor_alpha,
            period=period,
            test_window=test_window
        )

        # --- 构建权重逻辑 ---
        raw_weights = {}
        significant_positive = []  # 显著正向因子
        significant_negative = []  # 显著负向因子（异象）
        insignificant_factors = []
        significant_lambdas = []  # 用于计算不显著因子的默认权重基准

        for fname in factor_names:
            if fname not in fm_result.results:
                insignificant_factors.append(fname)
                # 暂时标记，后续统一处理
                raw_weights[fname] = None 
                continue

            fm_test = fm_result.results[fname]
            if fm_test.significant:
                # 显著因子：直接使用 mean_lambda，保留正负方向
                raw_weights[fname] = fm_test.mean_lambda
                significant_lambdas.append(abs(fm_test.mean_lambda))

                if fm_test.mean_lambda > 0:
                    significant_positive.append(fname)
                else:
                    significant_negative.append(fname)
                    # 使用rich的警告提醒负向因子（异象）
                    console.print(
                        f"[yellow]⚠ 异象警告：因子 {fname} 效应为负向 "
                        f"(mean_lambda={fm_test.mean_lambda:.4f}, p={fm_test.p_value_nw:.4f})[/yellow]"
                    )
            else:
                insignificant_factors.append(fname)
                raw_weights[fname] = None # 标记为待处理

        # 计算显著因子的平均绝对 Lambda，作为基准量级
        if significant_lambdas:
            avg_sig_lambda = sum(significant_lambdas) / len(significant_lambdas)
        else:
            # 如果没有显著因子， fallback 到 default_weight
            avg_sig_lambda = default_weight 

        # 处理不显著因子和缺失结果的因子
        for fname in insignificant_factors:
            # 逻辑：基准量级 * 初始系数 * 缩放比例
            # 这样既保留了量级参考，又通过 ratio < 1.0 降低了噪声因子的影响
            base_w = avg_sig_lambda * insignificant_weight_ratio
            raw_weights[fname] = base_w

        # 权重归一化：先取绝对值，确保 sum(|weights|) = 1
        # 注意：负向因子(如异象)取绝对值后，评分时方向由因子暴露值决定
        raw_weights_abs = {f: abs(w) for f, w in raw_weights.items()}
        total_abs_weight = sum(raw_weights_abs.values())

        if total_abs_weight == 0:
            raise ValueError("所有因子权重均为0，无法计算评分")

        weights = {f: w / total_abs_weight for f, w in raw_weights.items()}

        # --- 打印日志 ---
        if verbose:
            print(f"\n{'='*60}")
            print(f"因子选股 - {factor.name} ({FACTOR_CONFIGS[factor]['name']})")
            print(f"{'='*60}")
            print(f"显著性水平: {factor_alpha}")
            console.print(f"显著正向因子 ({len(significant_positive)}): [green]{significant_positive}[/green]")
            console.print(f"显著负向因子/异象 ({len(significant_negative)}): [yellow]{significant_negative}[/yellow]")
            print(f"不显著因子 ({len(insignificant_factors)}): {insignificant_factors}")
            print(f"不显著因子权重缩放比例: {insignificant_weight_ratio}")
            # console.print(f"归一化权重: {weights}") # 如果因子太多，打印可能会乱，可选开启
            print(f"{'='*60}\n")

        # --- 计算评分 ---
        exposure_cols = ['symbol', 'date'] + factor_names
        
        # 防御性编程：检查列是否存在
        missing_cols = [col for col in exposure_cols if col not in factor_exposures.columns]
        if missing_cols:
            raise ValueError(f"因子暴露数据中缺少列: {missing_cols}")

        exposures = factor_exposures[exposure_cols].copy()

        # 只保留最新一期（最近）的暴露数据
        latest_date = exposures['date'].max()
        exposures_latest = exposures[exposures['date'] == latest_date].copy()

        # 缺失值监控
        initial_count = len(exposures_latest)
        exposures_clean = exposures_latest.dropna(subset=factor_names)
        final_count = len(exposures_clean)
        
        if initial_count > 0:
            missing_ratio = 1 - (final_count / initial_count)
            if missing_ratio > missing_data_threshold:
                console.print(
                    f"[red]⚠ 数据缺失警告：最新日期 {latest_date} 有 {missing_ratio:.1%} 的股票因因子缺失被剔除 "
                    f"(剩余 {final_count}/{initial_count})[/red]"
                )

        if exposures_clean.empty:
            raise ValueError("没有有效的因子暴露数据")

        # 每只股票只保留一行（最新一期），防止重复
        exposures_clean = exposures_clean.drop_duplicates(subset=['symbol'], keep='last')

        # 计算 Score: S_i = sum(|w_j| * sign(w_j) * E_ij)
        # 对异象(负权重因子)，需要取绝对值后根据原始方向调整
        score_df = exposures_clean[['symbol']].copy()

        score_values = np.zeros(len(exposures_clean))
        for f in factor_names:
            w = weights[f]
            # 对负权重因子(异象)，取绝对值乘以原始符号方向
            effective_weight = abs(w) if w >= 0 else -abs(w)
            score_values += effective_weight * exposures_clean[f].values

        score_df['score'] = score_values

        # 排序并选取 Top/Bottom
        score_df = score_df.sort_values('score', ascending=False)
        top_stocks = score_df.head(top_n).copy()
        bottom_stocks = score_df.tail(bottom_n).copy()

        return FactorSelectionResult(
            top_stocks=top_stocks['symbol'].tolist(),
            bottom_stocks=bottom_stocks['symbol'].tolist(),
            weights=weights,
            fm_result=fm_result,
            top_scores=top_stocks['score'].tolist(),
            bottom_scores=bottom_stocks['score'].tolist(),
        )