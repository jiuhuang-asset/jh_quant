from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

SYMBOL_COL = "symbol"
DATE_COL = "date"
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
BACKTEST_PRICE_COLUMNS = [SYMBOL_COL, DATE_COL, *OHLCV_COLUMNS]


def validate_backtest_price_frame(
    price: pd.DataFrame,
    *,
    required_columns: Iterable[str] = BACKTEST_PRICE_COLUMNS,
) -> None:
    """Validate the normalized price schema required by backtest."""
    if not isinstance(price, pd.DataFrame):
        raise TypeError("price_data must be a pandas DataFrame")

    missing = [col for col in required_columns if col not in price.columns]
    if missing:
        raise ValueError(
            "price_data is missing required backtest columns: "
            + ", ".join(missing)
        )


def normalize_backtest_price_frame(price: pd.DataFrame) -> pd.DataFrame:
    """Validate and sort a DataFrame that already uses the backtest schema."""
    validate_backtest_price_frame(price)
    result = price.copy()
    result[DATE_COL] = pd.to_datetime(result[DATE_COL])

    for col in OHLCV_COLUMNS:
        result[col] = pd.to_numeric(result[col], errors="coerce")

    return result.sort_values([SYMBOL_COL, DATE_COL]).reset_index(drop=True)
