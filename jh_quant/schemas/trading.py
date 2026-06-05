from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .market import DATE_COL, SYMBOL_COL

TRADING_PRICE_REQUIRED_COLUMNS = [
    SYMBOL_COL,
    DATE_COL,
    "open",
    "high",
    "low",
    "close",
]
TRADING_PRICE_NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "price",
    "pct_chg",
    "chg",
    "turnover_rate",
    "amplitude",
]
TRADING_PRICE_COLUMNS = [
    *TRADING_PRICE_REQUIRED_COLUMNS,
    "volume",
    "amount",
    "price",
]


def normalize_trading_symbol(value) -> str:
    """Normalize A-share symbols for trading execution and broker calls."""
    text = str(value).strip()
    if not text:
        return text
    return text.split(".")[0]


def validate_trading_price_frame(
    price: pd.DataFrame,
    *,
    required_columns: Iterable[str] = TRADING_PRICE_REQUIRED_COLUMNS,
) -> None:
    if not isinstance(price, pd.DataFrame):
        raise TypeError("price_data must be a pandas DataFrame")

    missing = [col for col in required_columns if col not in price.columns]
    if missing:
        raise ValueError(
            "price_data is missing required trading columns: " + ", ".join(missing)
        )


def normalize_trading_price_frame(price: pd.DataFrame) -> pd.DataFrame:
    """Validate, coerce, and sort a DataFrame that uses trading price columns."""
    if isinstance(price, pd.DataFrame) and price.empty:
        result = price.copy()
        for col in TRADING_PRICE_COLUMNS:
            if col not in result.columns:
                result[col] = pd.Series(dtype="float64")
        return result

    validate_trading_price_frame(price)
    result = price.copy()

    result[SYMBOL_COL] = result[SYMBOL_COL].map(normalize_trading_symbol)
    result[DATE_COL] = pd.to_datetime(result[DATE_COL], errors="coerce")

    for col in TRADING_PRICE_NUMERIC_COLUMNS:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    if "price" not in result.columns:
        result["price"] = result["close"]
    elif result["price"].isna().any():
        result["price"] = result["price"].fillna(result["close"])

    result = result.dropna(subset=[SYMBOL_COL, DATE_COL, "close"])
    leading = [col for col in TRADING_PRICE_COLUMNS if col in result.columns]
    trailing = [col for col in result.columns if col not in leading]
    return (
        result[leading + trailing]
        .sort_values([SYMBOL_COL, DATE_COL])
        .reset_index(drop=True)
    )
