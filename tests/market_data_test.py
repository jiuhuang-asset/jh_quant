from __future__ import annotations

import pandas as pd

from jh_quant.data import DataTypes
from jh_quant.trading.market_data import JHMarketDataProvider


class FakeJHDataResult:
    code_date_col = ("symbol", "dt")

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def to_df(self) -> pd.DataFrame:
        return self._df


class FakeJHData:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.calls = []

    def get_data(self, data_type, **kwargs):
        self.calls.append((data_type, kwargs))
        return FakeJHDataResult(self.df)


def test_fetch_today_spot_checks_freshness_after_query():
    fake_jhd = FakeJHData(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "latest": 10.5,
                    "dt": "2026-05-06 14:55:00",
                }
            ]
        )
    )
    provider = JHMarketDataProvider(jhd=fake_jhd)
    provider._get_today_spot_fresh_after = lambda: pd.Timestamp(
        "2026-05-06 14:50:00"
    )

    result = provider._fetch_today_spot_df(["000001"])

    data_type, kwargs = fake_jhd.calls[0]
    assert data_type == DataTypes.AK_STOCK_ZH_A_SPOT
    assert kwargs == {"symbol": "000001", "bypass_cache": True}
    assert result.loc[0, "symbol"] == "000001"
    assert result.loc[0, "close"] == 10.5
    assert result.loc[0, "date"] == pd.Timestamp("2026-05-06")


def test_fetch_today_spot_drops_stale_rows_by_dt():
    fake_jhd = FakeJHData(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "latest": 10.5,
                    "dt": "2026-05-06 14:40:00",
                }
            ]
        )
    )
    provider = JHMarketDataProvider(jhd=fake_jhd)
    provider._get_today_spot_fresh_after = lambda: pd.Timestamp(
        "2026-05-06 14:50:00"
    )

    result = provider._fetch_today_spot_df(["000001"])

    assert result.empty
