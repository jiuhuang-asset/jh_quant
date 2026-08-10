from __future__ import annotations

from typing import Any

import pandas as pd

from jh_quant.schemas.factors import ANN_DATE_COL, FINANCIAL_FACTOR_FIELDS


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


def _fetch_basic_monthly(
    jhd,
    *,
    period: str,
    start_date: str,
    end_date: str,
    ts_codes: str | None,
) -> pd.DataFrame:
    """Fetch basic metrics reduced to one row per symbol-month.

    period="M" prefers the server-side ts_monthly_basic (one row per symbol-month,
    trade_date = last trading day of the month, same convention as the TS_MONTHLY
    price tables) and falls back to ts_daily_basic reduced locally when the
    monthly table is missing or empty. period="D" always uses ts_daily_basic
    reduced locally.

    ``ts_codes`` may be None to request all stocks (ts_code is then omitted
    from the request, since an empty string is rejected by the server).

    Returns a canonical [symbol, date, ...] frame carrying the basic fields.
    """
    from rich import print as rprint

    from jh_quant.data import DataTypes

    is_monthly = period.upper() in {"M", "MONTH", "MONTHLY"}
    candidates = (
        [DataTypes.TS_MONTHLY_BASIC, DataTypes.TS_DAILY_BASIC]
        if is_monthly
        else [DataTypes.TS_DAILY_BASIC]
    )

    for data_type in candidates:
        fetch_kwargs = {"start": start_date, "end": end_date}
        if ts_codes:
            fetch_kwargs["ts_code"] = ts_codes
        basic = jhd.get_data(data_type, **fetch_kwargs)
        df = _to_df(basic)
        if df is None or df.empty:
            continue

        frame = df.copy().rename(columns={"ts_code": "symbol", "trade_date": "date"})
        if data_type == DataTypes.TS_MONTHLY_BASIC:
            rprint(
                f"[green]Using ts_monthly_basic for basic metrics "
                f"({start_date} ~ {end_date})[/green]"
            )
            # Server contract: one row per symbol-month. Cheap guard against
            # stray duplicate rows (keep last, matching tail(1) semantics), and
            # sort like month_end_rows so both sources produce identical order.
            return (
                frame.drop_duplicates(["symbol", "date"], keep="last")
                .sort_values(["symbol", "date"])
                .reset_index(drop=True)
            )
        if len(candidates) > 1:
            rprint(
                "[yellow]ts_monthly_basic 无数据，回退 ts_daily_basic 本地降频[/yellow]"
            )
        return month_end_rows(frame)

    raise ValueError("无法获取基本面数据: ts_monthly_basic 与 ts_daily_basic 均为空")


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
    df[ANN_DATE_COL] = df["date"]

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

    ``symbols`` is optional; when omitted or empty, data for all A-shares is
    loaded (the request omits ``ts_code`` entirely). Pass a list of ts_codes to
    restrict the universe, e.g. ``symbols=["000001.SZ", "600000.SH"]``.

    ``period="M"`` uses TS_MONTHLY_* price data and TS_MONTHLY_BASIC daily-basic
    data directly (falling back to TS_DAILY_BASIC reduced locally when the
    monthly table is unavailable). ``period="D"`` uses TS_DAILY_* price data and
    converts it to month-end returns, always using TS_DAILY_BASIC.
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
    # Empty symbols means "all stocks": omit ts_code entirely (an empty string
    # would be rejected by the server), rather than filtering to zero codes.
    fetch_kwargs = {}
    if symbols:
        fetch_kwargs["ts_code"] = ",".join(symbols)
    price_data_type, already_monthly = _ts_price_data_type(
        DataTypes,
        period=period,
        price_adjust=price_adjust,
    )

    prices = jhd.get_data(
        price_data_type,
        start=start_date,
        end=end_date,
        **fetch_kwargs,
    )
    stock_returns = _monthly_returns_from_ts_prices(
        prices,
        already_monthly=already_monthly,
    )

    basic_monthly = _fetch_basic_monthly(
        jhd,
        period=period,
        start_date=start_date,
        end_date=end_date,
        ts_codes=",".join(symbols) if symbols else None,
    )
    market_cap = to_factor_market_cap_frame(basic_monthly)
    if lag_features:
        market_cap = _align_features_to_next_return_date(market_cap, stock_returns)

    pb = pd.to_numeric(basic_monthly["pb"], errors="coerce")
    basic_monthly["bm"] = 1 / pb.where(pb > 0)
    bm = to_factor_input_frame(basic_monthly, field_name="bm")

    price_df = _to_df(prices).copy().rename(
        columns={"ts_code": "symbol", "trade_date": "date"}
    )
    price_monthly = price_df if already_monthly else month_end_rows(price_df)

    fundamentals: dict[str, pd.DataFrame] = {"bm": bm}
    fundamentals.update(_build_price_fields(price_monthly, stock_returns))

    if include_proxy_fundamentals:
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
