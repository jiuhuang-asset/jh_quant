"""
通用因子计算器

支持所有因子模型的计算：
- FF3: Fama-French三因子
- FF5: Fama-French五因子
- CARHART: Carhart四因子
- NOVY_MARX: Novy-Marx四因子
- HOU_XUE_ZHANG: Hou-Xue-Zhang四因子
- DHS: Daniel-Hirshleifer-Sun三因子

"""
from typing import Optional, Dict, List, Tuple, Union
import pandas as pd
import numpy as np
import polars as pl
from joblib import Parallel, delayed
from ..config import FactorType, CalculationMethod, TimePeriod, FACTOR_CONFIGS, CLASSIC_CONFIGS,DEFAULT_N_JOBS


FACTOR_SORT_VAR_MAP = {
    'smb': 'mkt_cap',
    'me': 'mkt_cap',
    'hml': 'bm',
    # FF5: RMW uses Operating Profitability (op), CMA uses asset_growth
    'rmw': 'op',
    'roe': 'roe',
    'cma': 'asset_growth',
    # HOU_XUE_ZHANG: ia uses asset_growth, roe is separate
    'ia': 'asset_growth',
    'umd': 'momentum',
    'idio_vol': 'ivol',
    'ivol': 'ivol',
    # CH3 中国三因子
    'vmg': 'bm',
    # SY4 Stambaugh-Yuan 四因子
    'mgmt': 'mgmt',
    'perf': 'perf',
    # REVERSAL 短期反转
    'rev': 'rev',
    # NOVY_MARX 四因子
    'hml_adj': 'bm',
    'gp_a': 'gp_a',
    # DHS 三因子
    'pead': 'pead',
    'fin': 'fin',
    # CARHART 四因子
    'mom': 'momentum',
}


def _get_factor_sort_var(factor_name: str, sort_vars: List[str]) -> Optional[str]:
    """Return the sorting variable that should drive a given factor spread."""
    preferred = FACTOR_SORT_VAR_MAP.get(factor_name)
    if preferred in sort_vars:
        return preferred
    return next((var for var in sort_vars if var in FACTOR_SORT_VAR_MAP.values()), None)




def _calc_single_date_sorting(
    date,
    group: pd.DataFrame,
    sort_vars: List[str],
    factor_def: Dict[str, tuple],
    rf_lookup: Optional[Dict],
    min_stocks: int
) -> Optional[Dict]:
    """
    并行计算的helper函数：计算单个日期的因子收益（排序法）

    Args:
        date: 日期
        group: 该日期的数据
        sort_vars: 排序变量
        factor_def: 因子定义
        rf_lookup: 无风险利率查询
        min_stocks: 最小股票数

    Returns:
        单日因子收益字典，如果数据不足则返回None
    """
    if len(group) < min_stocks:
        return None

    group = group.copy()

    for var in sort_vars:
        if var in group.columns:
            non_na_count = group[var].notna().sum()
            if non_na_count >= 10:
                median = group[var].median()
                # NaN values go to 'low' group (consistent with classic method)
                group[f'{var}_group'] = group[var].apply(
                    lambda x: 'low' if pd.isna(x) or x <= median else 'high'
                )
            else:
                # If insufficient data for proper分组, still do 2-group split
                # NaN goes to 'low', non-NaN above median goes to 'high'
                group[f'{var}_group'] = group[var].apply(
                    lambda x: 'low' if pd.isna(x) else 'high'
                )
        else:
            group[f'{var}_group'] = 'low'  # Variable not available, all go to 'low'

    row = {'date': pd.to_datetime(date)}

    # 计算市场收益率并减去无风险利率得到超额收益
    market_return = group['return'].mean()
    if rf_lookup is not None:
        date_key = pd.to_datetime(date)
        rf = rf_lookup.get(date_key, 0.0)
        market_return = market_return - rf
    row['mkt'] = market_return

    for factor_name, (high_group, low_group) in factor_def.items():
        if factor_name == 'mkt':
            continue

        if high_group is None:
            continue

        sort_var = _get_factor_sort_var(factor_name, sort_vars)
        if sort_var is None:
            continue

        high_key = f'{sort_var}_group'
        if high_key not in group.columns:
            continue

        try:
            high_ret = group[group[high_key] == high_group]['return'].mean()
            low_ret = group[group[high_key] == low_group]['return'].mean()

            if pd.notna(high_ret) and pd.notna(low_ret):
                row[factor_name] = high_ret - low_ret
            else:
                row[factor_name] = np.nan
        except Exception:
            row[factor_name] = np.nan

    return row


def _module_value_weighted_return(
    group: pd.DataFrame,
    return_col: str = 'return',
    weight_col: str = 'mkt_cap'
) -> float:
    """模块级市值加权收益率计算"""
    valid = group[[return_col, weight_col]].notna().all(axis=1)
    if valid.sum() == 0:
        return np.nan
    w = group.loc[valid, weight_col]
    r = group.loc[valid, return_col]
    w = w.clip(lower=0)
    if w.sum() == 0:
        return r.mean()
    return (r * w).sum() / w.sum()


def _module_assign_groups(
    series: pd.Series,
    breakpoints: List[float]
) -> pd.Series:
    """模块级分组函数"""
    bounds = [series.quantile(p) for p in breakpoints]
    labels = []
    for val in series:
        if pd.isna(val):
            labels.append('low')
        else:
            assigned = False
            for i, bound in enumerate(bounds):
                if val <= bound:
                    labels.append('low' if i == 0 else ['medium', 'high'][i-1])
                    assigned = True
                    break
            if not assigned:
                labels.append('high')
    return pd.Series(labels, index=series.index)



def ret_none_if_exception(func):
    """异常处理装饰器"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # print(f"An error occurred: {e}")
            return None
    return wrapper


@ret_none_if_exception
def _calc_single_date_classic(
    date,
    group: pd.DataFrame,
    factor_type: FactorType,
    classic_config: Dict,
    sorting_dims: List[str],
    min_stocks: int,
    rf_lookup: Optional[Dict]
) -> Optional[Dict]:
    """并行计算的helper函数：计算单个日期的因子收益（CLASSIC法）"""
    if len(group) < min_stocks:
        return None

    group = group.copy()
    breakpoints = classic_config.get("breakpoints", {})
    weighting = classic_config.get("weighting", "value")

    group_labels = {}
    for var in sorting_dims:
        if var in group.columns and group[var].notna().sum() >= 10:
            bps = breakpoints.get(var, [0.5])
            group_labels[var] = _module_assign_groups(group[var], bps)
        else:
            group_labels[var] = pd.Series(['all'] * len(group), index=group.index)

    if len(sorting_dims) == 1:
        group['portfolio'] = group_labels[sorting_dims[0]]
    else:
        for var in sorting_dims:
            group[f'{var}_g'] = group_labels[var]
        portfolio_labels = group[[f'{var}_g' for var in sorting_dims]].apply(
            lambda x: tuple(x.values), axis=1
        )
        group['portfolio'] = portfolio_labels

    if weighting == "value":
        market_return = _module_value_weighted_return(group)
    else:
        market_return = group['return'].mean()

    if rf_lookup is not None:
        date_key = pd.to_datetime(date)
        rf = rf_lookup.get(date_key, 0.0)
        market_return = market_return - rf

    row = {'date': pd.to_datetime(date), 'mkt': market_return}

    if factor_type == FactorType.FF3:
        row.update(_calc_ff3_classic_module(group, classic_config))
    elif factor_type == FactorType.FF5:
        row.update(_calc_ff5_classic_module(group, classic_config))
    elif factor_type == FactorType.CARHART:
        row.update(_calc_carhart_classic_module(group, classic_config))
    elif factor_type == FactorType.NOVY_MARX:
        row.update(_calc_novymarx_classic_module(group, classic_config))
    elif factor_type == FactorType.HOU_XUE_ZHANG:
        row.update(_calc_hxz_classic_module(group, classic_config))
    elif factor_type == FactorType.DHS:
        row.update(_calc_dhs_classic_module(group, classic_config))
    elif factor_type == FactorType.CH3:
        row.update(_calc_ch3_classic_module(group, classic_config))
    elif factor_type == FactorType.SY4:
        row.update(_calc_sy4_classic_module(group, classic_config))
    elif factor_type == FactorType.REVERSAL:
        row.update(_calc_reversal_classic_module(group, classic_config))
    elif factor_type == FactorType.LOW_VOL:
        row.update(_calc_lowvol_classic_module(group, classic_config))

    return row


def _calc_ff3_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """FF3 CLASSIC模块级计算"""
    size_var = 'mkt_cap'
    value_var = 'bm'
    group = group.copy()
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= group[size_var].median() else 'big'
    )
    bps = classic_config.get("breakpoints", {}).get(value_var, [0.3, 0.7])
    group['value_g'] = _module_assign_groups(group[value_var], bps)

    portfolios = group.groupby(['size_g', 'value_g'])
    small_returns = []
    big_returns = []
    for (size, value), sub in portfolios:
        ret = _module_value_weighted_return(sub)
        if size == 'small':
            small_returns.append(ret)
        else:
            big_returns.append(ret)
    smb = np.mean(small_returns) - np.mean(big_returns) if small_returns and big_returns else np.nan

    high_returns = []
    low_returns = []
    for (size, value), sub in portfolios:
        ret = _module_value_weighted_return(sub)
        if value == 'high':
            high_returns.append(ret)
        elif value == 'low':
            low_returns.append(ret)
    hml = np.mean(high_returns) - np.mean(low_returns) if high_returns and low_returns else np.nan

    return {'smb': smb, 'hml': hml}


def _calc_ff5_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    FF5 CLASSIC模块级计算

    FF5使用2x3独立排序（Size与每个因子分别交叉）:
    - Size: small/big (50% breakpoint)
    - bm: low/medium/high (30%/70% breakpoints)
    - op (Operating Profitability): low/medium/high
    - investment: low/medium/high

    SMB = (S/L + S/M + S/H)/3 - (B/L + B/M + B/H)/3
    HML = (S/H + B/H)/2 - (S/L + B/L)/2  (基于bm)
    RMW = (S/H + B/H)/2 - (S/L + B/L)/2  (基于op)
    CMA = (S/L + B/L)/2 - (S/H + B/H)/2  (基于investment)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # 各因子分组
    bm_bps = bps.get('bm', [0.3, 0.7])
    op_bps = bps.get('op', [0.3, 0.7])
    inv_bps = bps.get('investment', [0.3, 0.7])

    if 'bm' in group.columns:
        group['bm_g'] = _module_assign_groups(group['bm'], bm_bps)
    if 'op' in group.columns:
        group['op_g'] = _module_assign_groups(group['op'], op_bps)
    if 'asset_growth' in group.columns:
        group['inv_g'] = _module_assign_groups(group['asset_growth'], inv_bps)

    # SMB: 基于所有组合
    if 'bm_g' in group.columns and 'op_g' in group.columns and 'inv_g' in group.columns:
        portfolios_all = group.groupby(['size_g', 'bm_g', 'op_g', 'inv_g'])
    elif 'bm_g' in group.columns and 'op_g' in group.columns:
        portfolios_all = group.groupby(['size_g', 'bm_g', 'op_g'])
    elif 'bm_g' in group.columns:
        portfolios_all = group.groupby(['size_g', 'bm_g'])
    else:
        return {'smb': np.nan, 'hml': np.nan, 'rmw': np.nan, 'cma': np.nan}

    port_returns_all = {}
    for combo, sub in portfolios_all:
        port_returns_all[combo] = _module_value_weighted_return(sub)

    # SMB
    small_rets = [v for k, v in port_returns_all.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns_all.items() if k[0] == 'big']
    smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

    # HML (基于bm的3分组)
    bm_portfolios = group.groupby(['size_g', 'bm_g']) if 'bm_g' in group.columns else None
    if bm_portfolios:
        port_returns_bm = {k: _module_value_weighted_return(v) for k, v in bm_portfolios}
        high_rets = [v for k, v in port_returns_bm.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_bm.items() if k[1] == 'low']
        hml = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        hml = np.nan

    # RMW (基于op的3分组)
    op_portfolios = group.groupby(['size_g', 'op_g']) if 'op_g' in group.columns else None
    if op_portfolios:
        port_returns_op = {k: _module_value_weighted_return(v) for k, v in op_portfolios}
        robust_rets = [v for k, v in port_returns_op.items() if k[1] == 'high']
        weak_rets = [v for k, v in port_returns_op.items() if k[1] == 'low']
        rmw = np.nanmean(robust_rets) - np.nanmean(weak_rets) if robust_rets and weak_rets else np.nan
    else:
        rmw = np.nan

    # CMA (基于investment的3分组，低投资=保守)
    inv_portfolios = group.groupby(['size_g', 'inv_g']) if 'inv_g' in group.columns else None
    if inv_portfolios:
        port_returns_inv = {k: _module_value_weighted_return(v) for k, v in inv_portfolios}
        conservative_rets = [v for k, v in port_returns_inv.items() if k[1] == 'low']
        aggressive_rets = [v for k, v in port_returns_inv.items() if k[1] == 'high']
        cma = np.nanmean(conservative_rets) - np.nanmean(aggressive_rets) if conservative_rets and aggressive_rets else np.nan
    else:
        cma = np.nan

    return {'smb': smb, 'hml': hml, 'rmw': rmw, 'cma': cma}


def _calc_carhart_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """CARHART CLASSIC模块级计算"""
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()
    # Use 'small'/'big' labels for size (50% breakpoint), same as FF3
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    for var, var_bps in [('bm', bps.get('bm', [0.3, 0.7])),
                         ('momentum', bps.get('momentum', [0.3, 0.7]))]:
        if var in group.columns:
            group[f'{var}_g'] = _module_assign_groups(group[var], var_bps)

    portfolios = group.groupby(['size_g', 'bm_g', 'momentum_g'])
    port_returns = {}
    for combo, sub in portfolios:
        port_returns[combo] = _module_value_weighted_return(sub)

    small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
    smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

    high_rets = [v for k, v in port_returns.items() if k[1] == 'high']
    low_rets = [v for k, v in port_returns.items() if k[1] == 'low']
    hml = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan

    up_rets = [v for k, v in port_returns.items() if k[2] == 'high']
    down_rets = [v for k, v in port_returns.items() if k[2] == 'low']
    umd = np.nanmean(up_rets) - np.nanmean(down_rets) if up_rets and down_rets else np.nan

    return {'smb': smb, 'hml': hml, 'umd': umd}


def _calc_novymarx_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    NOVY_MARX CLASSIC模块级计算

    NOVY_MARX使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - bm: low/medium/high (用于hml_adj，行业调整)
    - gp_a: low/medium/high (用于盈利因子)
    - momentum: low/medium/high (用于umd)

    SMB = size因子
    HML_adj = 基于行业调整bm的价值因子 (bm - industry_median_bm)
    UMD = 基于momentum的动量因子
    PMU = 基于gp_a的盈利因子
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # 行业调整BM：如果有行业数据，计算 bm_adj = bm - industry_median_bm
    if 'bm' in group.columns and 'industry' in group.columns:
        industry_medians = group.groupby('industry')['bm'].transform('median')
        group['bm_adj'] = group['bm'] - industry_medians
        bm_var = 'bm_adj'
    elif 'bm' in group.columns:
        group['bm_adj'] = group['bm']
        bm_var = 'bm_adj'
    else:
        bm_var = None

    # 各因子分组
    bm_bps = bps.get('bm', [0.3, 0.7])
    gp_a_bps = bps.get('gp_a', [0.3, 0.7])
    mom_bps = bps.get('momentum', [0.3, 0.7])

    if bm_var and bm_var in group.columns:
        group['bm_g'] = _module_assign_groups(group[bm_var], bm_bps)
    if 'gp_a' in group.columns:
        group['gp_a_g'] = _module_assign_groups(group['gp_a'], gp_a_bps)
    if 'momentum' in group.columns:
        group['mom_g'] = _module_assign_groups(group['momentum'], mom_bps)

    # SMB: 基于size
    if 'bm_g' in group.columns:
        bm_portfolios = group.groupby(['size_g', 'bm_g'])
        port_returns_bm = {k: _module_value_weighted_return(v) for k, v in bm_portfolios}
        small_rets = [v for k, v in port_returns_bm.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_bm.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan
    else:
        smb = np.nan

    # HML_adj (基于行业调整bm)
    if 'bm_g' in group.columns:
        high_rets = [v for k, v in port_returns_bm.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_bm.items() if k[1] == 'low']
        hml_adj = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        hml_adj = np.nan

    # UMD (基于momentum)
    if 'mom_g' in group.columns:
        mom_portfolios = group.groupby(['size_g', 'mom_g'])
        port_returns_mom = {k: _module_value_weighted_return(v) for k, v in mom_portfolios}
        up_rets = [v for k, v in port_returns_mom.items() if k[1] == 'high']
        down_rets = [v for k, v in port_returns_mom.items() if k[1] == 'low']
        umd = np.nanmean(up_rets) - np.nanmean(down_rets) if up_rets and down_rets else np.nan
    else:
        umd = np.nan

    # PMU (基于gp_a，高盈利-低盈利)
    if 'gp_a_g' in group.columns:
        gp_a_portfolios = group.groupby(['size_g', 'gp_a_g'])
        port_returns_gp = {k: _module_value_weighted_return(v) for k, v in gp_a_portfolios}
        high_rets = [v for k, v in port_returns_gp.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_gp.items() if k[1] == 'low']
        pmu = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        pmu = np.nan

    return {'smb': smb, 'hml_adj': hml_adj, 'umd': umd, 'gp_a': pmu}


def _calc_hxz_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """HOU_XUE_ZHANG CLASSIC模块级计算"""
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()
    # Use 'small'/'big' labels for size (50% breakpoint), same as FF3
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    for var, var_bps in [('asset_growth', bps.get('asset_growth', [0.3, 0.7])),
                         ('roe', bps.get('roe', [0.3, 0.7]))]:
        if var in group.columns:
            group[f'{var}_g'] = _module_assign_groups(group[var], var_bps)

    portfolios = group.groupby(['size_g', 'asset_growth_g', 'roe_g'])
    port_returns = {}
    for combo, sub in portfolios:
        port_returns[combo] = _module_value_weighted_return(sub)

    small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
    me = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

    conservative_rets = [v for k, v in port_returns.items() if k[1] == 'low']
    aggressive_rets = [v for k, v in port_returns.items() if k[1] == 'high']
    ia = np.nanmean(conservative_rets) - np.nanmean(aggressive_rets) if conservative_rets and aggressive_rets else np.nan

    high_rets = [v for k, v in port_returns.items() if k[2] == 'high']
    low_rets = [v for k, v in port_returns.items() if k[2] == 'low']
    roe_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan

    return {'me': me, 'ia': ia, 'roe': roe_factor}


def _calc_dhs_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    DHS CLASSIC模块级计算 (Daniel-Hirshleifer-Sun行为三因子)

    DHS使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - pead: low/medium/high (盈余公告漂移/ earnings surprise)
    - fin: low/medium/high (融资因子/ net share issuance)

    PEAD = 基于pead的盈余公告漂移因子
    FIN = 基于fin的融资因子
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # PEAD分组
    pead_bps = bps.get('pead', [0.3, 0.7])
    if 'pead' in group.columns:
        group['pead_g'] = _module_assign_groups(group['pead'], pead_bps)

    # FIN分组
    fin_bps = bps.get('fin', [0.3, 0.7])
    if 'fin' in group.columns:
        group['fin_g'] = _module_assign_groups(group['fin'], fin_bps)

    # PEAD因子
    if 'pead_g' in group.columns:
        pead_portfolios = group.groupby(['size_g', 'pead_g'])
        port_returns_pead = {k: _module_value_weighted_return(v) for k, v in pead_portfolios}
        high_rets = [v for k, v in port_returns_pead.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_pead.items() if k[1] == 'low']
        pead_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        pead_factor = np.nan

    # FIN因子
    if 'fin_g' in group.columns:
        fin_portfolios = group.groupby(['size_g', 'fin_g'])
        port_returns_fin = {k: _module_value_weighted_return(v) for k, v in fin_portfolios}
        high_rets = [v for k, v in port_returns_fin.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_fin.items() if k[1] == 'low']
        fin_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        fin_factor = np.nan

    # DHS不计算SMB，只计算行为因子
    return {'pead': pead_factor, 'fin': fin_factor}


def _calc_ch3_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    CH3 CLASSIC模块级计算 (中国三因子模型)

    CH3使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - bm: low/medium/high (账面市值比)

    VMG = 高BM组合均值 - 低BM组合均值 (剔除小市值壳价值干扰)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # BM分组
    bm_bps = bps.get('bm', [0.3, 0.7])
    if 'bm' in group.columns:
        group['bm_g'] = _module_assign_groups(group['bm'], bm_bps)

    # SMB因子
    if 'bm_g' in group.columns:
        bm_portfolios = group.groupby(['size_g', 'bm_g'])
        port_returns_bm = {k: _module_value_weighted_return(v) for k, v in bm_portfolios}
        small_rets = [v for k, v in port_returns_bm.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_bm.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan
    else:
        smb = np.nan

    # VMG因子 (Value Minus Growth)
    # CH3在价值腿构建前先剔除当期最小30%市值股票。
    vmg_group = group[group[size_var].notna()].copy()
    if 'bm' in vmg_group.columns and not vmg_group.empty:
        vmg_cutoff = vmg_group[size_var].quantile(0.3)
        vmg_group = vmg_group[vmg_group[size_var] > vmg_cutoff].copy()

        if not vmg_group.empty:
            vmg_group['bm_g'] = _module_assign_groups(vmg_group['bm'], bm_bps)
            vmg_portfolios = vmg_group.groupby(['size_g', 'bm_g'])
            vmg_returns = {k: _module_value_weighted_return(v) for k, v in vmg_portfolios}
            high_rets = [v for k, v in vmg_returns.items() if k[1] == 'high']
            low_rets = [v for k, v in vmg_returns.items() if k[1] == 'low']
            vmg = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
        else:
            vmg = np.nan
    else:
        vmg = np.nan

    return {'smb': smb, 'vmg': vmg}


def _calc_sy4_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    SY4 CLASSIC模块级计算 (Stambaugh-Yuan四因子模型)

    SY4使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - mgmt: low/medium/high (管理因子)
    - perf: low/medium/high (绩效因子)

    MGMT = 高管理评分组合均值 - 低管理评分组合均值
    PERF = 高绩效评分组合均值 - 低绩效评分组合均值
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # MGMT分组
    mgmt_bps = bps.get('mgmt', [0.2, 0.8])
    if 'mgmt' in group.columns:
        group['mgmt_g'] = _module_assign_groups(group['mgmt'], mgmt_bps)

    # PERF分组
    perf_bps = bps.get('perf', [0.2, 0.8])
    if 'perf' in group.columns:
        group['perf_g'] = _module_assign_groups(group['perf'], perf_bps)

    # SMB因子 (基于bm)
    if 'mgmt_g' in group.columns:
        mgmt_portfolios = group.groupby(['size_g', 'mgmt_g'])
        port_returns_mgmt = {k: _module_value_weighted_return(v) for k, v in mgmt_portfolios}
        small_rets = [v for k, v in port_returns_mgmt.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_mgmt.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan
    else:
        smb = np.nan

    # MGMT因子
    if 'mgmt_g' in group.columns:
        high_rets = [v for k, v in port_returns_mgmt.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_mgmt.items() if k[1] == 'low']
        mgmt_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        mgmt_factor = np.nan

    # PERF因子
    if 'perf_g' in group.columns:
        perf_portfolios = group.groupby(['size_g', 'perf_g'])
        port_returns_perf = {k: _module_value_weighted_return(v) for k, v in perf_portfolios}
        high_rets = [v for k, v in port_returns_perf.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_perf.items() if k[1] == 'low']
        perf_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan
    else:
        perf_factor = np.nan

    return {'smb': smb, 'mgmt': mgmt_factor, 'perf': perf_factor}


def _calc_reversal_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    REVERSAL CLASSIC模块级计算 (短期反转模型)

    REVERSAL使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - rev: low/medium/high (反转因子，过去20日收益率)

    REV = 低收益率组合均值 - 高收益率组合均值 (反转效应：跌的多的未来涨的多)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # REV分组
    rev_bps = bps.get('rev', [0.3, 0.7])
    if 'rev' in group.columns:
        group['rev_g'] = _module_assign_groups(group['rev'], rev_bps)

    # SMB因子
    if 'rev_g' in group.columns:
        rev_portfolios = group.groupby(['size_g', 'rev_g'])
        port_returns_rev = {k: _module_value_weighted_return(v) for k, v in rev_portfolios}
        small_rets = [v for k, v in port_returns_rev.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_rev.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan
    else:
        smb = np.nan

    # REV因子 (反转：跌的多的未来涨的多，所以是low - high)
    if 'rev_g' in group.columns:
        low_rets = [v for k, v in port_returns_rev.items() if k[1] == 'low']
        high_rets = [v for k, v in port_returns_rev.items() if k[1] == 'high']
        rev_factor = np.nanmean(low_rets) - np.nanmean(high_rets) if low_rets and high_rets else np.nan
    else:
        rev_factor = np.nan

    return {'smb': smb, 'rev': rev_factor}


def _calc_lowvol_classic_module(group: pd.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    LOW_VOL CLASSIC模块级计算 (低波动模型)

    LOW_VOL使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - ivol: low/medium/high (特质波动率)

    IVOL = 低波动组合均值 - 高波动组合均值 (低波动异象)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    group = group.copy()

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = group[size_var].quantile(size_breakpoint)
    group['size_g'] = group[size_var].apply(
        lambda x: 'small' if pd.isna(x) or x <= size_median else 'big'
    )

    # IVOL分组
    ivol_bps = bps.get('ivol', [0.3, 0.7])
    if 'ivol' in group.columns:
        group['ivol_g'] = _module_assign_groups(group['ivol'], ivol_bps)

    # SMB因子
    if 'ivol_g' in group.columns:
        ivol_portfolios = group.groupby(['size_g', 'ivol_g'])
        port_returns_ivol = {k: _module_value_weighted_return(v) for k, v in ivol_portfolios}
        small_rets = [v for k, v in port_returns_ivol.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_ivol.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan
    else:
        smb = np.nan

    # IVOL因子 (低波动股票表现更好，所以是low - high)
    if 'ivol_g' in group.columns:
        low_rets = [v for k, v in port_returns_ivol.items() if k[1] == 'low']
        high_rets = [v for k, v in port_returns_ivol.items() if k[1] == 'high']
        ivol_factor = np.nanmean(low_rets) - np.nanmean(high_rets) if low_rets and high_rets else np.nan
    else:
        ivol_factor = np.nan

    return {'smb': smb, 'ivol': ivol_factor}


# =============================================================================
# Polars优化版本 - 使用向量化操作替代Python循环
# =============================================================================

def _pl_assign_groups(
    series: pl.Series,
    breakpoints: List[float]
) -> pl.Expr:
    """
    Polars版本：根据分位数断点将数据分配到组

    Args:
        series: 要分组的数据
        breakpoints: 分位数列表，如 [0.3, 0.7]

    Returns:
        分组标签Polars表达式
    """
    # Check if series has valid (non-NaN) data
    if series.null_count() == series.len():
        # All values are null, assign all to 'low'
        return pl.lit('low')

    bounds = []
    for p in breakpoints:
        q = series.quantile(p)
        # Handle case where quantile returns None for edge cases
        bounds.append(q if q is not None else float('nan'))

    n = len(bounds)

    # 构建when-otherwise链，逐个添加条件
    # NaN values go to 'low' group
    result = pl.when(series.is_null()).then(pl.lit('low'))
    for i, bound in enumerate(bounds):
        if pd.isna(bound):
            # Skip invalid bounds
            continue
        label = 'low' if i == 0 else ('medium' if i < n - 1 else 'high')
        result = result.when(series <= bound).then(pl.lit(label))
    result = result.otherwise(pl.lit('high'))

    return result


def _pl_value_weighted_return(
    df: pl.DataFrame,
    return_col: str = 'return',
    weight_col: str = 'mkt_cap'
) -> float:
    """Polars版本：市值加权收益率计算"""
    tmp = df.filter(
        pl.col(return_col).is_not_null() & pl.col(weight_col).is_not_null()
    )
    if tmp.height == 0:
        return float('nan')

    # 使用Polars表达式进行市值加权（clip负值为0）
    total_w = tmp.select(pl.col(weight_col).clip(lower_bound=0).sum())[weight_col][0]
    if total_w is None or total_w == 0:
        return float(tmp[return_col].mean())

    weighted_sum = tmp.select((pl.col(return_col) * pl.col(weight_col).clip(lower_bound=0)).sum())[return_col][0]
    return float(weighted_sum / total_w)


def _pl_group_by_vw_returns(
    pl_df: pl.DataFrame,
    group_cols: List[str],
    return_col: str = 'return',
    weight_col: str = 'mkt_cap'
) -> Dict[Tuple, float]:
    """
    Polars版本：分组计算市值加权收益率

    Args:
        pl_df: Polars DataFrame
        group_cols: 分组列
        return_col: 收益率列
        weight_col: 权重列（市值）

    Returns:
        {(group_key_tuple): weighted_return} 字典
    """
    # 先filter掉null和负权重
    tmp = pl_df.filter(
        pl.col(return_col).is_not_null() &
        pl.col(weight_col).is_not_null() &
        (pl.col(weight_col) > 0)
    )

    if tmp.height == 0:
        return {}

    # 为每个分组计算市值加权收益率
    result = {}
    for keys, grp in tmp.group_by(group_cols, maintain_order=True):
        w = grp[weight_col]
        r = grp[return_col]
        total_w = w.sum()
        if total_w == 0:
            result[keys if isinstance(keys, tuple) else (keys,)] = float(r.mean())
        else:
            result[keys if isinstance(keys, tuple) else (keys,)] = float((r * w).sum() / total_w)

    return result


def _calc_single_date_sorting_polars(
    date,
    group: Union[pd.DataFrame, pl.DataFrame],
    sort_vars: List[str],
    factor_def: Dict[str, tuple],
    rf_lookup: Optional[Dict],
    min_stocks: int
) -> Optional[Dict]:
    """
    Polars优化版本：计算单个日期的因子收益（排序法）

    Args:
        date: 日期
        group: 该日期的数据（pandas或polars DataFrame）
        sort_vars: 排序变量
        factor_def: 因子定义
        rf_lookup: 无风险利率查询
        min_stocks: 最小股票数

    Returns:
        单日因子收益字典，如果数据不足则返回None
    """
    # 转换为Polars
    if isinstance(group, pd.DataFrame):
        pdf = group
    else:
        pdf = group.to_pandas()

    pl_df = pl.from_pandas(pdf)

    if pl_df.height < min_stocks:
        return None

    # 批量计算分组
    for var in sort_vars:
        if var in pl_df.columns:
            non_na_count = pl_df.height - pl_df[var].null_count()
            if non_na_count >= 10:
                median = pl_df[var].median()
                pl_df = pl_df.with_columns(
                    pl.when(pl.col(var).is_null() | (pl.col(var) <= median))
                      .then(pl.lit('low'))
                      .otherwise(pl.lit('high'))
                      .alias(f'{var}_group')
                )
            else:
                # If insufficient data for proper分组, still do 2-group split
                # NaN goes to 'low', non-NaN goes to 'high'
                pl_df = pl_df.with_columns(
                    pl.when(pl.col(var).is_null())
                      .then(pl.lit('low'))
                      .otherwise(pl.lit('high'))
                      .alias(f'{var}_group')
                )
        else:
            # Variable not available, all go to 'low'
            pl_df = pl_df.with_columns(pl.lit('low').alias(f'{var}_group'))

    row = {'date': pd.to_datetime(date)}

    # 计算市场收益率
    market_return = pl_df['return'].mean()
    if rf_lookup is not None:
        date_key = pd.to_datetime(date)
        rf = rf_lookup.get(date_key, 0.0)
        market_return = market_return - rf
    row['mkt'] = market_return

    for factor_name, (high_group, low_group) in factor_def.items():
        if factor_name == 'mkt' or high_group is None:
            continue

        sort_var = _get_factor_sort_var(factor_name, sort_vars)
        if sort_var is None:
            continue

        high_key = f'{sort_var}_group'
        if high_key not in pl_df.columns:
            continue

        try:
            high_ret = pl_df.filter(pl.col(high_key) == high_group)['return'].mean()
            low_ret = pl_df.filter(pl.col(high_key) == low_group)['return'].mean()

            if high_ret is not None and low_ret is not None:
                row[factor_name] = high_ret - low_ret
            else:
                row[factor_name] = float('nan')
        except Exception:
            row[factor_name] = float('nan')

    return row


@ret_none_if_exception  
def _calc_single_date_classic_polars(
    date,
    group: Union[pd.DataFrame, pl.DataFrame],
    factor_type: FactorType,
    classic_config: Dict,
    sorting_dims: List[str],
    min_stocks: int,
    rf_lookup: Optional[Dict]
) -> Optional[Dict]:
    """
    Polars优化版本：计算单个日期的因子收益（CLASSIC法）

    Args:
        date: 日期
        group: 该日期的数据
        factor_type: 因子类型
        classic_config: 经典配置
        sorting_dims: 排序维度
        min_stocks: 最小股票数
        rf_lookup: 无风险利率查询

    Returns:
        单日因子收益字典
    """
    if isinstance(group, pd.DataFrame):
        pdf = group
    else:
        pdf = group.to_pandas()

    pl_df = pl.from_pandas(pdf)

    if pl_df.height < min_stocks:
        return None

    breakpoints = classic_config.get("breakpoints", {})
    weighting = classic_config.get("weighting", "value")

    # 计算分组标签
    group_labels = {}
    # breakpoint()
    for var in sorting_dims:
        if var in pl_df.columns and pl_df[var].null_count() < pl_df.height - 10:
            bps = breakpoints.get(var, [0.5])
            group_labels[var] = _pl_assign_groups(pl_df[var], bps)
        else:
            group_labels[var] = pl.lit('all')

    if len(sorting_dims) == 1:
        pl_df = pl_df.with_columns(group_labels[sorting_dims[0]].alias('portfolio'))
    else:
        for var in sorting_dims:
            pl_df = pl_df.with_columns(group_labels[var].alias(f'{var}_g'))
        # 构建组合标签
        portfolio_labels = pl.concat_str([pl.col(f'{var}_g') for var in sorting_dims], separator="_")
        pl_df = pl_df.with_columns(portfolio_labels.alias('portfolio'))

    # 计算市场收益率
    if weighting == "value":
        market_return = _pl_value_weighted_return(pl_df)
    else:
        market_return = pl_df['return'].mean()

    if rf_lookup is not None:
        date_key = pd.to_datetime(date)
        rf = rf_lookup.get(date_key, 0.0)
        market_return = market_return - rf

    row = {'date': pd.to_datetime(date), 'mkt': market_return}

    if factor_type == FactorType.FF3:
        row.update(_calc_ff3_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.FF5:
        row.update(_calc_ff5_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.CARHART:
        row.update(_calc_carhart_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.NOVY_MARX:
        row.update(_calc_novymarx_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.HOU_XUE_ZHANG:
        row.update(_calc_hxz_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.DHS:
        row.update(_calc_dhs_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.CH3:
        row.update(_calc_ch3_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.SY4:
        row.update(_calc_sy4_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.REVERSAL:
        row.update(_calc_reversal_classic_module_polars(pl_df, classic_config))
    elif factor_type == FactorType.LOW_VOL:
        row.update(_calc_lowvol_classic_module_polars(pl_df, classic_config))

    return row


def _calc_ff3_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """FF3 CLASSIC Polars版本"""
    size_var = 'mkt_cap'
    value_var = 'bm'

    size_median = pl_df[size_var].median()
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    bps = classic_config.get("breakpoints", {}).get(value_var, [0.3, 0.7])
    pl_df = pl_df.with_columns(_pl_assign_groups(pl_df[value_var], bps).alias('value_g'))

    # 分组计算市值加权收益率
    port_returns = _pl_group_by_vw_returns(pl_df, ['size_g', 'value_g'])

    small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
    smb = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

    high_rets = [v for k, v in port_returns.items() if k[1] == 'high']
    low_rets = [v for k, v in port_returns.items() if k[1] == 'low']
    hml = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')

    return {'smb': smb, 'hml': hml}


def _calc_ff5_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    FF5 CLASSIC Polars版本

    FF5使用2x3独立排序（Size与每个因子分别交叉）:
    - Size: small/big (50% breakpoint)
    - bm: low/medium/high (30%/70% breakpoints)
    - op (Operating Profitability): low/medium/high
    - investment: low/medium/high

    SMB = (S/L + S/M + S/H)/3 - (B/L + B/M + B/H)/3
    HML = (S/H + B/H)/2 - (S/L + B/L)/2  (基于bm)
    RMW = (S/H + B/H)/2 - (S/L + B/L)/2  (基于op)
    CMA = (S/L + B/L)/2 - (S/H + B/H)/2  (基于investment)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # 各因子分组
    bm_bps = bps.get('bm', [0.3, 0.7])
    op_bps = bps.get('op', [0.3, 0.7])
    inv_bps = bps.get('investment', [0.3, 0.7])

    if 'bm' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['bm'], bm_bps).alias('bm_g'))
    if 'op' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['op'], op_bps).alias('op_g'))
    if 'asset_growth' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['asset_growth'], inv_bps).alias('inv_g'))

    result = {}

    # SMB: 基于所有组合
    if all(c in pl_df.columns for c in ['bm_g', 'op_g', 'inv_g']):
        port_returns_all = _pl_group_by_vw_returns(pl_df, ['size_g', 'bm_g', 'op_g', 'inv_g'])
    elif all(c in pl_df.columns for c in ['bm_g', 'op_g']):
        port_returns_all = _pl_group_by_vw_returns(pl_df, ['size_g', 'bm_g', 'op_g'])
    elif 'bm_g' in pl_df.columns:
        port_returns_all = _pl_group_by_vw_returns(pl_df, ['size_g', 'bm_g'])
    else:
        return {'smb': float('nan'), 'hml': float('nan'), 'rmw': float('nan'), 'cma': float('nan')}

    small_rets = [v for k, v in port_returns_all.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns_all.items() if k[0] == 'big']
    result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

    # HML (基于bm)
    if 'bm_g' in pl_df.columns:
        port_returns_bm = _pl_group_by_vw_returns(pl_df, ['size_g', 'bm_g'])
        high_rets = [v for k, v in port_returns_bm.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_bm.items() if k[1] == 'low']
        result['hml'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['hml'] = float('nan')

    # RMW (基于op)
    if 'op_g' in pl_df.columns:
        port_returns_op = _pl_group_by_vw_returns(pl_df, ['size_g', 'op_g'])
        robust_rets = [v for k, v in port_returns_op.items() if k[1] == 'high']
        weak_rets = [v for k, v in port_returns_op.items() if k[1] == 'low']
        result['rmw'] = (sum(robust_rets) / len(robust_rets) - sum(weak_rets) / len(weak_rets)) if robust_rets and weak_rets else float('nan')
    else:
        result['rmw'] = float('nan')

    # CMA (基于investment)
    if 'inv_g' in pl_df.columns:
        port_returns_inv = _pl_group_by_vw_returns(pl_df, ['size_g', 'inv_g'])
        conservative_rets = [v for k, v in port_returns_inv.items() if k[1] == 'low']
        aggressive_rets = [v for k, v in port_returns_inv.items() if k[1] == 'high']
        result['cma'] = (sum(conservative_rets) / len(conservative_rets) - sum(aggressive_rets) / len(aggressive_rets)) if conservative_rets and aggressive_rets else float('nan')
    else:
        result['cma'] = float('nan')

    return result


def _calc_carhart_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """CARHART CLASSIC Polars版本"""
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    # Use 'small'/'big' labels for size (50% breakpoint), same as FF3
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # Build list of grouping columns based on what actually exists in the dataframe
    group_cols = ['size_g']
    for var, var_bps in [('bm', bps.get('bm', [0.3, 0.7])),
                         ('momentum', bps.get('momentum', [0.3, 0.7]))]:
        if var in pl_df.columns:
            pl_df = pl_df.with_columns(_pl_assign_groups(pl_df[var], var_bps).alias(f'{var}_g'))
            group_cols.append(f'{var}_g')

    port_returns = _pl_group_by_vw_returns(pl_df, group_cols)

    # Determine factor values based on available groups
    result = {}

    # SMB: always calculated (size_g exists)
    small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
    result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

    # HML: requires bm_g (3rd column in group_cols if exists)
    if 'bm_g' in group_cols:
        bm_idx = group_cols.index('bm_g')
        high_rets = [v for k, v in port_returns.items() if k[bm_idx] == 'high']
        low_rets = [v for k, v in port_returns.items() if k[bm_idx] == 'low']
        result['hml'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['hml'] = float('nan')

    # UMD: requires momentum_g (last column in group_cols if exists)
    if 'momentum_g' in group_cols:
        mom_idx = group_cols.index('momentum_g')
        up_rets = [v for k, v in port_returns.items() if k[mom_idx] == 'high']
        down_rets = [v for k, v in port_returns.items() if k[mom_idx] == 'low']
        result['umd'] = (sum(up_rets) / len(up_rets) - sum(down_rets) / len(down_rets)) if up_rets and down_rets else float('nan')
    else:
        result['umd'] = float('nan')

    return result


def _calc_novymarx_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    NOVY_MARX CLASSIC Polars版本

    NOVY_MARX使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - bm: low/medium/high (用于hml_adj，行业调整)
    - gp_a: low/medium/high (用于盈利因子)
    - momentum: low/medium/high (用于umd)

    SMB = size因子
    HML_adj = 基于行业调整bm的价值因子 (bm - industry_median_bm)
    UMD = 基于momentum的动量因子
    PMU = 基于gp_a的盈利因子
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # 行业调整BM：如果有行业数据，计算 bm_adj = bm - industry_median_bm
    if 'bm' in pl_df.columns and 'industry' in pl_df.columns:
        industry_medians = pl_df.group_by('industry').agg(pl.col('bm').median())
        industry_medians = industry_medians.rename({'bm': 'bm_industry_median'})
        pl_df = pl_df.join(industry_medians, on='industry', how='left')
        pl_df = pl_df.with_columns((pl.col('bm') - pl.col('bm_industry_median')).alias('bm_adj'))
        bm_var = 'bm_adj'
    elif 'bm' in pl_df.columns:
        pl_df = pl_df.with_columns(pl.col('bm').alias('bm_adj'))
        bm_var = 'bm_adj'
    else:
        bm_var = None

    # 各因子分组
    bm_bps = bps.get('bm', [0.3, 0.7])
    gp_a_bps = bps.get('gp_a', [0.3, 0.7])
    mom_bps = bps.get('momentum', [0.3, 0.7])

    if bm_var and bm_var in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df[bm_var], bm_bps).alias('bm_g'))
    if 'gp_a' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['gp_a'], gp_a_bps).alias('gp_a_g'))
    if 'momentum' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['momentum'], mom_bps).alias('mom_g'))

    result = {}

    # SMB (基于bm)
    if 'bm_g' in pl_df.columns:
        port_returns_bm = _pl_group_by_vw_returns(pl_df, ['size_g', 'bm_g'])
        small_rets = [v for k, v in port_returns_bm.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_bm.items() if k[0] == 'big']
        result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')
    else:
        result['smb'] = float('nan')

    # HML_adj (基于行业调整bm)
    if 'bm_g' in pl_df.columns:
        high_rets = [v for k, v in port_returns_bm.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_bm.items() if k[1] == 'low']
        result['hml_adj'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['hml_adj'] = float('nan')

    # UMD (基于momentum)
    if 'mom_g' in pl_df.columns:
        port_returns_mom = _pl_group_by_vw_returns(pl_df, ['size_g', 'mom_g'])
        up_rets = [v for k, v in port_returns_mom.items() if k[1] == 'high']
        down_rets = [v for k, v in port_returns_mom.items() if k[1] == 'low']
        result['umd'] = (sum(up_rets) / len(up_rets) - sum(down_rets) / len(down_rets)) if up_rets and down_rets else float('nan')
    else:
        result['umd'] = float('nan')

    # GP_A (基于gp_a)
    if 'gp_a_g' in pl_df.columns:
        port_returns_gp = _pl_group_by_vw_returns(pl_df, ['size_g', 'gp_a_g'])
        high_rets = [v for k, v in port_returns_gp.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_gp.items() if k[1] == 'low']
        result['gp_a'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['gp_a'] = float('nan')

    return result


def _calc_hxz_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """HOU_XUE_ZHANG CLASSIC Polars版本"""
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'
    # Use 'small'/'big' labels for size (50% breakpoint), same as FF3
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # Build list of grouping columns based on what actually exists in the dataframe
    group_cols = ['size_g']
    for var, var_bps in [('asset_growth', bps.get('asset_growth', [0.3, 0.7])),
                         ('roe', bps.get('roe', [0.3, 0.7]))]:
        if var in pl_df.columns:
            pl_df = pl_df.with_columns(_pl_assign_groups(pl_df[var], var_bps).alias(f'{var}_g'))
            group_cols.append(f'{var}_g')

    port_returns = _pl_group_by_vw_returns(pl_df, group_cols)

    result = {}

    # ME: always calculated (size_g exists)
    small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
    big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
    result['me'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

    # IA: requires asset_growth_g
    if 'asset_growth_g' in group_cols:
        inv_idx = group_cols.index('asset_growth_g')
        conservative_rets = [v for k, v in port_returns.items() if k[inv_idx] == 'low']
        aggressive_rets = [v for k, v in port_returns.items() if k[inv_idx] == 'high']
        result['ia'] = (sum(conservative_rets) / len(conservative_rets) - sum(aggressive_rets) / len(aggressive_rets)) if conservative_rets and aggressive_rets else float('nan')
    else:
        result['ia'] = float('nan')

    # ROE: requires roe_g
    if 'roe_g' in group_cols:
        roe_idx = group_cols.index('roe_g')
        high_rets = [v for k, v in port_returns.items() if k[roe_idx] == 'high']
        low_rets = [v for k, v in port_returns.items() if k[roe_idx] == 'low']
        result['roe'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['roe'] = float('nan')

    return result


def _calc_dhs_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    DHS CLASSIC Polars版本 (Daniel-Hirshleifer-Sun行为三因子)

    DHS使用2x3独立排序:
    - Size: small/big (50% breakpoint)
    - pead: low/medium/high (盈余公告漂移/ earnings surprise)
    - fin: low/medium/high (融资因子/ net share issuance)

    PEAD = 基于pead的盈余公告漂移因子
    FIN = 基于fin的融资因子
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # PEAD分组
    pead_bps = bps.get('pead', [0.3, 0.7])
    if 'pead' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['pead'], pead_bps).alias('pead_g'))

    # FIN分组
    fin_bps = bps.get('fin', [0.3, 0.7])
    if 'fin' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['fin'], fin_bps).alias('fin_g'))

    result = {}

    # PEAD因子
    if 'pead_g' in pl_df.columns:
        port_returns_pead = _pl_group_by_vw_returns(pl_df, ['size_g', 'pead_g'])
        high_rets = [v for k, v in port_returns_pead.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_pead.items() if k[1] == 'low']
        result['pead'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['pead'] = float('nan')

    # FIN因子
    if 'fin_g' in pl_df.columns:
        port_returns_fin = _pl_group_by_vw_returns(pl_df, ['size_g', 'fin_g'])
        high_rets = [v for k, v in port_returns_fin.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_fin.items() if k[1] == 'low']
        result['fin'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['fin'] = float('nan')

    return result


def _calc_ch3_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    CH3 CLASSIC Polars版本 (中国三因子模型)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # BM分组
    bm_bps = bps.get('bm', [0.3, 0.7])
    if 'bm' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['bm'], bm_bps).alias('bm_g'))

    result = {}

    # SMB
    if 'bm_g' in pl_df.columns:
        port_returns_bm = _pl_group_by_vw_returns(pl_df, ['size_g', 'bm_g'])
        small_rets = [v for k, v in port_returns_bm.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_bm.items() if k[0] == 'big']
        result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

        # VMG: exclude the bottom 30% by market cap before value sorting.
        valid_caps = pl_df.filter(pl.col(size_var).is_not_null())
        if valid_caps.height > 0:
            vmg_cutoff = valid_caps[size_var].quantile(0.3)
            vmg_df = pl_df.filter(pl.col(size_var).is_not_null() & (pl.col(size_var) > vmg_cutoff))
        else:
            vmg_df = pl_df.clear()

        if vmg_df.height > 0 and 'bm' in vmg_df.columns:
            vmg_df = vmg_df.with_columns(_pl_assign_groups(vmg_df['bm'], bm_bps).alias('bm_g'))
            vmg_returns = _pl_group_by_vw_returns(vmg_df, ['size_g', 'bm_g'])
            high_rets = [v for k, v in vmg_returns.items() if k[1] == 'high']
            low_rets = [v for k, v in vmg_returns.items() if k[1] == 'low']
            result['vmg'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
        else:
            result['vmg'] = float('nan')
    else:
        result['smb'] = float('nan')
        result['vmg'] = float('nan')

    return result


def _calc_sy4_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    SY4 CLASSIC Polars版本 (Stambaugh-Yuan四因子模型)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # MGMT分组
    mgmt_bps = bps.get('mgmt', [0.2, 0.8])
    if 'mgmt' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['mgmt'], mgmt_bps).alias('mgmt_g'))

    # PERF分组
    perf_bps = bps.get('perf', [0.2, 0.8])
    if 'perf' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['perf'], perf_bps).alias('perf_g'))

    result = {}

    # SMB (基于mgmt)
    if 'mgmt_g' in pl_df.columns:
        port_returns_mgmt = _pl_group_by_vw_returns(pl_df, ['size_g', 'mgmt_g'])
        small_rets = [v for k, v in port_returns_mgmt.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_mgmt.items() if k[0] == 'big']
        result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

        # MGMT因子
        high_rets = [v for k, v in port_returns_mgmt.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_mgmt.items() if k[1] == 'low']
        result['mgmt'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['smb'] = float('nan')
        result['mgmt'] = float('nan')

    # PERF因子
    if 'perf_g' in pl_df.columns:
        port_returns_perf = _pl_group_by_vw_returns(pl_df, ['size_g', 'perf_g'])
        high_rets = [v for k, v in port_returns_perf.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns_perf.items() if k[1] == 'low']
        result['perf'] = (sum(high_rets) / len(high_rets) - sum(low_rets) / len(low_rets)) if high_rets and low_rets else float('nan')
    else:
        result['perf'] = float('nan')

    return result


def _calc_reversal_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    REVERSAL CLASSIC Polars版本 (短期反转模型)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # REV分组
    rev_bps = bps.get('rev', [0.3, 0.7])
    if 'rev' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['rev'], rev_bps).alias('rev_g'))

    result = {}

    # SMB
    if 'rev_g' in pl_df.columns:
        port_returns_rev = _pl_group_by_vw_returns(pl_df, ['size_g', 'rev_g'])
        small_rets = [v for k, v in port_returns_rev.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_rev.items() if k[0] == 'big']
        result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

        # REV因子 (反转：low - high)
        low_rets = [v for k, v in port_returns_rev.items() if k[1] == 'low']
        high_rets = [v for k, v in port_returns_rev.items() if k[1] == 'high']
        result['rev'] = (sum(low_rets) / len(low_rets) - sum(high_rets) / len(high_rets)) if low_rets and high_rets else float('nan')
    else:
        result['smb'] = float('nan')
        result['rev'] = float('nan')

    return result


def _calc_lowvol_classic_module_polars(pl_df: pl.DataFrame, classic_config: Dict) -> Dict[str, float]:
    """
    LOW_VOL CLASSIC Polars版本 (低波动模型)
    """
    bps = classic_config.get("breakpoints", {})
    size_var = 'mkt_cap'

    # Size分组
    size_breakpoint = bps.get(size_var, [0.5])[0]
    size_median = pl_df[size_var].quantile(size_breakpoint)
    pl_df = pl_df.with_columns(
        pl.when(pl.col(size_var).is_null() | (pl.col(size_var) <= size_median))
          .then(pl.lit('small'))
          .otherwise(pl.lit('big'))
          .alias('size_g')
    )

    # IVOL分组
    ivol_bps = bps.get('ivol', [0.3, 0.7])
    if 'ivol' in pl_df.columns:
        pl_df = pl_df.with_columns(_pl_assign_groups(pl_df['ivol'], ivol_bps).alias('ivol_g'))

    result = {}

    # SMB
    if 'ivol_g' in pl_df.columns:
        port_returns_ivol = _pl_group_by_vw_returns(pl_df, ['size_g', 'ivol_g'])
        small_rets = [v for k, v in port_returns_ivol.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns_ivol.items() if k[0] == 'big']
        result['smb'] = (sum(small_rets) / len(small_rets) - sum(big_rets) / len(big_rets)) if small_rets and big_rets else float('nan')

        # IVOL因子 (低波动：low - high)
        low_rets = [v for k, v in port_returns_ivol.items() if k[1] == 'low']
        high_rets = [v for k, v in port_returns_ivol.items() if k[1] == 'high']
        result['ivol'] = (sum(low_rets) / len(low_rets) - sum(high_rets) / len(high_rets)) if low_rets and high_rets else float('nan')
    else:
        result['smb'] = float('nan')
        result['ivol'] = float('nan')

    return result


class GeneralFactorCalculator:
    """
    通用因子计算器

    支持通过配置计算所有类型的因子。
    """

    def __init__(
        self,
        factor_type: FactorType,
        method: CalculationMethod = CalculationMethod.SIMPLE,
        period: TimePeriod = TimePeriod.MONTHLY,
        min_stocks: int = 20,
        n_jobs: Optional[int] = None,
        use_polars: bool = True
    ):
        """
        初始化因子计算器

        Args:
            factor_type: 因子类型
            method: 计算方法
            period: 时间周期
            min_stocks: 最小股票数
            n_jobs: 并行任务数，默认为CPU核心数（最多4个）
            use_polars: 是否使用Polars加速（默认True）
        """
        self.factor_type = factor_type
        self.method = method
        self.period = period
        self.min_stocks = min_stocks
        self.n_jobs = n_jobs if n_jobs is not None else DEFAULT_N_JOBS
        self.use_polars = use_polars

        self.config = FACTOR_CONFIGS[factor_type]
        self.factor_names = self.config["factors"]
        self.sorting_dims = self.config["sorting_dims"]
        self.required_data = self.config["required_data"]

        # CLASSIC配置（如果使用CLASSIC方法）
        self.classic_config = CLASSIC_CONFIGS.get(factor_type, {})

    def calculate(
        self,
        stock_returns: pd.DataFrame,
        market_cap: pd.DataFrame,
        fundamentals: Optional[Dict[str, pd.DataFrame]] = None,
        risk_free_rate: Optional[pd.DataFrame] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        计算因子收益率

        Args:
            stock_returns: 股票收益率
            market_cap: 市值数据（CAPM时为市场超额收益率数据）
            fundamentals: 基本面数据字典 {field_name: DataFrame}
            risk_free_rate: 无风险利率数据，包含 date, rf 列（年化百分比）

        Returns:
            因子收益率DataFrame
        """
        if self.factor_type == FactorType.CAPM:
            # CAPM: market_cap 实际上是 market_return (mkt_excess)
            market_return = market_cap
            return self._calculate_capm_factor(market_return)
        return self._calculate_from_data(stock_returns, market_cap, fundamentals, risk_free_rate)

    def _calculate_from_data(
        self,
        stock_returns: pd.DataFrame,
        market_cap: pd.DataFrame,
        fundamentals: Optional[Dict[str, pd.DataFrame]] = None,
        risk_free_rate: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """使用传入的数据计算因子"""
        if stock_returns is None or stock_returns.empty:
            raise ValueError("stock_returns 不能为空")
        if market_cap is None or market_cap.empty:
            raise ValueError("market_cap 不能为空")

        df = stock_returns.merge(
            market_cap[['symbol', 'date', 'mkt_cap']],
            on=['symbol', 'date'],
            how='inner'
        )

        # 处理无风险利率数据
        rf_lookup = None
        if risk_free_rate is not None and not risk_free_rate.empty:
            rf_lookup = self._prepare_risk_free_rate(risk_free_rate)

        if fundamentals:
            for field_name, field_data in fundamentals.items():
                if field_data is not None and not field_data.empty:
                    # 跳过没有symbol列的字段（如shibor是日期->利率映射，不是股票级别数据）
                    if 'symbol' not in field_data.columns:
                        continue
                    # 使用最近可用原则：ann_date <= 股价日期，end_date最大，且不超过6个月
                    field_data = self._get_latest_available_financial(
                        field_data, df[['symbol', 'date']], field_name
                    )
                    if not field_data.empty:
                        df = df.merge(
                            field_data[['symbol', 'date', field_name]],
                            on=['symbol', 'date'],
                            how='left'
                        )

        df = df[
            (df['return'].notna()) &
            (df['mkt_cap'].notna()) &
            (df['return'] > -1) &
            (df['return'] < 10)
        ]

        if len(df) < self.min_stocks:
            raise ValueError(f"Insufficient data: {len(df)} < {self.min_stocks}")

        # 根据计算方法选择算法
        if self.method == CalculationMethod.CLASSIC:
            return self._calculate_classic(df, rf_lookup)

        # SIMPLE方法
        if self.factor_type == FactorType.FF3:
            return self._calculate_ff3(df, rf_lookup)
        elif self.factor_type == FactorType.FF5:
            return self._calculate_ff5(df, rf_lookup)
        elif self.factor_type == FactorType.CARHART:
            return self._calculate_carhart(df, rf_lookup)
        elif self.factor_type == FactorType.NOVY_MARX:
            return self._calculate_novymarx(df, rf_lookup)
        elif self.factor_type == FactorType.HOU_XUE_ZHANG:
            return self._calculate_hxz(df, rf_lookup)
        elif self.factor_type == FactorType.DHS:
            return self._calculate_dhs(df, rf_lookup)
        elif self.factor_type == FactorType.CH3:
            return self._calculate_ch3(df, rf_lookup)
        elif self.factor_type == FactorType.SY4:
            return self._calculate_sy4(df, rf_lookup)
        elif self.factor_type == FactorType.REVERSAL:
            return self._calculate_reversal(df, rf_lookup)
        elif self.factor_type == FactorType.LOW_VOL:
            return self._calculate_low_vol(df, rf_lookup)
        else:
            raise NotImplementedError(f"因子类型 {self.factor_type} 未实现")

    def _prepare_risk_free_rate(
        self,
        shibor_data: pd.DataFrame
    ) -> Optional[Dict]:
        """
        准备无风险利率查询字典

        根据当前period将SHIBOR转换为日度或月度无风险利率

        Args:
            shibor_data: SHIBOR数据，包含 date, on_rate, m1_rate 等列

        Returns:
            无风险利率查询字典 {date: rf}，rf为小数形式（如0.03表示3%）
        """
        if shibor_data is None or shibor_data.empty:
            return None

        shibor_data = shibor_data.copy()

        if self.period == TimePeriod.MONTHLY:
            # 月度：使用1个月期SHIBOR，转换为月度利率
            shibor_data['year_month'] = shibor_data['date'].dt.to_period('M')
            shibor_monthly = shibor_data.groupby('year_month').agg({
                'm1_rate': 'last',
                'date': 'last'
            }).reset_index()
            shibor_monthly['rf'] = shibor_monthly['m1_rate'] / 100 / 12
            return dict(zip(pd.to_datetime(shibor_monthly['date']), shibor_monthly['rf']))
        else:
            # 日度：使用隔夜SHIBOR，转换为日度利率
            shibor_data['rf'] = shibor_data['on_rate'] / 100 / 360
            return dict(zip(pd.to_datetime(shibor_data['date']), shibor_data['rf']))

    def _get_latest_available_financial(
        self,
        financial_data: pd.DataFrame,
        stock_dates: pd.DataFrame,
        field_name: str
    ) -> pd.DataFrame:
        """
        ?????????????????

        ?????????+??????????????nd_date <= ?????????????????end_date????????????????nd_date???????????????????
        ?????
        - ?????????end_date????????nn_date(??????)???
        - ????????????????????????????nn_date????????? ann_date <= stock_date ???
        - ann_date????????inancial_data?????????

        Args:
            financial_data: ???????????ymbol, date, ann_date, field_name??
            stock_dates: ??????????????ymbol??ate??
            field_name: ????????
        Returns:
            ????????????
        """
        if financial_data.empty:
            return financial_data

        financial_data = financial_data.copy()
        financial_data['date'] = pd.to_datetime(financial_data['date'])

        stock_dates = stock_dates.copy()
        stock_dates['date'] = pd.to_datetime(stock_dates['date'])
        stock_dates = stock_dates[['symbol', 'date']].drop_duplicates().sort_values(['date', 'symbol'])
        financial_data = financial_data[['symbol', 'date', field_name]].sort_values(['date', 'symbol'])

        matched = pd.merge_asof(
            stock_dates.rename(columns={'date': 'stock_date'}),
            financial_data.rename(columns={'date': 'financial_date'}),
            by='symbol',
            left_on='stock_date',
            right_on='financial_date',
            direction='backward',
            allow_exact_matches=True
        )

        valid = matched['financial_date'].notna()
        if not valid.any():
            return pd.DataFrame()

        months_diff = (
            (matched.loc[valid, 'stock_date'].dt.year - matched.loc[valid, 'financial_date'].dt.year) * 12 +
            (matched.loc[valid, 'stock_date'].dt.month - matched.loc[valid, 'financial_date'].dt.month)
        )
        result = matched.loc[valid].copy()
        result = result.loc[months_diff <= 6, ['symbol', 'stock_date', field_name]]
        if result.empty:
            return pd.DataFrame()

        return result.rename(columns={'stock_date': 'date'})

    def _calculate_ff3(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算FF3因子"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'bm'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'hml': ('high', 'low'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_ff5(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算FF5因子（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'bm', 'op', 'asset_growth'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'hml': ('high', 'low'),
                'rmw': ('high', 'low'),
                'cma': ('low', 'high'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_carhart(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算Carhart四因子（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'bm', 'momentum'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'hml': ('high', 'low'),
                'umd': ('high', 'low'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_novymarx(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算Novy-Marx四因子（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'bm', 'momentum', 'gp_a'],
            factor_def={
                'mkt': ('all', None),
                'hml_adj': ('high', 'low'),
                'umd': ('high', 'low'),
                'gp_a': ('high', 'low'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_hxz(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算Hou-Xue-Zhang四因子（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'asset_growth', 'roe'],
            factor_def={
                'mkt': ('all', None),
                'me': ('low', 'high'),
                'ia': ('low', 'high'),
                'roe': ('high', 'low'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_dhs(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算Daniel-Hirshleifer-Sun三因子（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'pead', 'fin'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'pead': ('high', 'low'),
                'fin': ('low', 'high'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_ch3(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算CH3中国三因子模型（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'bm'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'vmg': ('high', 'low'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_sy4(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算SY4 Stambaugh-Yuan四因子模型（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'mgmt', 'perf'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'mgmt': ('high', 'low'),
                'perf': ('high', 'low'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_reversal(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算REVERSAL短期反转模型（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'rev'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'rev': ('low', 'high'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_low_vol(self, df: pd.DataFrame, rf_lookup: Optional[Dict]) -> pd.DataFrame:
        """计算LOW_VOL低波动模型（简化版：单变量依次排序）"""
        return self._calculate_with_sorting(
            df,
            sort_vars=['mkt_cap', 'ivol'],
            factor_def={
                'mkt': ('all', None),
                'smb': ('low', 'high'),
                'ivol': ('low', 'high'),
            },
            rf_lookup=rf_lookup
        )

    def _calculate_capm_factor(self, market_return: pd.DataFrame) -> pd.DataFrame:
        """
        计算CAPM因子收益率

        CAPM模型：R_i - R_f = alpha + beta * (R_m - R_f) + epsilon
        因子收益率就是市场超额收益率 (R_m - R_f)

        Args:
            market_return: 市场超额收益率数据，包含 date, mkt_return, mkt_excess

        Returns:
            市场超额收益率序列，index为date，column为['mkt']
        """
        if market_return is None or market_return.empty:
            raise ValueError("market_return 不能为空")

        df = market_return[['date', 'mkt_excess']].copy()
        df = df.set_index('date').sort_index()
        df.columns = ['mkt']

        return df

    def _calculate_classic(
        self,
        df: pd.DataFrame,
        rf_lookup: Optional[Dict]
    ) -> pd.DataFrame:
        """
        使用CLASSIC算法计算因子收益率

        参考论文标准方法:
        - 独立排序：每个维度按指定分位数分组
        - 市值加权：组合内按市值加权
        - 多因子模型中，非市值因子的计算取决于模型类型

        Args:
            df: 合并后的数据
            rf_lookup: 无风险利率查询字典

        Returns:
            因子收益率DataFrame
        """
        dates = list(df.groupby('date'))

        # 选择使用Polars还是pandas版本
        calc_func = _calc_single_date_classic_polars if self.use_polars else _calc_single_date_classic

        # 并行计算每个日期的因子收益
        raw_results = Parallel(
            n_jobs=self.n_jobs,
            prefer="threads" if self.use_polars else "processes"
        )(
            delayed(calc_func)(
                date, group, self.factor_type, self.classic_config,
                self.sorting_dims, self.min_stocks, rf_lookup
            )
            for date, group in dates
        )

        results = [r for r in raw_results if r is not None]

        if not results:
            raise ValueError("No valid factor data calculated")

        factor_df = pd.DataFrame(results)
        cols = ['date'] + [f for f in self.factor_names if f in factor_df.columns]
        factor_df = factor_df[[c for c in cols if c in factor_df.columns]]
        factor_df = factor_df.set_index('date').sort_index()

        return factor_df

    def _assign_groups(
        self,
        series: pd.Series,
        breakpoints: List[float]
    ) -> pd.Series:
        """
        根据分位数断点将数据分配到组

        Args:
            series: 要分组的数据
            breakpoints: 分位数列表，如 [0.3, 0.7] 表示按30%和70%分位数分组

        Returns:
            分组标签Series
        """
        # 计算分位数边界
        bounds = [series.quantile(p) for p in breakpoints]
        labels = []
        for val in series:
            if pd.isna(val):
                labels.append('low')  # 缺失值归入最低组
            else:
                assigned = False
                for i, bound in enumerate(bounds):
                    if val <= bound:
                        labels.append('low' if i == 0 else ['medium', 'high'][i-1])
                        assigned = True
                        break
                if not assigned:
                    labels.append('high')
        return pd.Series(labels, index=series.index)

    def _value_weighted_return(
        self,
        group: pd.DataFrame,
        return_col: str = 'return',
        weight_col: str = 'mkt_cap'
    ) -> float:
        """
        计算市值加权收益率

        Args:
            group: 股票组合数据
            return_col: 收益率列名
            weight_col: 市值列名

        Returns:
            市值加权收益率
        """
        valid = group[[return_col, weight_col]].notna().all(axis=1)
        if valid.sum() == 0:
            return np.nan

        w = group.loc[valid, weight_col]
        r = group.loc[valid, return_col]
        # 处理负市值或异常值
        w = w.clip(lower=0)
        if w.sum() == 0:
            return r.mean()
        return (r * w).sum() / w.sum()

    def _calc_ff3_classic(
        self,
        group: pd.DataFrame,
        portfolio_labels: pd.Series
    ) -> Dict[str, float]:
        """
        FF3因子CLASSIC计算

        SMB = (S/L + S/M + S/H)/3 - (B/L + B/M + B/H)/3
        HML = (S/H + B/H)/2 - (S/L + B/L)/2
        """
        factor_def = self.classic_config.get("factor_definition", {})
        size_var = 'mkt_cap'
        value_var = 'bm'

        group['size_g'] = group[size_var].apply(
            lambda x: 'small' if pd.isna(x) or x <= group[size_var].median() else 'big'
        )
        bps = self.classic_config.get("breakpoints", {}).get(value_var, [0.3, 0.7])
        group['value_g'] = self._assign_groups(group[value_var], bps)

        # 计算各组合收益率（市值加权）
        portfolios = group.groupby(['size_g', 'value_g'])

        # SMB: 小市值组合均值 - 大市值组合均值
        small_returns = []
        big_returns = []
        for (size, value), sub in portfolios:
            ret = self._value_weighted_return(sub)
            if size == 'small':
                small_returns.append(ret)
            else:
                big_returns.append(ret)

        smb = np.mean(small_returns) - np.mean(big_returns) if small_returns and big_returns else np.nan

        # HML: 高价值组合均值 - 低价值组合均值
        high_returns = []
        low_returns = []
        for (size, value), sub in portfolios:
            ret = self._value_weighted_return(sub)
            if value == 'high':
                high_returns.append(ret)
            elif value == 'low':
                low_returns.append(ret)

        hml = np.mean(high_returns) - np.mean(low_returns) if high_returns and low_returns else np.nan

        return {'smb': smb, 'hml': hml}

    def _calc_ff5_classic(
        self,
        group: pd.DataFrame,
        portfolio_labels: pd.Series
    ) -> Dict[str, float]:
        """
        FF5因子CLASSIC计算

        使用2x3x3x3独立排序:
        - size: small/big (50% breakpoint)
        - bm: low/medium/high (30%/70% breakpoints)
        - roe: low/medium/high
        - investment: low/medium/high

        SMB = 27个小型组合均值 - 27个大型组合均值
        HML = (小型+大型)高BM组合均值 - (小型+大型)低BM组合均值
        RMW = (小型+大型)高盈利组合均值 - (小型+大型)低盈利组合均值
        CMA = (小型+大型)低投资组合均值 - (小型+大型)高投资组合均值
        """
        bps = self.classic_config.get("breakpoints", {})

        size_var = 'mkt_cap'
        size_bps = bps.get(size_var, [0.5])
        group['size_g'] = self._assign_groups(group[size_var], size_bps)

        for var, var_bps in [('bm', bps.get('bm', [0.3, 0.7])),
                             ('roe', bps.get('roe', [0.3, 0.7])),
                             ('investment', bps.get('investment', [0.3, 0.7]))]:
            if var in group.columns:
                group[f'{var}_g'] = self._assign_groups(group[var], var_bps)

        # 构建8组组合
        def calc_spread(col1_low, col1_high, col2_low, col2_high):
            """计算因子利差"""
            rets = []
            for (s, b, op, inv), sub in group.groupby(['size_g', f'{col1_low}_g' if '_g' not in col1_low else f'{col1_low}_g',
                                                       f'{col2_low}_g' if '_g' not in col2_low else f'{col2_low}_g']):
                pass

            return np.nan

        # 各组合市值加权收益率
        portfolios = group.groupby(['size_g', 'bm_g', 'roe_g', 'investment_g'])
        port_returns = {}
        for combo, sub in portfolios:
            port_returns[combo] = self._value_weighted_return(sub)

        # SMB
        small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

        # HML (基于bm)
        high_rets = [v for k, v in port_returns.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns.items() if k[1] == 'low']
        hml = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan

        # RMW (基于roe)
        robust_rets = [v for k, v in port_returns.items() if k[2] == 'high']
        weak_rets = [v for k, v in port_returns.items() if k[2] == 'low']
        rmw = np.nanmean(robust_rets) - np.nanmean(weak_rets) if robust_rets and weak_rets else np.nan

        # CMA (基于investment，低投资=保守，高投资=激进)
        conservative_rets = [v for k, v in port_returns.items() if k[3] == 'low']
        aggressive_rets = [v for k, v in port_returns.items() if k[3] == 'high']
        cma = np.nanmean(conservative_rets) - np.nanmean(aggressive_rets) if conservative_rets and aggressive_rets else np.nan

        return {'smb': smb, 'hml': hml, 'rmw': rmw, 'cma': cma}

    def _calc_carhart_classic(
        self,
        group: pd.DataFrame,
        portfolio_labels: pd.Series
    ) -> Dict[str, float]:
        """
        CARHART四因子CLASSIC计算

        基于2x3排序:
        - size: small/big
        - bm: low/medium/high
        - momentum: low/medium/high

        UMD (动量因子) = 高动量组合均值 - 低动量组合均值
        """
        bps = self.classic_config.get("breakpoints", {})

        size_var = 'mkt_cap'
        size_bps = bps.get(size_var, [0.5])
        group['size_g'] = self._assign_groups(group[size_var], size_bps)

        for var, var_bps in [('bm', bps.get('bm', [0.3, 0.7])),
                             ('momentum', bps.get('momentum', [0.3, 0.7]))]:
            if var in group.columns:
                group[f'{var}_g'] = self._assign_groups(group[var], var_bps)

        # 各组合市值加权收益率
        portfolios = group.groupby(['size_g', 'bm_g', 'momentum_g'])
        port_returns = {}
        for combo, sub in portfolios:
            port_returns[combo] = self._value_weighted_return(sub)

        # SMB
        small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

        # HML
        high_rets = [v for k, v in port_returns.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns.items() if k[1] == 'low']
        hml = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan

        # UMD (动量)
        up_rets = [v for k, v in port_returns.items() if k[2] == 'high']
        down_rets = [v for k, v in port_returns.items() if k[2] == 'low']
        umd = np.nanmean(up_rets) - np.nanmean(down_rets) if up_rets and down_rets else np.nan

        return {'smb': smb, 'hml': hml, 'umd': umd}

    def _calc_novymarx_classic(
        self,
        group: pd.DataFrame,
        portfolio_labels: pd.Series
    ) -> Dict[str, float]:
        """
        Novy-Marx四因子CLASSIC计算

        基于2x3排序:
        - size: small/big
        - roe: low/medium/high

        RMW = 高盈利组合均值 - 低盈利组合均值
        CMA = 低投资组合均值 - 高投资组合均值 (Novy-Marx用 profitability 和 investment)
        """
        bps = self.classic_config.get("breakpoints", {})

        size_var = 'mkt_cap'
        size_bps = bps.get(size_var, [0.5])
        group['size_g'] = self._assign_groups(group[size_var], size_bps)

        for var, var_bps in [('roe', bps.get('roe', [0.3, 0.7])),
                             ('investment', bps.get('investment', [0.3, 0.7]))]:
            if var in group.columns:
                group[f'{var}_g'] = self._assign_groups(group[var], var_bps)

        # 各组合市值加权收益率
        portfolios = group.groupby(['size_g', 'roe_g', 'investment_g'])
        port_returns = {}
        for combo, sub in portfolios:
            port_returns[combo] = self._value_weighted_return(sub)

        # SMB
        small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

        # RMW (盈利因子)
        robust_rets = [v for k, v in port_returns.items() if k[1] == 'high']
        weak_rets = [v for k, v in port_returns.items() if k[1] == 'low']
        rmw = np.nanmean(robust_rets) - np.nanmean(weak_rets) if robust_rets and weak_rets else np.nan

        # CMA (投资因子)
        conservative_rets = [v for k, v in port_returns.items() if k[2] == 'low']
        aggressive_rets = [v for k, v in port_returns.items() if k[2] == 'high']
        cma = np.nanmean(conservative_rets) - np.nanmean(aggressive_rets) if conservative_rets and aggressive_rets else np.nan

        return {'smb': smb, 'rmw': rmw, 'cma': cma}

    def _calc_hxz_classic(
        self,
        group: pd.DataFrame,
        portfolio_labels: pd.Series
    ) -> Dict[str, float]:
        """
        Hou-Xue-Zhang四因子CLASSIC计算

        基于2x3排序:
        - size: small/big
        - investment: low/medium/high

        ME = size因子
        IA = 投资因子 (conservative - aggressive)
        ROE = 盈利因子
        """
        bps = self.classic_config.get("breakpoints", {})

        size_var = 'mkt_cap'
        size_bps = bps.get(size_var, [0.5])
        group['size_g'] = self._assign_groups(group[size_var], size_bps)

        for var, var_bps in [('investment', bps.get('investment', [0.3, 0.7])),
                             ('roe', bps.get('roe', [0.3, 0.7]))]:
            if var in group.columns:
                group[f'{var}_g'] = self._assign_groups(group[var], var_bps)

        # 各组合市值加权收益率
        portfolios = group.groupby(['size_g', 'investment_g', 'roe_g'])
        port_returns = {}
        for combo, sub in portfolios:
            port_returns[combo] = self._value_weighted_return(sub)

        # ME (size因子，等同SMB)
        small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
        me = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

        # IA (投资因子)
        conservative_rets = [v for k, v in port_returns.items() if k[1] == 'low']
        aggressive_rets = [v for k, v in port_returns.items() if k[1] == 'high']
        ia = np.nanmean(conservative_rets) - np.nanmean(aggressive_rets) if conservative_rets and aggressive_rets else np.nan

        # ROE (盈利因子)
        high_rets = [v for k, v in port_returns.items() if k[2] == 'high']
        low_rets = [v for k, v in port_returns.items() if k[2] == 'low']
        roe_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan

        return {'me': me, 'ia': ia, 'roe': roe_factor}

    def _calc_dhs_classic(
        self,
        group: pd.DataFrame,
        portfolio_labels: pd.Series
    ) -> Dict[str, float]:
        """
        DHS三因子CLASSIC计算

        基于2x3排序:
        - size: small/big
        - idio_vol: low/medium/high

        IDIO_VOL = 高特质波动率组合均值 - 低特质波动率组合均值
        """
        bps = self.classic_config.get("breakpoints", {})

        size_var = 'mkt_cap'
        size_bps = bps.get(size_var, [0.5])
        group['size_g'] = self._assign_groups(group[size_var], size_bps)

        idio_var = 'idio_vol'
        idio_bps = bps.get(idio_var, [0.3, 0.7])
        if idio_var in group.columns:
            group['idio_vol_g'] = self._assign_groups(group[idio_var], idio_bps)

        # 各组合市值加权收益率
        portfolios = group.groupby(['size_g', 'idio_vol_g'])
        port_returns = {}
        for combo, sub in portfolios:
            port_returns[combo] = self._value_weighted_return(sub)

        # SMB
        small_rets = [v for k, v in port_returns.items() if k[0] == 'small']
        big_rets = [v for k, v in port_returns.items() if k[0] == 'big']
        smb = np.nanmean(small_rets) - np.nanmean(big_rets) if small_rets and big_rets else np.nan

        # IDIO_VOL
        high_rets = [v for k, v in port_returns.items() if k[1] == 'high']
        low_rets = [v for k, v in port_returns.items() if k[1] == 'low']
        idio_vol_factor = np.nanmean(high_rets) - np.nanmean(low_rets) if high_rets and low_rets else np.nan

        return {'smb': smb, 'idio_vol': idio_vol_factor}

    def _calculate_with_sorting(
        self,
        df: pd.DataFrame,
        sort_vars: List[str],
        factor_def: Dict[str, tuple],
        rf_lookup: Optional[Dict] = None
    ) -> pd.DataFrame:
        """
        使用排序法计算因子

        Args:
            df: 合并后的数据
            sort_vars: 排序变量
            factor_def: 因子定义 {因子名: (多头组, 空头组)}
            rf_lookup: 无风险利率查询字典 {date: rf}

        Returns:
            因子收益率
        """
        dates = list(df.groupby('date'))

        # 选择使用Polars还是pandas版本
        calc_func = _calc_single_date_sorting_polars if self.use_polars else _calc_single_date_sorting

        # 并行计算每个日期的因子收益
        raw_results = Parallel(
            n_jobs=self.n_jobs,
            prefer="threads" if self.use_polars else "processes"
        )(
            delayed(calc_func)(
                date, group, sort_vars, factor_def, rf_lookup, self.min_stocks
            )
            for date, group in dates
        )

        results = [r for r in raw_results if r is not None]

        if not results:
            raise ValueError("No valid factor data calculated")

        factor_df = pd.DataFrame(results)

        cols = ['date'] + [f for f in self.factor_names if f in factor_df.columns]
        factor_df = factor_df[[c for c in cols if c in factor_df.columns]]

        factor_df = factor_df.set_index('date').sort_index()

        return factor_df
