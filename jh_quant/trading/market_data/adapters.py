from __future__ import annotations

import pandas as pd

from jh_quant.schemas.trading import (
    TRADING_PRICE_REQUIRED_COLUMNS,
    normalize_trading_price_frame,
)


TRADING_PRICE_RENAME_MAP = {
    "ts_code": "symbol",
    "trade_date": "date",
    "datetime": "date",
    "dt": "date",
    "code": "symbol",
    "sec_code": "symbol",
    "vol": "volume",
    "latest": "close",
    "last_price": "close",
    "change": "chg",
}


def to_trading_price_frame(data) -> pd.DataFrame:
    """Convert provider-specific market data to the trading price schema."""
    if data is None:
        return pd.DataFrame(columns=TRADING_PRICE_REQUIRED_COLUMNS)

    if hasattr(data, "to_df"):
        data = data.to_df()
    if not isinstance(data, pd.DataFrame):
        raise TypeError("market data provider must return a pandas DataFrame")

    if data.empty and len(data.columns) == 0:
        return pd.DataFrame(columns=TRADING_PRICE_REQUIRED_COLUMNS)

    result = data.copy()
    rename = {
        source: target
        for source, target in TRADING_PRICE_RENAME_MAP.items()
        if source in result.columns and target not in result.columns
    }
    if rename:
        result = result.rename(columns=rename)

    if "price" not in result.columns and "close" in result.columns:
        result["price"] = result["close"]

    return normalize_trading_price_frame(result)


__all__ = ["to_trading_price_frame"]
