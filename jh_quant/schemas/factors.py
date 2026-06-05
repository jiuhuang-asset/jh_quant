from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

import pandas as pd

from .market import DATE_COL, SYMBOL_COL

RETURN_COL = "return"
MARKET_CAP_COL = "mkt_cap"
MARKET_EXCESS_COL = "mkt_excess"
RISK_FREE_RATE_COL = "rf"
ANN_DATE_COL = "ann_date"

FACTOR_STOCK_RETURNS_COLUMNS = [SYMBOL_COL, DATE_COL, RETURN_COL]
FACTOR_MARKET_CAP_COLUMNS = [SYMBOL_COL, DATE_COL, MARKET_CAP_COL]
FACTOR_MARKET_RETURN_COLUMNS = [DATE_COL, MARKET_EXCESS_COL]
FACTOR_RISK_FREE_RATE_COLUMNS = [DATE_COL, RISK_FREE_RATE_COL]

FINANCIAL_FACTOR_FIELDS = {
    "op",
    "asset_growth",
    "gp_a",
    "gross_profit",
    "roe",
    "roe_quarterly",
    "pead",
    "sud",
    "fin",
    "net_share_issuance",
    "operating_accruals",
    "mgmt",
    "perf",
}


def _validate_frame(
    frame: pd.DataFrame,
    *,
    frame_name: str,
    required_columns: Iterable[str],
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{frame_name} must be a pandas DataFrame")

    missing = [col for col in required_columns if col not in frame.columns]
    if missing:
        raise ValueError(
            f"{frame_name} is missing required factor columns: "
            + ", ".join(missing)
        )


def validate_factor_stock_returns_frame(stock_returns: pd.DataFrame) -> None:
    _validate_frame(
        stock_returns,
        frame_name="stock_returns",
        required_columns=FACTOR_STOCK_RETURNS_COLUMNS,
    )


def normalize_factor_stock_returns_frame(stock_returns: pd.DataFrame) -> pd.DataFrame:
    validate_factor_stock_returns_frame(stock_returns)
    result = stock_returns.copy()
    result[DATE_COL] = pd.to_datetime(result[DATE_COL])
    result[RETURN_COL] = pd.to_numeric(result[RETURN_COL], errors="coerce")
    return result.sort_values([SYMBOL_COL, DATE_COL]).reset_index(drop=True)


def validate_factor_market_cap_frame(market_cap: pd.DataFrame) -> None:
    _validate_frame(
        market_cap,
        frame_name="market_cap",
        required_columns=FACTOR_MARKET_CAP_COLUMNS,
    )


def normalize_factor_market_cap_frame(market_cap: pd.DataFrame) -> pd.DataFrame:
    validate_factor_market_cap_frame(market_cap)
    result = market_cap.copy()
    result[DATE_COL] = pd.to_datetime(result[DATE_COL])
    result[MARKET_CAP_COL] = pd.to_numeric(result[MARKET_CAP_COL], errors="coerce")
    return result.sort_values([SYMBOL_COL, DATE_COL]).reset_index(drop=True)


def validate_factor_market_return_frame(market_return: pd.DataFrame) -> None:
    _validate_frame(
        market_return,
        frame_name="market_return",
        required_columns=FACTOR_MARKET_RETURN_COLUMNS,
    )


def normalize_factor_market_return_frame(market_return: pd.DataFrame) -> pd.DataFrame:
    validate_factor_market_return_frame(market_return)
    result = market_return.copy()
    result[DATE_COL] = pd.to_datetime(result[DATE_COL])
    result[MARKET_EXCESS_COL] = pd.to_numeric(
        result[MARKET_EXCESS_COL], errors="coerce"
    )
    return result.sort_values(DATE_COL).reset_index(drop=True)


def normalize_factor_returns_frame(factor_returns: pd.DataFrame) -> pd.DataFrame:
    """Normalize calculated factor returns to a DatetimeIndex and numeric columns."""
    if not isinstance(factor_returns, pd.DataFrame):
        raise TypeError("factor_returns must be a pandas DataFrame")

    result = factor_returns.copy()
    if DATE_COL in result.columns:
        result[DATE_COL] = pd.to_datetime(result[DATE_COL])
        result = result.set_index(DATE_COL)
    elif not isinstance(result.index, pd.DatetimeIndex):
        raise ValueError("factor_returns must have a date column or DatetimeIndex")

    result.index = pd.to_datetime(result.index)
    for col in result.columns:
        result[col] = pd.to_numeric(result[col], errors="coerce")
    return result.sort_index()


def normalize_factor_input_frame(
    frame: pd.DataFrame,
    *,
    frame_name: str,
    required_columns: Iterable[str],
    numeric_columns: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Normalize a generic factor input frame that already uses canonical names."""
    _validate_frame(frame, frame_name=frame_name, required_columns=required_columns)
    result = frame.copy()
    if DATE_COL in result.columns:
        result[DATE_COL] = pd.to_datetime(result[DATE_COL])
    if ANN_DATE_COL in result.columns:
        result[ANN_DATE_COL] = pd.to_datetime(result[ANN_DATE_COL])
    for col in numeric_columns or []:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    sort_cols = [col for col in [SYMBOL_COL, DATE_COL] if col in result.columns]
    if sort_cols:
        result = result.sort_values(sort_cols).reset_index(drop=True)
    return result


def normalize_factor_fundamentals(
    fundamentals: Optional[Mapping[str, pd.DataFrame]],
) -> dict[str, pd.DataFrame]:
    """Normalize factor-specific input frames keyed by their canonical field name."""
    if fundamentals is None:
        return {}

    result: dict[str, pd.DataFrame] = {}
    for field_name, frame in fundamentals.items():
        if frame is None:
            continue
        if SYMBOL_COL in frame.columns:
            required = [SYMBOL_COL, DATE_COL, field_name]
            if field_name in FINANCIAL_FACTOR_FIELDS:
                required.append(ANN_DATE_COL)
        else:
            required = [DATE_COL]
        numeric = [field_name] if field_name in frame.columns else None
        result[field_name] = normalize_factor_input_frame(
            frame,
            frame_name=f"fundamentals[{field_name}]",
            required_columns=required,
            numeric_columns=numeric,
        )
    return result


def normalize_factor_risk_free_rate_frame(
    risk_free_rate: Optional[pd.DataFrame],
) -> Optional[pd.DataFrame]:
    if risk_free_rate is None:
        return None
    return normalize_factor_input_frame(
        risk_free_rate,
        frame_name="risk_free_rate",
        required_columns=FACTOR_RISK_FREE_RATE_COLUMNS,
        numeric_columns=[RISK_FREE_RATE_COL],
    )
