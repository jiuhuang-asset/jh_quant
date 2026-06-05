from __future__ import annotations

from typing import Any

import pandas as pd

from jh_quant.schemas.factors import ANN_DATE_COL, FINANCIAL_FACTOR_FIELDS

DEFAULT_TS_SYMBOLS = [
    "600135.SH",
    "000001.SZ",
    "600036.SH",
    "600519.SH",
    "000858.SZ",
    "601318.SH",
    "000002.SZ",
    "600030.SH",
    "600000.SH",
    "600016.SH",
    "600048.SH",
    "600887.SH",
    "601166.SH",
    "601601.SH",
    "601628.SH",
    "601857.SH",
    "601939.SH",
    "601988.SH",
    "000063.SZ",
    "000333.SZ",
    "000425.SZ",
    "000568.SZ",
    "000651.SZ",
    "000725.SZ",
    "000776.SZ",
    "000895.SZ",
    "002027.SZ",
    "002142.SZ",
    "002230.SZ",
    "002415.SZ",
]


def month_end_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"])
    result["year_month"] = result["date"].dt.to_period("M")
    result = (
        result.sort_values(["symbol", "date"])
        .groupby(["symbol", "year_month"], as_index=False)
        .tail(1)
        .drop(columns=["year_month"])
    )
    return result.reset_index(drop=True)


def _to_df(data: Any) -> pd.DataFrame:
    return data.to_df() if hasattr(data, "to_df") else data


def _monthly_returns_from_ts_prices(
    prices,
    *,
    already_monthly: bool = False,
) -> pd.DataFrame:
    from jh_quant.data import to_factor_stock_returns_frame

    price_df = _to_df(prices).copy().rename(
        columns={"ts_code": "symbol", "trade_date": "date"}
    )
    if not already_monthly:
        price_df = month_end_rows(price_df)
        price_df = price_df.drop(columns=["pct_chg"], errors="ignore")
    return to_factor_stock_returns_frame(price_df).dropna(subset=["return"])


def _ts_price_data_type(DataTypes, *, period: str, price_adjust: str):
    period_key = period.upper()
    adjust_key = price_adjust.lower()

    if period_key in {"M", "MONTH", "MONTHLY"}:
        if adjust_key == "qfq":
            return DataTypes.TS_MONTHLY_QFQ, True
        if adjust_key == "hfq":
            return DataTypes.TS_MONTHLY_HFQ, True
        if adjust_key in {"none", "raw", "bfq"}:
            return DataTypes.TS_MONTHLY, True
    elif period_key in {"D", "DAY", "DAILY"}:
        if adjust_key == "qfq":
            return DataTypes.TS_DAILY_QFQ, False
        if adjust_key == "hfq":
            return DataTypes.TS_DAILY_HFQ, False
        if adjust_key in {"none", "raw", "bfq"}:
            return DataTypes.TS_DAILY, False

    raise ValueError(
        "Unsupported TS price frequency/adjustment: "
        f"period={period!r}, price_adjust={price_adjust!r}"
    )


def _market_return_from_stock_returns(stock_returns: pd.DataFrame) -> pd.DataFrame:
    return (
        stock_returns.groupby("date", as_index=False)["return"]
        .mean()
        .rename(columns={"return": "mkt_excess"})
    )


def _align_features_to_next_return_date(
    features: pd.DataFrame,
    stock_returns: pd.DataFrame,
) -> pd.DataFrame:
    """Use features observed at t for the next available return date."""
    if features.empty:
        return features

    result = features.copy()
    result["date"] = pd.to_datetime(result["date"])

    targets = stock_returns[["symbol", "date"]].copy()
    targets["date"] = pd.to_datetime(targets["date"])
    targets = targets.drop_duplicates().sort_values(["symbol", "date"])

    shifted_parts = []
    for symbol, grp in result.sort_values(["symbol", "date"]).groupby(
        "symbol", sort=False
    ):
        symbol_targets = targets.loc[targets["symbol"] == symbol, "date"]
        if symbol_targets.empty:
            continue
        target_dates = symbol_targets.to_numpy()
        positions = target_dates.searchsorted(grp["date"].to_numpy(), side="right")
        valid = positions < len(target_dates)
        if not valid.any():
            continue
        shifted = grp.loc[valid].copy()
        shifted["date"] = target_dates[positions[valid]]
        shifted_parts.append(shifted)

    if not shifted_parts:
        return result.iloc[0:0].copy()

    return (
        pd.concat(shifted_parts, ignore_index=True)
        .sort_values(["symbol", "date"])
        .drop_duplicates(["symbol", "date"], keep="last")
        .reset_index(drop=True)
    )


def _align_fundamentals_to_next_return_date(
    fundamentals: dict[str, pd.DataFrame],
    stock_returns: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    result = {}
    for field, frame in fundamentals.items():
        if field in FINANCIAL_FACTOR_FIELDS or ANN_DATE_COL in frame.columns:
            result[field] = frame.copy()
        else:
            result[field] = _align_features_to_next_return_date(frame, stock_returns)
    return result


def _build_price_fields(
    base: pd.DataFrame,
    stock_returns: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    df = base.copy()
    df["date"] = pd.to_datetime(df["date"])
    df[ANN_DATE_COL] = df["date"]
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    returns = stock_returns[["symbol", "date", "return"]].copy()
    returns["date"] = pd.to_datetime(returns["date"])
    df = df.merge(returns, on=["symbol", "date"], how="left")
    df["return"] = pd.to_numeric(df["return"], errors="coerce")

    df["momentum"] = df.groupby("symbol")["close"].pct_change(3)
    df["daily_return"] = df["return"].fillna(df.groupby("symbol")["close"].pct_change())
    df["rev"] = -df["daily_return"]
    df["ivol"] = (
        df.groupby("symbol")["daily_return"]
        .transform(lambda s: s.rolling(6, min_periods=2).std())
        .fillna(df["daily_return"].abs())
    )

    return {
        field: df[["symbol", "date", field]].copy()
        for field in ["close", "momentum", "daily_return", "rev", "ivol"]
    }


def _build_proxy_fundamentals(
    base: pd.DataFrame,
    stock_returns: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    df = base.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["mkt_cap"] = pd.to_numeric(df["mkt_cap"], errors="coerce")
    df["bm"] = pd.to_numeric(df["bm"], errors="coerce")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    returns = stock_returns[["symbol", "date", "return"]].copy()
    returns["date"] = pd.to_datetime(returns["date"])
    df = df.merge(returns, on=["symbol", "date"], how="left")
    df["return"] = pd.to_numeric(df["return"], errors="coerce")

    symbol_code = df["symbol"].astype(str).str.extract(r"(\d+)")[0].fillna("0")
    symbol_num = pd.to_numeric(symbol_code, errors="coerce").fillna(0)
    symbol_bucket = (symbol_num % 11) / 100

    df["daily_return"] = df["return"].fillna(df.groupby("symbol")["close"].pct_change())
    df["asset_growth"] = df.groupby("symbol")["mkt_cap"].pct_change().fillna(0)
    df["op"] = (df["bm"].rank(pct=True) + symbol_bucket).astype(float)
    df["gp_a"] = (df["op"] - df["asset_growth"]).astype(float)
    df["gross_profit"] = df["gp_a"]
    df["roe"] = (df["op"] / (df["bm"].abs() + 1)).astype(float)
    df["roe_quarterly"] = df["roe"]
    df["pead"] = df["daily_return"].fillna(0)
    df["sud"] = df["pead"]
    df["fin"] = -df["asset_growth"]
    df["net_share_issuance"] = df["fin"]
    df["is_st"] = 0.0
    df["operating_accruals"] = df["asset_growth"] - df["op"]
    df["mgmt"] = -df["operating_accruals"]
    df["momentum"] = df.groupby("symbol")["close"].pct_change(3)
    df["perf"] = df["roe"] + df["momentum"].fillna(0)
    df["industry"] = (symbol_num % 5).astype(float)

    fields = [
        "op",
        "asset_growth",
        "gp_a",
        "gross_profit",
        "industry",
        "roe",
        "roe_quarterly",
        "pead",
        "sud",
        "fin",
        "net_share_issuance",
        "is_st",
        "operating_accruals",
        "mgmt",
        "perf",
    ]
    return {
        field: df[
            ["symbol", "date", ANN_DATE_COL, field]
            if field in FINANCIAL_FACTOR_FIELDS
            else ["symbol", "date", field]
        ].copy()
        for field in fields
        if field in df.columns
    }


def load_ts_factor_inputs(
    *,
    start_date: str = "2015-01-01",
    end_date: str = "2026-03-31",
    symbols: list[str] | None = None,
    period: str = "M",
    price_adjust: str = "qfq",
    lag_features: bool = True,
    include_proxy_fundamentals: bool = False,
) -> dict[str, pd.DataFrame | dict[str, pd.DataFrame]]:
    """
    Load TS-backed factor inputs and normalize them to factor schemas.

    ``period="M"`` uses TS_MONTHLY_* price data directly. ``period="D"`` uses
    TS_DAILY_* price data and converts it to month-end returns.
    ``lag_features=True`` aligns market cap and characteristic fields observed
    at t to the next return period, avoiding same-period look-ahead.

    This helper imports ``jh_quant.data`` inside the function so the factor core
    remains usable without the data module. It returns keyword arguments that can
    be passed directly to ``calculate_factor_returns``.
    """
    from jh_quant.data import (
        DataTypes,
        JHData,
        to_factor_input_frame,
        to_factor_market_cap_frame,
    )

    jhd = JHData()
    symbols = symbols or DEFAULT_TS_SYMBOLS
    ts_codes = ",".join(symbols)
    price_data_type, already_monthly = _ts_price_data_type(
        DataTypes,
        period=period,
        price_adjust=price_adjust,
    )

    prices = jhd.get_data(
        price_data_type,
        start=start_date,
        end=end_date,
        ts_code=ts_codes,
    )
    stock_returns = _monthly_returns_from_ts_prices(
        prices,
        already_monthly=already_monthly,
    )

    daily_basic = jhd.get_data(
        DataTypes.TS_DAILY_BASIC,
        start=start_date,
        end=end_date,
        ts_code=ts_codes,
    )
    market_cap = month_end_rows(to_factor_market_cap_frame(daily_basic))
    if lag_features:
        market_cap = _align_features_to_next_return_date(market_cap, stock_returns)

    basic_df = _to_df(daily_basic).copy().rename(
        columns={"ts_code": "symbol", "trade_date": "date"}
    )
    pb = pd.to_numeric(basic_df["pb"], errors="coerce")
    basic_df["bm"] = 1 / pb.where(pb > 0)
    bm = month_end_rows(to_factor_input_frame(basic_df, field_name="bm"))

    price_df = _to_df(prices).copy().rename(
        columns={"ts_code": "symbol", "trade_date": "date"}
    )
    price_monthly = price_df if already_monthly else month_end_rows(price_df)

    fundamentals: dict[str, pd.DataFrame] = {"bm": bm}
    fundamentals.update(_build_price_fields(price_monthly, stock_returns))

    if include_proxy_fundamentals:
        basic_monthly = month_end_rows(basic_df)
        basic_monthly["mkt_cap"] = pd.to_numeric(
            basic_monthly["total_mv"], errors="coerce"
        )
        proxy_base = (
            price_monthly[["symbol", "date", "close"]]
            .merge(
                basic_monthly[["symbol", "date", "mkt_cap", "bm"]],
                on=["symbol", "date"],
                how="left",
            )
            .dropna(subset=["mkt_cap", "bm"])
        )
        fundamentals.update(_build_proxy_fundamentals(proxy_base, stock_returns))

    if lag_features:
        fundamentals = _align_fundamentals_to_next_return_date(
            fundamentals,
            stock_returns,
        )

    return {
        "stock_returns": stock_returns,
        "market_cap": market_cap,
        "fundamentals": fundamentals,
        "market_return": _market_return_from_stock_returns(stock_returns),
    }
