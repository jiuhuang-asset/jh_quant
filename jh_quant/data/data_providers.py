import pandas as pd
import numpy as np
import re
from datetime import datetime
from .data_types import DataTypes, get_data_rename_mapping
from .data import JHData, JhDataType

__all__ = ["akshare", "tushare"]


def _normalize_date(date_val) -> str:
    """Normalize date to YYYY-MM-DD format.

    Handles:
    - YYYYMMDD (e.g., 20250101) -> 2025-01-01
    - YYYY-MM-DD (e.g., 2025-01-01) -> 2025-01-01
    """
    if not date_val:
        return date_val
    date_str = str(date_val)
    # If already in YYYY-MM-DD format, return as is
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    # If in YYYYMMDD format, insert dashes
    if re.match(r"^\d{8}$", date_str):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _find_data_type(prefix: str, method_name: str, adjust: str = None) -> DataTypes:
    """Find DataType by prefix + method name, with optional adjust suffix.

    Args:
        prefix: Provider prefix ("ak_", "ts_", etc.)
        method_name: Method name (e.g., "stock_zh_a_hist")
        adjust: Optional adjust suffix

    Returns:
        DataType enum member

    Raises:
        NotSupportedError: If DataType is not found
    """
    name = f"{prefix}{method_name}"
    if adjust:
        name = f"{name}_{adjust}"
    try:
        return DataTypes(name)
    except:
        erro_method_name = f"{method_name}"
        if adjust:
            erro_method_name = f"{method_name} with adjust `{adjust}`, you can first try remove adjust argument"
        raise NotSupportedError(f"API not supported yet: `{erro_method_name}`")


class NotSupportedError(Exception):
    """Raised when a data type is not supported"""

    pass


class _DynamicApiWrapper:
    """Base class for dynamic API wrappers using __getattr__"""

    # Subclasses should set their reverse function name
    _reverse_func_name: str = None

    def __init__(self, jhd=None, prefix: str = ""):
        self._jhd = jhd
        self._prefix = prefix

    def _get_jhd(self):
        """Create JHData lazily so importing wrappers does not touch local cache."""
        if self._jhd is None:
            self._jhd = JHData()
        return self._jhd

    def _get_reverse_func(self):
        """Get the reverse function by name (late binding)"""
        if self._reverse_func_name == "reverse_ak":
            return reverse_ak
        elif self._reverse_func_name == "reverse_ts":
            return reverse_ts
        return None

    def _call_jhd(self, data_type: DataTypes, **kwargs):
        """Call JHData get_data and return reversed data"""
        df = self._get_jhd().get_data(data_type, **kwargs)
        if df is None:
            return None
        reverse_func = self._get_reverse_func()
        if reverse_func:
            return reverse_func(df)
        return df

    def __getattr__(self, name: str):
        """Dynamic method dispatch for API calls"""
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        def wrapper(**kwargs):
            data_type = _find_data_type(self._prefix, name, kwargs.get("adjust"))
            normalized_kwargs = self._build_kwargs(kwargs, data_type)
            return self._call_jhd(data_type, **normalized_kwargs)

        return wrapper


# ===== Akshare compatible wrapper =====


class _JhAkShare(_DynamicApiWrapper):
    """JHData wrapper providing akshare-compatible API using dynamic method dispatch"""

    _reverse_func_name = "reverse_ak"

    def __init__(self, jhd=None):
        super().__init__(jhd=jhd, prefix="ak_")

    def _build_kwargs(self, kwargs: dict, data_type: DataTypes = None) -> dict:
        """Build kwargs for akshare: normalize dates and map start_date/end_date to start/end"""
        result = {}

        for k, v in kwargs.items():
            if v is None:
                continue
            # Map akshare params to jhd params
            if k == "start_date":
                result["start"] = _normalize_date(v)
            elif k == "date" and data_type in {
                DataTypes.AK_STOCK_LRB_EM,
                DataTypes.AK_STOCK_XJLL_EM,
                DataTypes.AK_STOCK_ZCFZ_EM,
            }:
                result["start"] = _normalize_date(v)
                result["end"] = _normalize_date(v)
            elif k == "period" and "hist" in data_type.value:
                if v != "daily":
                    raise ValueError(
                        f"目前只支持日线数据, 请不要指定或将period设置为`daily`"
                    )
            elif k == "indicator" and "fund_flow" in data_type.value:
                pass
            elif (
                k == "symbol"
                and data_type == DataTypes.AK_STOCK_MAIN_FUND_FLOW
                and v == "全部股票"
            ):
                pass
            elif k == "stock" and data_type == DataTypes.AK_STOCK_INDIVIDUAL_FUND_FLOW:
                result["symbol"] = v
            elif k == "end_date":
                result["end"] = _normalize_date(v)
            elif k == "adjust":
                pass  # Don't pass adjust to jhd, handled in _find_data_type
            else:
                result[k] = v
        return result


# Global akshare instance (initialized lazily on first use)
akshare = _JhAkShare()


# ===== Tushare compatible wrapper =====


class _TushareProApi(_DynamicApiWrapper):
    """Tushare Pro API wrapper using JHData"""

    _reverse_func_name = "reverse_ts"

    def __init__(self, jhd=None):
        super().__init__(jhd=jhd, prefix="ts_")

    def _build_kwargs(self, kwargs: dict, data_type: DataTypes = None) -> dict:
        """Build kwargs for tushare: normalize dates and map to correct field names"""
        result = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            # Map tushare date params to jhd params
            if k == "start_date":
                result["start"] = _normalize_date(v)
            elif k == "end_date":
                result["end"] = _normalize_date(v)
            elif k == "trade_date":
                result[k] = _normalize_date(v)
            elif k == "fields":
                result[k] = v
            else:
                result[k] = v
        return result

    def pro_bar(
        self, ts_code=None, start_date=None, end_date=None, asset="E", freq="D"
    ):
        """获取行情数据 (tushare pro.pro_bar)"""
        # Map asset and freq to appropriate DataType
        if asset == "E" and freq == "D":
            data_type = DataTypes.TS_DAILY
        elif asset == "E" and freq == "W":
            data_type = DataTypes.TS_WEEKLY
        elif asset == "E" and freq == "M":
            data_type = DataTypes.TS_MONTHLY
        else:
            raise ValueError(f"Unsupported asset/freq combination: {asset}/{freq}")

        kwargs = {}
        if ts_code:
            kwargs["ts_code"] = ts_code
        if start_date:
            kwargs["start_date"] = _normalize_date(start_date)
        if end_date:
            kwargs["end_date"] = _normalize_date(end_date)

        df = self._get_jhd().get_data(data_type, **kwargs)
        return reverse_ts(df)

    def __getattr__(self, name: str):
        """动态方法分发，支持 pro.daily()、pro.daily_basic() 等调用"""
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        # 动态查找 DataType
        try:
            data_type = DataTypes(f"ts_{name}")
        except ValueError:
            raise AttributeError(
                f"不支持的 tushare 方法: `{name}`. 请检查方法名是否正确"
            )

        def wrapper(**kwargs):
            normalized_kwargs = self._build_kwargs(kwargs, data_type)
            return self._call_jhd(data_type, **normalized_kwargs)

        return wrapper


class _JhTushare:
    """JHData wrapper providing tushare-compatible API"""

    def __init__(self, jhd=None):
        self._jhd = jhd
        self._pro_api = None

    def _get_jhd(self):
        """Create JHData lazily so importing wrappers does not touch local cache."""
        if self._jhd is None:
            self._jhd = JHData()
        return self._jhd

    def __getattr__(self, name: str):
        """动态方法分发，支持 tushare.daily() 和 tushare.pro.daily() 形式的调用"""
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        # 如果是调用 pro 属性，返回同一个 _TushareProApi 实例
        if name == "pro":
            if self._pro_api is None:
                self._pro_api = _TushareProApi(self._get_jhd())
            return self._pro_api

        # 其他方法通过 pro 调用
        pro_api = self.pro_api()
        method = getattr(pro_api, name)
        return method

    def pro_api(self, jhd=None):
        """返回 Tushare Pro API 对象"""
        effective_jhd = jhd or self._get_jhd()
        return _TushareProApi(effective_jhd)


# Global tushare instance
tushare = _JhTushare()


def init_wrappers(jhd):
    """Initialize akshare and tushare wrappers with JHData instance"""
    global akshare, tushare
    akshare = _JhAkShare(jhd)
    tushare = _JhTushare(jhd)


def reverse_ak(df: pd.DataFrame):
    if df is None:
        raise ValueError("data is None")
    dt = df.jh_dt
    data = _reverse_data_rename(dt, df)
    data = _reverse_process_ak_data(dt, data)

    return JhDataType(data, dt)


def process_ak(df: JhDataType):
    if df is None:
        raise ValueError("data is None")
    dt = df.jh_dt
    data = _process_ak_data(dt, df)
    renmae_mapping = get_data_rename_mapping(dt)
    data = data.rename(columns=renmae_mapping)

    return JhDataType(data, dt)


def reverse_ts(df: JhDataType):
    dt =  df.jh_dt
    data = _reverse_data_rename(dt, df)
    data = _reverse_process_ts_data(data)

    return JhDataType(data, dt)


def process_ts(df: pd.DataFrame):
    dt = df.jh_dt
    data = _process_ts_data(df)
    renmae_mapping = get_data_rename_mapping(dt)
    data = data.rename(columns=renmae_mapping)
    return JhDataType(data, dt)


def _reverse_data_rename(data_type: DataTypes, df: pd.DataFrame) -> pd.DataFrame:
    """根据 get_data_rename_mapping 复原原来的字段名"""
    mapping = get_data_rename_mapping(data_type)
    if not mapping:
        return df

    # 反转映射: {"基金代码": "symbol"} -> {"symbol": "基金代码"}
    reverse_mapping = {v: k for k, v in mapping.items()}

    # 只重命名存在于 df 中的列
    cols_to_rename = {k: v for k, v in reverse_mapping.items() if k in df.columns}
    if cols_to_rename:
        df = df.rename(columns=cols_to_rename)
    return df


def _reverse_process_ak_data(data_type: DataTypes, df: pd.DataFrame) -> pd.DataFrame:
    """将被 _process_ak_data 处理过的数据 reverse 成原来的样子"""
    if df.empty:
        return df

    value = data_type.value
    date_processer = _AkDateProcessor()

    # 1. 移除 end_date 列 (财务报表类型)
    if value in ("ak_stock_zcfz_em", "ak_stock_xjll_em", "ak_stock_lrb_em"):
        df = df.drop(columns=["end_date"], errors="ignore")

    # 2. 移除 symbol 列
    symbol_types = {
        "ak_fund_etf_hist_em",
        "ak_fund_etf_hist_em_qfq",
        "ak_fund_etf_hist_em_hfq",
        "ak_stock_zh_index_daily",
        "ak_stock_individual_fund_flow",
        "ak_stock_sector_fund_flow_summary",
        "ak_stock_sector_fund_flow_hist",
        "ak_stock_cyq_em",
        "ak_stock_cyq_em_qfq",
        "ak_stock_cyq_em_hfq",
        "ak_fund_portfolio_hold_em",
        "ak_fund_portfolio_industry_allocation_em",
    }
    if value in symbol_types:
        df = df.drop(columns=["symbol"], errors="ignore")

    # 3. 移除 date 列
    if value in ("ak_stock_sector_fund_flow_rank", "ak_stock_main_fund_flow"):
        df = df.drop(columns=["date"], errors="ignore")

    # 4. 时间戳处理 (stock_zh_a_spot) - 还原为时间字符串
    if value == "ak_stock_zh_a_spot_em":
        if "时间戳" in df.columns:
            df = df.copy()
            df["时间戳"] = df["时间戳"].apply(
                lambda x: x.strftime("%H:%M:%S") if pd.notnull(x) else x
            )

    # 5. pivot 处理 (stock_individual_info_em) - 无法完全还原，跳过
    # 6. 年月提取处理 - 还原为原始格式
    year_month1_types = {
        "ak_macro_china_fdi",
        "ak_macro_china_qyspjg",
        "ak_macro_china_gyzjz",
        "ak_macro_china_new_financial_credit",
        "ak_macro_china_ppi",
        "ak_macro_china_pmi",
        "ak_macro_china_gdzctz",
        "ak_macro_china_hgjck",
        "ak_macro_china_czsr",
        "ak_macro_china_whxd",
        "ak_macro_china_wbck",
        "ak_macro_china_xfzxx",
        "ak_macro_china_cpi",
        "ak_macro_china_money_supply",
        "ak_macro_china_fx_gold",
        "ak_macro_china_shrzgm",
    }
    if value in year_month1_types:
        if "月份" in df.columns:
            df = df.copy()
            df["月份"] = df["月份"].apply(
                lambda x: date_processer.reverse_year_month1(x)
            )

    # 7. 年月提取处理 (extract_year_month2)
    year_month2_types = {
        "ak_macro_cnbs",
        "ak_macro_rmb_loan",
        "ak_macro_rmb_deposit",
    }
    if value in year_month2_types:
        col = "年份" if value == "ak_macro_cnbs" else "月份"
        if col in df.columns:
            df = df.copy()
            df[col] = df[col].apply(lambda x: date_processer.reverse_year_month2(x))

    # 8. 年月提取处理 (extract_year_month)
    if value == "ak_macro_china_shrzgm":
        if "月份" in df.columns:
            df = df.copy()
            df["月份"] = df["月份"].apply(
                lambda x: date_processer.reverse_year_month(x)
            )

    # 9. 统计时间提取处理 (extract_year_month3)
    year_month3_types = {
        "ak_macro_china_society_electricity",
        "ak_macro_china_society_traffic_volume",
        "ak_macro_china_passenger_load_factor",
        "ak_macro_china_central_bank_balance",
        "ak_macro_china_insurance",
        "ak_macro_china_supply_of_money",
        "ak_macro_china_foreign_exchange_gold",
        "ak_macro_china_retail_price_index",
    }
    if value in year_month3_types:
        if "统计时间" in df.columns:
            df = df.copy()
            df["统计时间"] = df["统计时间"].apply(
                lambda x: date_processer.reverse_year_month3(x)
            )

    # 10. 日期提取处理 (extract_date1)
    if value == "ak_macro_china_reserve_requirement_ratio":
        if "公布时间" in df.columns:
            df = df.copy()
            df["公布时间"] = df["公布时间"].apply(
                lambda x: date_processer.reverse_date1(x)
            )
        if "生效时间" in df.columns:
            df["生效时间"] = df["生效时间"].apply(
                lambda x: date_processer.reverse_date1(x)
            )

    # 11. 数据日期提取处理 (extract_year_month1)
    if value == "ak_macro_china_stock_market_cap":
        if "数据日期" in df.columns:
            df = df.copy()
            df["数据日期"] = df["数据日期"].apply(
                lambda x: date_processer.reverse_year_month1(x)
            )

    return df


def _process_ak_data(
    data_type: DataTypes, df: pd.DataFrame, **kwargs
) -> pd.DataFrame:
    """根据 data_type 统一处理返回的 DataFrame"""

    date_processer = _AkDateProcessor()
    value = data_type.value

    # 1. 添加 end_date (财务报表类型)
    if value in ("ak_stock_zcfz_em", "ak_stock_xjll_em", "ak_stock_lrb_em"):
        date_val = kwargs.get("date") or kwargs.get("end_date")
        if date_val:
            df = df.copy()
            df["end_date"] = date_val

    # 2. 添加 symbol 列
    symbol_types = {
        "ak_fund_etf_hist_em",
        "ak_fund_etf_hist_em_qfq",
        "ak_fund_etf_hist_em_hfq",
        "ak_stock_zh_index_daily",
        "ak_stock_individual_fund_flow",
        "ak_stock_sector_fund_flow_summary",
        "ak_stock_sector_fund_flow_hist",
        "ak_stock_cyq_em",
        "ak_stock_cyq_em_qfq",
        "ak_stock_cyq_em_hfq",
        "ak_fund_portfolio_hold_em",
        "ak_fund_portfolio_industry_allocation_em",
    }
    if value in symbol_types:
        df = df.copy()
        df["symbol"] = kwargs.get("symbol", "") or kwargs.get("stock", "")

    # 3. 添加 date (当前日期)
    if value in ("ak_stock_sector_fund_flow_rank", "ak_stock_main_fund_flow"):
        df = df.copy()
        df["date"] = datetime.now().strftime("%Y-%m-%d")

    # 4. 时间戳处理 (stock_zh_a_spot)
    if value == "ak_stock_zh_a_spot_em":
        today = datetime.today().date()
        df = df.copy()
        df["时间戳"] = df["时间戳"].apply(
            lambda x: datetime.combine(today, datetime.strptime(x, "%H:%M:%S").time())
        )

    # 5. pivot 处理 (stock_individual_info_em)
    if value == "ak_stock_individual_info_em":
        df = df.pivot_table(index=None, columns="item", values="value", aggfunc="first")
        df = df.reset_index(drop=True)
        df["上市时间"] = pd.to_datetime(df["上市时间"], format="%Y%m%d")
        df.replace({"-": np.nan}, inplace=True)

    # 6. 年月提取处理 (macro 类型，使用 extract_year_month1)
    year_month1_types = {
        "ak_macro_china_fdi",
        "ak_macro_china_qyspjg",
        "ak_macro_china_gyzjz",
        "ak_macro_china_new_financial_credit",
        "ak_macro_china_ppi",
        "ak_macro_china_pmi",
        "ak_macro_china_gdzctz",
        "ak_macro_china_hgjck",
        "ak_macro_china_czsr",
        "ak_macro_china_whxd",
        "ak_macro_china_wbck",
        "ak_macro_china_xfzxx",
        "ak_macro_china_cpi",
        "ak_macro_china_money_supply",
        "ak_macro_china_fx_gold",
        "ak_macro_china_shrzgm",
    }
    if value in year_month1_types:
        df = df.copy()
        col = "月份"
        if col in df.columns:
            df[col] = df[col].apply(lambda x: date_processer.extract_year_month1(x))
            df = df.dropna(subset=[col])

    # 7. 年月提取处理 (extract_year_month2)
    year_month2_types = {
        "ak_macro_cnbs",
        "ak_macro_rmb_loan",
        "ak_macro_rmb_deposit",
    }
    if value in year_month2_types:
        df = df.copy()
        col = "年份" if value == "ak_macro_cnbs" else "月份"
        if col in df.columns:
            df[col] = df[col].apply(lambda x: date_processer.extract_year_month2(x))
            df = df.dropna(subset=[col])

    # 8. 年月提取处理 (extract_year_month)
    if value == "ak_macro_china_shrzgm":
        df = df.copy()
        df["月份"] = df["月份"].apply(lambda x: date_processer.extract_year_month(x))
        df = df.dropna(subset=["月份"])

    # 9. 统计时间提取处理 (extract_year_month3)
    year_month3_types = {
        "ak_macro_china_society_electricity",
        "ak_macro_china_society_traffic_volume",
        "ak_macro_china_passenger_load_factor",
        "ak_macro_china_central_bank_balance",
        "ak_macro_china_insurance",
        "ak_macro_china_supply_of_money",
        "ak_macro_china_foreign_exchange_gold",
        "ak_macro_china_retail_price_index",
    }
    if value in year_month3_types:
        df = df.copy()
        df["统计时间"] = df["统计时间"].apply(
            lambda x: date_processer.extract_year_month3(x)
        )
        df = df.dropna(subset=["统计时间"])

    # 10. 日期提取处理 (extract_date1)
    if value == "ak_macro_china_reserve_requirement_ratio":
        df = df.copy()
        df["公布时间"] = df["公布时间"].apply(lambda x: date_processer.extract_date1(x))
        df["生效时间"] = df["生效时间"].apply(lambda x: date_processer.extract_date1(x))
        df = df.dropna(subset=["公布时间", "生效时间"])

    # 11. 数据日期提取处理 (extract_year_month1)
    if value == "ak_macro_china_stock_market_cap":
        df = df.copy()
        df["数据日期"] = df["数据日期"].apply(
            lambda x: date_processer.extract_year_month1(x)
        )
        df = df.dropna(subset=["数据日期"])

    # 12. fund_info_index_em 过滤处理
    if value == "ak_fund_info_index_em":
        df = df[df["日期"] != ""]
        df = df.drop_duplicates(subset=["基金代码"], keep="last")

    # 13. stop/st 数据过滤
    if value == "ak_stock_zh_a_stop_em":
        df = df[["代码", "名称"]]

    if value == "ak_stock_zh_a_st_em":
        df = df[["代码", "名称"]].copy()
        df["date"] = datetime.today()

    return df


def _process_ts_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    data_processer = _TsDateProcessor()
    df = df.copy()

    # 转换日期列 (如 20200101 -> 2020-01-01)
    date_columns = [
        "trade_date",
        "date",
        "ann_date",
        "report_date",
        "end_date",
        "start_date",
        "pub_date",
    ]
    for col in date_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: data_processer.modify_date(x))

    # 转换 time 列 (如 0930 -> 今天 09:30:00)
    if "time" in df.columns:
        df["time"] = df["time"].apply(lambda x: data_processer.modify_time(x))

    return df


def _reverse_process_ts_data(df: pd.DataFrame) -> pd.DataFrame:
    """将被 _process_ts_data 处理过的数据 reverse 成原来的样子"""
    if df is None or df.empty:
        return df
    data_processer = _TsDateProcessor()
    df = df.copy()

    # 反转日期列 (如 2020-01-01 -> 20200101)
    date_columns = [
        "trade_date",
        "date",
        "ann_date",
        "report_date",
        "end_date",
        "start_date",
        "pub_date",
    ]
    for col in date_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: data_processer.reverse_date(x))

    # 反转 time 列 (如 2024-01-01 09:30:00 -> 0930)
    if "time" in df.columns:
        df["time"] = df["time"].apply(lambda x: data_processer.reverse_time(x))

    return df


class _TsDateProcessor:
    @staticmethod
    def modify_date(date_val) -> str:
        """'20200101' or datetime -> '2020-01-01'"""
        if pd.isna(date_val):
            return date_val
        # Handle datetime or pandas Timestamp objects
        if hasattr(date_val, "strftime"):
            return date_val.strftime("%Y-%m-%d")
        date_str = str(date_val)
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_val

    @staticmethod
    def reverse_date(date_val) -> str:
        """'2020-01-01' or datetime -> '20200101'"""
        if pd.isna(date_val):
            return date_val
        # Handle datetime or pandas Timestamp objects
        if hasattr(date_val, "strftime"):
            return date_val.strftime("%Y%m%d")
        date_str = str(date_val)
        if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
            return f"{date_str[:4]}{date_str[5:7]}{date_str[8:10]}"
        return date_val

    @staticmethod
    def modify_time(time_val) -> str:
        """'0930' -> '2024-01-01 09:30:00'"""
        if pd.isna(time_val):
            return time_val
        time_str = str(time_val)
        if len(time_str) == 4 and time_str.isdigit():
            hour = time_str[:2]
            minute = time_str[2:]
            today = datetime.today().isoformat()
            return f"{today} {hour}:{minute}:00"
        return time_val

    @staticmethod
    def reverse_time(time_val) -> str:
        """'2024-01-01 09:30:00' -> '0930'"""
        if pd.isna(time_val):
            return time_val
        time_str = str(time_val)
        # Format: '2024-01-01 09:30:00' or '2024-01-01T09:30:00'
        parts = time_str.replace("T", " ").split()
        if len(parts) >= 2:
            hm = parts[1].replace(":", "")[:4]  # '09:30:00' -> '0930'
            return hm
        return time_val


class _AkDateProcessor:
    @staticmethod
    def extract_year_month(year_month_str) -> int:
        """
        Extracts year and month from a string in 'YYYYMM' format and converts it to an integer.

        Args:
            year_month_str (str): A string in the format 'YYYYMM'.

        Returns:
            int: An integer in the format YYYYMM, or None if conversion fails.
        """
        try:
            output = int(year_month_str)
            return output
        except (
            ValueError,
            AttributeError,
        ):  # If conversion fails or input is not string, return None
            return None

    @staticmethod
    def extract_year_month1(year_month_str) -> str:
        """
        Extracts year and month from a string and converts it to a string.

        Args:
            year_month_str (str): A string in the format 'YYYY年MM月份'.

        Returns:
            str: A string in the format 'YYYY-mm'.
        """
        # Remove '年' and '月份' from the string
        cleaned_str = year_month_str.replace("年", "").replace("月份", "")

        # Convert to string in YYYY-mm format
        try:
            year = cleaned_str[:4]
            month = cleaned_str[4:6].zfill(2)
            output = f"{year}-{month}"
            return output
        except ValueError:  # If conversion fails, return None
            return None

    @staticmethod
    def extract_year_month2(year_month_str) -> str:
        """
        Extracts year and month from a string in 'YYYY-MM' format and converts it to a string.

        Args:
            year_month_str (str): A string in the format 'YYYY-MM'.

        Returns:
            str: A string in the format 'YYYY-mm', or None if conversion fails.
        """
        try:
            # Split the string by '-' and join with '-' separator
            year, month = year_month_str.split("-")
            output = f"{year}-{month.zfill(2)}"
            return output
        except (
            ValueError,
            AttributeError,
        ):  # If conversion fails or input is not string, return None
            return None

    @staticmethod
    def extract_year_month3(year_month_str) -> str:
        """
        Extracts year and month from a string in 'YYYY.M' or 'YYYY.MM' format and converts it to a string.

        Args:
            year_month_str (str): A string in the format 'YYYY.M' or 'YYYY.MM'.

        Returns:
            str: A string in the format 'YYYY-mm', or None if conversion fails.
        """
        try:
            # Split the string by '.' to separate year and month
            parts = year_month_str.split(".")
            if len(parts) != 2:
                return None

            year, month = parts

            # Ensure month is two digits
            month = month.zfill(2)

            # Combine and convert to string
            output = f"{year}-{month}"
            return output
        except (
            ValueError,
            AttributeError,
        ):  # If conversion fails or input is not string, return None
            return None

    @staticmethod
    def extract_date1(date_str) -> str:
        """
        Extracts date from a string in 'YYYY年MM月DD日' format and converts it to 'YYYY-MM-DD' format.

        Args:
            date_str (str): A string in the format 'YYYY年MM月DD日'.

        Returns:
            str: A string in the format 'YYYY-MM-DD', or None if conversion fails.
        """
        try:
            # Remove '年', '月', and '日' from the string
            cleaned_str = (
                date_str.replace("年", "-").replace("月", "-").replace("日", "")
            )

            # Split the string by '-' to get year, month, and day
            year, month, day = cleaned_str.split("-")

            # Format as 'YYYY-MM-DD'
            output = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

            return output
        except (
            ValueError,
            AttributeError,
        ):  # If conversion fails or input is not string, return None
            return None

    # ===== Reverse methods =====
    @staticmethod
    def reverse_year_month1(ym_str) -> str:
        """Reverse: 'YYYY-mm' -> 'YYYY年MM月份'"""
        try:
            if not ym_str or pd.isna(ym_str):
                return None
            parts = ym_str.split("-")
            if len(parts) != 2:
                return None
            year, month = parts
            return f"{year}年{month}月份"
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def reverse_year_month2(ym_str) -> str:
        """Reverse: 'YYYY-mm' -> 'YYYY-MM'"""
        try:
            if not ym_str or pd.isna(ym_str):
                return None
            return ym_str  # Already in YYYY-MM format, just return as is
        except (ValueError, AttributeError):
            return None

    def reverse_year_month(ym_str) -> str:
        """Reverse: 'YYYY-mm' -> 'YYYYMM' (integer)"""
        try:
            if not ym_str or pd.isna(ym_str):
                return None
            parts = ym_str.split("-")
            if len(parts) != 2:
                return None
            year, month = parts
            return int(f"{year}{month}")
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def reverse_year_month3(ym_str) -> str:
        """Reverse: 'YYYY-mm' -> 'YYYY.M' or 'YYYY.MM'"""
        try:
            if not ym_str or pd.isna(ym_str):
                return None
            parts = ym_str.split("-")
            if len(parts) != 2:
                return None
            year, month = parts
            # Remove leading zero from month
            month_int = int(month)
            return f"{year}.{month_int}"
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def reverse_date1(date_str) -> str:
        """Reverse: 'YYYY-MM-DD' -> 'YYYY年MM月DD日'"""
        try:
            if not date_str or pd.isna(date_str):
                return None
            parts = date_str.split("-")
            if len(parts) != 3:
                return None
            year, month, day = parts
            return f"{year}年{month}月{day}日"
        except (ValueError, AttributeError):
            return None
