"""
conftest.py - pytest configuration for gateway tests.

Sets up polars mock before any project imports to avoid import chain
requiring the optional polars dependency.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_polars_mock():
    """Create a minimal polars mock that satisfies the factors module."""
    polars_mock = types.ModuleType("polars")

    # Core types
    polars_mock.Expr = MagicMock()
    polars_mock.DataFrame = MagicMock()
    polars_mock.Series = MagicMock()
    polars_mock.LazyFrame = MagicMock()

    # Common functions used by factors/general.py
    polars_mock.concat = MagicMock()
    polars_mock.col = MagicMock()
    polars_mock.lit = MagicMock()
    polars_mock.all = MagicMock()
    polars_mock.any = MagicMock()
    polars_mock.sum = MagicMock()
    polars_mock.mean = MagicMock()
    polars_mock.max = MagicMock()
    polars_mock.min = MagicMock()
    polars_mock.std = MagicMock()
    polars_mock.var = MagicMock()
    polars_mock.count = MagicMock()
    polars_mock.when = MagicMock()
    polars_mock.otherwise = MagicMock()
    polars_mock.element = MagicMock()
    polars_mock.rolling = MagicMock()
    polars_mock.exp = MagicMock()
    polars_mock.log = MagicMock()
    polars_mock.abs = MagicMock()
    polars_mock.sqrt = MagicMock()
    polars_mock.null = MagicMock()
    polars_mock.sort = MagicMock()
    polars_mock.drop = MagicMock()
    polars_mock.rename = MagicMock()
    polars_mock.with_columns = MagicMock()
    polars_mock.select = MagicMock()
    polars_mock.filter = MagicMock()
    polars_mock.group_by = MagicMock()
    polars_mock.agg = MagicMock()
    polars_mock.join = MagicMock()
    polars_mock.melt = MagicMock()
    polars_mock.pivot = MagicMock()
    polars_mock.unique = MagicMock()
    polars_mock.is_null = MagicMock()
    polars_mock.is_not_null = MagicMock()
    polars_mock.fill_null = MagicMock()
    polars_mock.drop_nulls = MagicMock()
    polars_mock.limit = MagicMock()
    polars_mock.slice = MagicMock()
    polars_mock.head = MagicMock()
    polars_mock.tail = MagicMock()
    polars_mock.n_unique = MagicMock()
    polars_mock.value_counts = MagicMock()
    polars_mock.cum_sum = MagicMock()
    polars_mock.cum_prod = MagicMock()
    polars_mock.cum_min = MagicMock()
    polars_mock.cum_max = MagicMock()
    polars_mock.rolling_sum = MagicMock()
    polars_mock.rolling_mean = MagicMock()
    polars_mock.rolling_min = MagicMock()
    polars_mock.rolling_max = MagicMock()
    polars_mock.rolling_std = MagicMock()
    polars_mock.rolling_var = MagicMock()
    polars_mock.rolling_corr = MagicMock()
    polars_mock.ewm_mean = MagicMock()
    polars_mock.ewm_std = MagicMock()
    polars_mock.pct_change = MagicMock()
    polars_mock.diff = MagicMock()
    polars_mock.rank = MagicMock()
    polars_mock.lag = MagicMock()
    polars_mock.lead = MagicMock()
    polars_mock.and_ = MagicMock()
    polars_mock.or_ = MagicMock()
    polars_mock.not_ = MagicMock()
    polars_mock.in_ = MagicMock()
    polars_mock.contains = MagicMock()
    polars_mock.strptime = MagicMock()
    polars_mock.to_date = MagicMock()
    polars_mock.to_datetime = MagicMock()
    polars_mock.hash = MagicMock()
    polars_mock.arctan2 = MagicMock()
    polars_mock.degrees = MagicMock()
    polars_mock.radians = MagicMock()
    polars_mock.cos = MagicMock()
    polars_mock.sin = MagicMock()
    polars_mock.tan = MagicMock()
    polars_mock.cosh = MagicMock()
    polars_mock.sinh = MagicMock()
    polars_mock.tanh = MagicMock()
    polars_mock.arcsin = MagicMock()
    polars_mock.arccos = MagicMock()
    polars_mock.arctan = MagicMock()
    polars_mock.from_dict = MagicMock()
    polars_mock.from_pandas = MagicMock()
    polars_mock.to_pandas = MagicMock()
    polars_mock.from_records = MagicMock()
    polars_mock.argwhere = MagicMock()
    polars_mock.float = MagicMock()
    polars_mock.int = MagicMock()
    polars_mock.str = MagicMock()
    polars_mock.bool = MagicMock()

    # Struct types
    polars_mock.Struct = MagicMock()
    polars_mock.StructField = MagicMock()
    polars_mock.List = MagicMock()
    polars_mock.Duration = MagicMock()
    polars_mock.Datetime = MagicMock()
    polars_mock.Date = MagicMock()
    polars_mock.Time = MagicMock()
    polars_mock.Float64 = MagicMock()
    polars_mock.Int64 = MagicMock()
    polars_mock.Int32 = MagicMock()
    polars_mock.String = MagicMock()
    polars_mock.Boolean = MagicMock()

    # Categorical, Object, Unknown
    polars_mock.Categorical = MagicMock()
    polars_mock.Object = MagicMock()
    polars_mock.Unknown = MagicMock()

    return polars_mock


# Install polars mock BEFORE any project imports
if "polars" not in sys.modules:
    _polars = _make_polars_mock()
    sys.modules["polars"] = _polars
    sys.modules["polars.datatypes"] = types.ModuleType("polars.datatypes")
    sys.modules["polars.datatypes"].Unknown = MagicMock()
    sys.modules["polars.datatypes"].Int64 = MagicMock()
    sys.modules["polars.datatypes"].Float64 = MagicMock()
    sys.modules["polars.datatypes"].Boolean = MagicMock()
    sys.modules["polars.datatypes"].Utf8 = MagicMock()
    sys.modules["polars.datatypes"].List = MagicMock()
    sys.modules["polars.datatypes"].Date = MagicMock()
    sys.modules["polars.datatypes"].Datetime = MagicMock()
    sys.modules["polars.datatypes"].Duration = MagicMock()
    sys.modules["polars.datatypes"].Struct = MagicMock()
    sys.modules["polars.datatypes"].Object = MagicMock()
    sys.modules["polars.datatypes"].Categorical = MagicMock()
    sys.modules["polars.datatypes"].Enum = MagicMock()
    sys.modules["polars.datatypes"].Expression = MagicMock()
    sys.modules["polars.functions"] = types.ModuleType("polars.functions")
    sys.modules["polars.functions"].col = MagicMock()
    sys.modules["polars.functions"].lit = MagicMock()
    sys.modules["polars.functions"].when = MagicMock()
    sys.modules["polars.polars"] = types.ModuleType("polars.polars")
    sys.modules["polars.polars"].expr = MagicMock()
    sys.modules["polars.exceptions"] = types.ModuleType("polars.exceptions")
    sys.modules["polars.exceptions"].PolarsError = MagicMock()
    sys.modules["polars._"] = types.ModuleType("polars._")
    sys.modules["polars._.expr"] = types.ModuleType("polars._.expr")

    # Patch os.cpu_count so that joblib.Parallel uses n_jobs=1
    # (avoids spawning subprocesses that lack the polars mock)
    import os
    _orig_cpu_count = os.cpu_count
    os.cpu_count = lambda: 1
