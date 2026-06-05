from __future__ import annotations

import pandas as pd

from jh_quant.schemas.factors import (
    ANN_DATE_COL,
    FACTOR_MARKET_CAP_COLUMNS,
    FACTOR_MARKET_RETURN_COLUMNS,
    FACTOR_RISK_FREE_RATE_COLUMNS,
    FACTOR_STOCK_RETURNS_COLUMNS,
    FINANCIAL_FACTOR_FIELDS,
    MARKET_CAP_COL,
    MARKET_EXCESS_COL,
    RETURN_COL,
    RISK_FREE_RATE_COL,
    normalize_factor_input_frame,
    normalize_factor_market_cap_frame,
    normalize_factor_market_return_frame,
    normalize_factor_risk_free_rate_frame,
    normalize_factor_stock_returns_frame,
)
from jh_quant.schemas.market import (
    BACKTEST_PRICE_COLUMNS,
    DATE_COL,
    SYMBOL_COL,
    normalize_backtest_price_frame,
)

_BACKTEST_PRICE_RENAME_MAP = {
    "ts_code": SYMBOL_COL,
    "trade_date": DATE_COL,
    "dt": DATE_COL,
    "datetime": DATE_COL,
    "vol": "volume",
}

_COMMON_RENAME_MAP = {
    "ts_code": SYMBOL_COL,
    "trade_date": DATE_COL,
    "end_date": DATE_COL,
    "report_date": DATE_COL,
    "f_ann_date": ANN_DATE_COL,
    "announcement_date": ANN_DATE_COL,
    "dt": DATE_COL,
    "datetime": DATE_COL,
}

_STOCK_RETURN_RENAME_MAP = {
    **_COMMON_RENAME_MAP,
    "ret": RETURN_COL,
    "returns": RETURN_COL,
}

_MARKET_CAP_RENAME_MAP = {
    **_COMMON_RENAME_MAP,
    "market_cap": MARKET_CAP_COL,
}

_MARKET_RETURN_RENAME_MAP = {
    **_COMMON_RENAME_MAP,
    "mkt_return": MARKET_EXCESS_COL,
    "market_return": MARKET_EXCESS_COL,
}

_RISK_FREE_RATE_RENAME_MAP = {
    **_COMMON_RENAME_MAP,
    "risk_free_rate": RISK_FREE_RATE_COL,
}


def _to_frame(data, *, arg_name: str = "data") -> pd.DataFrame:
    df = data.to_df() if hasattr(data, "to_df") else data
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"{arg_name} must be a pandas DataFrame or JhDataType-like wrapper")
    return df.copy()


def _ensure_empty_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        for col in columns:
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
    return df


def to_backtest_price_frame(data) -> pd.DataFrame:
    """Convert supported market data outputs to the backtest price schema."""
    result = _to_frame(data).rename(columns=_BACKTEST_PRICE_RENAME_MAP)
    result = _ensure_empty_columns(result, BACKTEST_PRICE_COLUMNS)

    result = normalize_backtest_price_frame(result)

    ordered_columns = [
        *BACKTEST_PRICE_COLUMNS,
        *[col for col in result.columns if col not in BACKTEST_PRICE_COLUMNS],
    ]
    return result[ordered_columns]


def to_factor_stock_returns_frame(data, *, price_col: str = "close") -> pd.DataFrame:
    """Convert source returns or prices to [symbol, date, return]."""
    result = _to_frame(data).rename(columns=_STOCK_RETURN_RENAME_MAP)

    if RETURN_COL not in result.columns and "pct_chg" in result.columns:
        result[RETURN_COL] = pd.to_numeric(result["pct_chg"], errors="coerce") / 100

    if RETURN_COL not in result.columns and price_col in result.columns:
        result[DATE_COL] = pd.to_datetime(result[DATE_COL])
        result[price_col] = pd.to_numeric(result[price_col], errors="coerce")
        result = result.sort_values([SYMBOL_COL, DATE_COL])
        result[RETURN_COL] = result.groupby(SYMBOL_COL)[price_col].pct_change()

    result = _ensure_empty_columns(result, FACTOR_STOCK_RETURNS_COLUMNS)
    result = normalize_factor_stock_returns_frame(result)

    ordered_columns = [
        *FACTOR_STOCK_RETURNS_COLUMNS,
        *[col for col in result.columns if col not in FACTOR_STOCK_RETURNS_COLUMNS],
    ]
    return result[ordered_columns]


def to_factor_market_cap_frame(data) -> pd.DataFrame:
    """Convert source market-cap data to [symbol, date, mkt_cap]."""
    result = _to_frame(data).rename(columns=_MARKET_CAP_RENAME_MAP)
    if MARKET_CAP_COL not in result.columns:
        if "total_mv" in result.columns:
            result[MARKET_CAP_COL] = result["total_mv"]
        elif "circ_mv" in result.columns:
            result[MARKET_CAP_COL] = result["circ_mv"]
    result = _ensure_empty_columns(result, FACTOR_MARKET_CAP_COLUMNS)
    result = normalize_factor_market_cap_frame(result)

    ordered_columns = [
        *FACTOR_MARKET_CAP_COLUMNS,
        *[col for col in result.columns if col not in FACTOR_MARKET_CAP_COLUMNS],
    ]
    return result[ordered_columns]


def to_factor_market_return_frame(data) -> pd.DataFrame:
    """Convert source market return data to [date, mkt_excess]."""
    result = _to_frame(data).rename(columns=_MARKET_RETURN_RENAME_MAP)
    result = _ensure_empty_columns(result, FACTOR_MARKET_RETURN_COLUMNS)
    result = normalize_factor_market_return_frame(result)

    ordered_columns = [
        *FACTOR_MARKET_RETURN_COLUMNS,
        *[col for col in result.columns if col not in FACTOR_MARKET_RETURN_COLUMNS],
    ]
    return result[ordered_columns]


def to_factor_risk_free_rate_frame(data) -> pd.DataFrame:
    """Convert source risk-free-rate data to [date, rf]."""
    result = _to_frame(data).rename(columns=_RISK_FREE_RATE_RENAME_MAP)
    result = _ensure_empty_columns(result, FACTOR_RISK_FREE_RATE_COLUMNS)
    result = normalize_factor_risk_free_rate_frame(result)
    if result is None:
        return pd.DataFrame(columns=FACTOR_RISK_FREE_RATE_COLUMNS)

    ordered_columns = [
        *FACTOR_RISK_FREE_RATE_COLUMNS,
        *[col for col in result.columns if col not in FACTOR_RISK_FREE_RATE_COLUMNS],
    ]
    return result[ordered_columns]


def to_factor_input_frame(
    data,
    *,
    field_name: str,
    column_map: dict[str, str] | None = None,
    require_symbol: bool = True,
) -> pd.DataFrame:
    """Convert a factor-specific input frame to canonical column names."""
    rename_map = {**_COMMON_RENAME_MAP, **(column_map or {})}
    result = _to_frame(data).rename(columns=rename_map)
    required = [DATE_COL, field_name]
    if require_symbol:
        required.insert(0, SYMBOL_COL)
    if field_name in FINANCIAL_FACTOR_FIELDS:
        required.append(ANN_DATE_COL)

    result = _ensure_empty_columns(result, required)
    return normalize_factor_input_frame(
        result,
        frame_name=field_name,
        required_columns=required,
        numeric_columns=[field_name],
    )
