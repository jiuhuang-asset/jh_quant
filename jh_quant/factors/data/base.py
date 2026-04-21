"""
Data Module for Factor Return Calculation
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

import pandas as pd
import numpy as np
from jh_quant.data import JHData, DataTypes
from ..config import FactorType, TimePeriod

def _get_market_by_code(code: str) -> str:
    """根据股票代码判断市场"""
    if code.startswith(("600", "601", "603", "688")):
        return "SH"
    elif code.startswith(("000", "002", "300", "003")):
        return "SZ"
    elif code.startswith(("430", "830", "870", "880")):
        return "BJ"
    else:
        return "SZ"


def _symbol_to_ts_code(symbol: str) -> str:
    """将6位股票代码转换为 tushare 格式"""
    market = _get_market_by_code(symbol)
    return f"{symbol}.{market}"


def _get_pit_report_period(trade_date: pd.Timestamp) -> pd.Timestamp:
    """
    根据交易日确定PIT(Point-in-Time)报告期

    规则:
    - 5月1日 - 8月31日: 使用 Q1 (报告期0331)
    - 9月1日 - 10月31日: 使用 Q2 (报告期0630)
    - 11月1日 - 次年4月30日: 使用 Q3 (报告期0930)

    Args:
        trade_date: 交易日期

    Returns:
        对应的报告期结束日期
    """
    month = trade_date.month
    year = trade_date.year

    if 5 <= month <= 8:
        # Q1: 使用当年3月31日
        return pd.Timestamp(year=year, month=3, day=31)
    elif 9 <= month <= 10:
        # Q2: 使用当年6月30日
        return pd.Timestamp(year=year, month=6, day=30)
    else:
        # Q3 (11月-4月): 使用去年9月30日
        return pd.Timestamp(year=year - 1, month=9, day=30)



class FactorReturnData(ABC):
    """
    抽象数据准备基类

    每个因子类型对应一个子类，实现 prepare_data(period) 方法
    支持真实数据和Mock数据测试
    """

    factor_type: FactorType  # 子类需要设置对应的因子类型

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        use_mock: bool = False,
        n_stocks: int = 30,
        start_date: str = "2023-01-01",
        end_date: str = "2024-12-31",
        seed: int = 42
    ):
        """
        初始化数据准备器

        Args:
            api_key: API密钥（可选，从环境变量读取）
            api_url: API地址（可选）
            use_mock: 是否使用Mock数据（用于测试）
            n_stocks: Mock股票数量
            start_date: Mock数据开始日期
            end_date: Mock数据结束日期
            seed: 随机种子
        """
        from os import getenv
        from dotenv import load_dotenv

        load_dotenv()

        self.api_key = api_key or getenv("JIUHUANG_API_KEY")
        self.api_url = api_url or getenv("JIUHUANG_API_URL", "https://data.jiuhuang.xyz")
        self._client = None

        self.use_mock = use_mock
        self.n_stocks = n_stocks
        self.mock_start = start_date
        self.mock_end = end_date
        self.seed = seed

        if use_mock:
            self._init_mock_data()

    def _init_mock_data(self):
        """初始化Mock数据"""
        np.random.seed(self.seed)
        self._mock_symbols = [f"{str(i).zfill(6)}" for i in range(1, self.n_stocks + 1)]
        self._mock_dates = pd.date_range(start=self.mock_start, end=self.mock_end, freq='B').tolist()

    def _get_client(self):
        """获取jh_data客户端"""
        if self._client is None:
            self._client = JHData(api_key=self.api_key, api_url=self.api_url)
            self._DataTypes = DataTypes
        return self._client

    def _to_dataframe(self, data) -> pd.DataFrame:
        """将jh_data返回的数据转换为DataFrame"""
        if data is None:
            return pd.DataFrame()
        if hasattr(data, 'columns') and hasattr(data, 'values'):
            return pd.DataFrame(data.values, columns=data.columns)
        return pd.DataFrame(data)

    def _sort_by_date(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize and sort date-based frames."""
        if df.empty:
            return df
        result = df.copy()
        if 'date' in result.columns:
            result['date'] = pd.to_datetime(result['date'])
            result = result.sort_values('date').reset_index(drop=True)
        return result

    def _fetch_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Shared SHIBOR loader."""
        client = self._get_client()
        kwargs = {}
        if start_date:
            kwargs['start'] = start_date
        if end_date:
            kwargs['end'] = end_date

        df = client.get_data(self._DataTypes.AK_MACRO_CHINA_SHIBOR_ALL, **kwargs)
        return self._sort_by_date(self._to_dataframe(df))

    def _get_trade_dates(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        获取交易日历数据。

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            包含 trade_date 列的 DataFrame
        """
        client = self._get_client()

        df = client.get_data(self._DataTypes.AK_TOOL_TRADE_DATE_HIST_SINA)
        df = self._to_dataframe(df)
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            # Filter by date range locally
            if start_date:
                df = df[df['trade_date'] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df['trade_date'] <= pd.to_datetime(end_date)]
        return df

    def _prepare_stock_returns(
        self,
        prices: pd.DataFrame,
        period: TimePeriod,
        trade_dates: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """Prepare daily or monthly stock returns from raw price data."""
        from ..data.transform import daily_to_monthly, calculate_returns

        prices = prices[prices['close'] > 0].copy()
        if period == TimePeriod.MONTHLY:
            return calculate_returns(daily_to_monthly(prices, trade_dates=trade_dates))
        return calculate_returns(prices)

    def _prepare_market_cap(
        self,
        daily_basic: pd.DataFrame,
        period: TimePeriod,
        trade_dates: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """Prepare daily or month-end market cap series."""
        daily_basic = daily_basic[daily_basic['close'] > 0].copy()
        if period == TimePeriod.MONTHLY:
            monthly = daily_basic.copy()
            monthly['year_month'] = monthly['date'].dt.to_period('M')

            # Get month-end value using last aggregation
            market_cap = monthly.groupby(['symbol', 'year_month'], sort=False).agg({
                'total_mv': 'last',
                'date': 'last',
            }).reset_index()
            market_cap.columns = ['symbol', 'year_month', 'mkt_cap', 'date']

            # If trade_dates provided, replace date with actual month-end trade date
            if trade_dates is not None and 'trade_date' in trade_dates.columns:
                trade_dates = trade_dates.copy()
                trade_dates['trade_date'] = pd.to_datetime(trade_dates['trade_date'])
                trade_dates['year_month'] = trade_dates['trade_date'].dt.to_period('M')
                month_end_trade_dates = trade_dates.groupby('year_month')['trade_date'].max().reset_index()
                month_end_trade_dates.columns = ['year_month', 'month_end_date']

                market_cap = market_cap.merge(month_end_trade_dates, on='year_month', how='left')
                market_cap['date'] = market_cap['month_end_date']
                market_cap = market_cap.drop(columns=['year_month', 'month_end_date'])
            else:
                market_cap = market_cap.drop(columns=['year_month'])

            return market_cap

        market_cap = daily_basic[['symbol', 'date', 'total_mv']].copy()
        market_cap.columns = ['symbol', 'date', 'mkt_cap']
        return market_cap

    def _calculate_roe_from_financials(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Calculate ROE from income statement and balance sheet data."""
        lrb = self.get_financial_data('LRB', start_date, end_date, symbols, trade_date=trade_date)
        zcfz = self.get_financial_data('ZCFZ', start_date, end_date, symbols, trade_date=trade_date)

        if lrb.empty or zcfz.empty:
            return pd.DataFrame()

        lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'ni': 'last'}).reset_index()
        zcfz_agg = zcfz.groupby(['symbol', 'date'], sort=False).agg({'be': 'last'}).reset_index()
        roe_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
        roe_df['roe'] = roe_df['ni'] / roe_df['be']
        return roe_df[['symbol', 'date', 'roe']].dropna()

    def _calculate_investment_from_financials(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Calculate investment growth from balance sheet data."""
        zcfz = self.get_financial_data('ZCFZ', start_date, end_date, symbols, trade_date=trade_date)
        if zcfz.empty:
            return pd.DataFrame()

        zcfz = zcfz.sort_values(['symbol', 'date'])
        zcfz['investment'] = zcfz.groupby('symbol')['ta'].pct_change()
        return zcfz[['symbol', 'date', 'investment']].dropna()

    def _get_industry(
        self,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取行业信息数据。

        通过调用 AK_STOCK_INDIVIDUAL_INFO_EM 获取股票行业分类。

        Args:
            symbols: 股票列表，如果为None则获取所有股票

        Returns:
            DataFrame with symbol, industry columns
        """
        client = self._get_client()
        kwargs = {}
        if symbols:
            kwargs['symbol'] = ','.join(symbols)

        df = client.get_data(self._DataTypes.AK_STOCK_INDIVIDUAL_INFO_EM, **kwargs)
        df = self._to_dataframe(df)

        if df.empty:
            return pd.DataFrame()

        if 'industry' not in df.columns:
            return pd.DataFrame()

        result = df[['symbol', 'industry']].dropna()
        # 行业数据是静态的，添加一个基准日期以便与股票日期匹配
        result['date'] = pd.Timestamp('1990-01-01')
        return result

    @abstractmethod
    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备因子计算所需的数据

        Args:
            period: 时间周期 ("M" 或 "D")
            start_date: 开始日期
            end_date: 结束日期
            symbols: 股票列表
            **kwargs: 额外参数

        Returns:
            Dict containing required DataFrames for factor calculation.
            每个子类返回不同的key，取决于因子所需数据
        """
        pass

    def _generate_mock_prices(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """生成Mock股价数据"""
        if symbols is None:
            symbols = self._mock_symbols

        if start_date:
            start = pd.to_datetime(start_date)
        else:
            start = pd.to_datetime(self.mock_start)

        if end_date:
            end = pd.to_datetime(end_date)
        else:
            end = pd.to_datetime(self.mock_end)

        dates = [d for d in self._mock_dates if start <= d <= end]
        if not dates:
            return pd.DataFrame()

        np.random.seed(self.seed)
        data = []

        for symbol in symbols:
            base_return = np.random.normal(0.0005, 0.02)
            volatility = np.random.uniform(0.015, 0.035)
            price = np.random.uniform(10, 100)

            for date in dates:
                return_day = np.random.normal(base_return, volatility)
                price = price * (1 + return_day)
                high = price * (1 + abs(np.random.normal(0, 0.01)))
                low = price * (1 - abs(np.random.normal(0, 0.01)))
                open_price = price * (1 + np.random.normal(0, 0.005))
                volume = np.random.randint(1000000, 10000000)
                amount = volume * price

                data.append({
                    'date': date,
                    'symbol': symbol,
                    'open': open_price,
                    'close': price,
                    'high': high,
                    'low': low,
                    'volume': volume,
                    'amount': amount,
                })

        return pd.DataFrame(data)

    def _generate_mock_daily_basic(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """生成Mock日频基础数据"""
        if symbols is None:
            symbols = self._mock_symbols

        if start_date:
            start = pd.to_datetime(start_date)
        else:
            start = pd.to_datetime(self.mock_start)

        if end_date:
            end = pd.to_datetime(end_date)
        else:
            end = pd.to_datetime(self.mock_end)

        dates = [d for d in self._mock_dates if start <= d <= end]
        if not dates:
            return pd.DataFrame()

        np.random.seed(self.seed)
        data = []

        for symbol in symbols:
            base_cap = np.random.uniform(1e9, 1e11)
            base_pe = np.random.uniform(10, 50)
            base_pb = np.random.uniform(1, 5)
            base_ps = np.random.uniform(1, 10)

            for date in dates:
                total_mv = base_cap * np.random.uniform(0.9, 1.1)
                circ_mv = total_mv * np.random.uniform(0.6, 0.9)
                close = np.random.uniform(10, 100)
                turnover_rate = np.random.uniform(0.5, 5)
                pe = base_pe * np.random.uniform(0.9, 1.1)
                pb = base_pb * np.random.uniform(0.9, 1.1)
                ps = base_ps * np.random.uniform(0.9, 1.1)
                ps_ttm = ps * np.random.uniform(0.9, 1.1)
                dv_ratio = np.random.uniform(0, 5)
                dv_ttm = dv_ratio * np.random.uniform(0.8, 1.2)
                total_share = total_mv / close * 10000
                float_share = circ_mv / close * 10000
                free_share = float_share * np.random.uniform(0.5, 0.9)
                turnover_rate_f = turnover_rate * np.random.uniform(0.8, 1.0)

                data.append({
                    'date': date,
                    'symbol': symbol,
                    'close': close,
                    'total_mv': total_mv,
                    'circ_mv': circ_mv,
                    'turnover_rate': turnover_rate,
                    'turnover_rate_f': turnover_rate_f,
                    'pe': pe,
                    'pe_ttm': pe * np.random.uniform(0.9, 1.1),
                    'pb': pb,
                    'ps': ps,
                    'ps_ttm': ps_ttm,
                    'dv_ratio': dv_ratio,
                    'dv_ttm': dv_ttm,
                    'total_share': total_share,
                    'float_share': float_share,
                    'free_share': free_share,
                })

        return pd.DataFrame(data)

    def get_price_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取股价数据（前复权）

        Returns:
            DataFrame with columns: [date, symbol, open, close, high, low, volume, amount]
        """
        if self.use_mock:
            return self._generate_mock_prices(symbols, start_date, end_date)

        client = self._get_client()
        kwargs = {}
        if start_date:
            kwargs['start'] = start_date
        if end_date:
            kwargs['end'] = end_date
        if symbols:
            kwargs['symbol'] = ','.join(symbols)

        df = client.get_data(self._DataTypes.AK_STOCK_ZH_A_HIST_QFQ, **kwargs)
        df = self._to_dataframe(df)

        if df.empty:
            return pd.DataFrame()

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])

        cols_to_keep = ['date', 'symbol', 'open', 'close', 'high', 'low', 'volume', 'amount']
        return df[[c for c in cols_to_keep if c in df.columns]].copy()

    def get_daily_basic_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取日频基础数据（市值、PE、PB等）

        Returns:
            DataFrame with columns including:
            - date: 交易日期
            - symbol: 股票代码
            - close: 收盘价
            - total_mv: 总市值（万元）
            - circ_mv: 流通市值（万元）
            - pe, pe_ttm, pb, ps, ps_ttm
            - turnover_rate, turnover_rate_f
            - total_share, float_share, free_share
            - bm: 账面市值比 (1/pb)
        """
        if self.use_mock:
            df = self._generate_mock_daily_basic(symbols, start_date, end_date)
            if not df.empty and 'pb' in df.columns:
                df['bm'] = 1 / df['pb']
            return df

        client = self._get_client()
        kwargs = {}
        if start_date:
            kwargs['start'] = start_date
        if end_date:
            kwargs['end'] = end_date
        if symbols:
            ts_codes = ','.join([_symbol_to_ts_code(s) for s in symbols])
            kwargs['ts_code'] = ts_codes

        df = client.get_data(self._DataTypes.TS_DAILY_BASIC, **kwargs)
        df = self._to_dataframe(df)

        if df.empty:
            return pd.DataFrame()

        if 'ts_code' in df.columns:
            df['symbol'] = df['ts_code'].str.extract(r'^(\d{6})')
            df = df.drop(columns=['ts_code'])

        if 'trade_date' in df.columns:
            df['date'] = pd.to_datetime(df['trade_date'])
            df = df.drop(columns=['trade_date'])

        if 'pb' in df.columns:
            df['bm'] = 1 / df['pb']

        return df

    def get_financial_data(
        self,
        data_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        max_ann_date: Optional[str] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        获取财务报表数据

        Args:
            data_type: 数据类型 (LRB=利润表, XJLL=现金流表, ZCFZ=资产负债表)
            start_date: 开始日期（报告期end_date的起始）
            end_date: 结束日期（报告期end_date的截止）
            symbols: 股票列表
            max_ann_date: 允许使用的最晚公告日期，用于避免前视偏差
            trade_date: 交易日期，用于PIT原则确定报告期。
                       如果指定，则只返回该交易日对应的特定报告期数据:
                       - 5月1日-8月31日: Q1(0331)
                       - 9月1日-10月31日: Q2(0630)
                       - 11月1日-次年4月30日: Q3(0930)

        Returns:
            DataFrame with financial data

        Note:
            财务报表数据必须确保公告日期(ann_date)不超过交易日期，
            以避免前视偏差 - 在T日计算因子时，只能使用ann_date <= T的财务数据。
        """

        type_map = {
            "LRB": DataTypes.AK_STOCK_LRB_EM,   # 利润表
            "XJLL": DataTypes.AK_STOCK_XJLL_EM, # 现金流量表
            "ZCFZ": DataTypes.AK_STOCK_ZCFZ_EM, # 资产负债表
        }

        dt = type_map.get(data_type.upper())
        if dt is None:
            raise ValueError(f"Unknown financial data type: {data_type}")

        if self.use_mock:
            return pd.DataFrame()

        client = self._get_client()
        kwargs = {}
        if symbols:
            kwargs['symbol'] = ','.join(symbols)

        # 财务报表数据量通常较小，直接获取所有数据后本地过滤
        df = client.get_data(dt, **kwargs)
        df = self._to_dataframe(df)

        if df.empty:
            return pd.DataFrame()

        if 'end_date' not in df.columns:
            return pd.DataFrame()

        # 转换日期
        df['end_date'] = pd.to_datetime(df['end_date'])
        if 'ann_date' in df.columns:
            df['ann_date'] = pd.to_datetime(df['ann_date'])

        # PIT原则：如果指定trade_date，只返回该交易日对应的报告期数据
        if trade_date:
            trade_dt = pd.to_datetime(trade_date)
            pit_period = _get_pit_report_period(trade_dt)
            df = df[df['end_date'] == pit_period]

            # PIT场景下也按公告日期过滤，避免前视偏差
            if max_ann_date:
                max_ann_dt = pd.to_datetime(max_ann_date)
                if 'ann_date' in df.columns:
                    df = df[df['ann_date'] <= max_ann_dt]
        else:
            # 非PIT模式：按报告期范围过滤
            if start_date:
                start_dt = pd.to_datetime(start_date)
                df = df[df['end_date'] >= start_dt]
            if end_date:
                end_dt = pd.to_datetime(end_date)
                df = df[df['end_date'] <= end_dt]

            # 按公告日期过滤以避免前视偏差
            if max_ann_date:
                max_ann_dt = pd.to_datetime(max_ann_date)
                if 'ann_date' in df.columns:
                    df = df[df['ann_date'] <= max_ann_dt]

        # 使用报告期作为date列
        df['date'] = df['end_date']

        # 保留必要的列：symbol, date, ann_date(用于后续可能的过滤)以及数值列
        cols_to_keep = ['symbol', 'date', 'ann_date']
        # 通用数值列
        numeric_cols = ['ni', 'be', 'ta', 'roe', 'bm', 'momentum', 'investment', 'idio_vol',
                        # LRB利润表相关列
                        'revenue', 'cogs', 'gross_profit', 'operating_expense', 'operating_cost',
                        'ebit', 'ebt', 'ni_yoy', 'revenue_yoy',
                        'selling_expense', 'admin_expenses', 'financial_expense']
        for col in numeric_cols:
            if col in df.columns:
                cols_to_keep.append(col)

        # 动态保留其他数值列（避免遗漏某些字段）
        for col in df.columns:
            if col not in cols_to_keep and df[col].dtype in ['float64', 'int64', 'float32', 'int32']:
                cols_to_keep.append(col)

        return df[cols_to_keep].dropna(subset=['date'])


# 具体因子数据准备类
class FF3Data(FactorReturnData):
    """FF3因子数据准备"""
    factor_type = FactorType.FF3

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备FF3因子所需数据

        FF3需要:
        - 股价数据 (计算收益率)
        - 市值数据 (计算SMB)
        - BM数据 (从TS_DAILY_BASIC的pb派生)

        Returns:
            Dict with keys: stock_returns, market_cap
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        bm_data = daily_basic[['symbol', 'date', 'bm']].dropna()

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'bm': bm_data,
            'shibor': shibor_data,
        }


class FF5Data(FactorReturnData):
    """FF5因子数据准备"""
    factor_type = FactorType.FF5

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备FF5因子所需数据

        FF5需要:
        - 股价数据 (计算收益率)
        - 市值数据 (计算SMB)
        - BM数据 (从pb派生)
        - ROE数据 (从利润表计算)
        - 投资数据 (从资产负债表计算)

        Returns:
            Dict with keys: stock_returns, market_cap, bm, roe, investment
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        bm_data = daily_basic[['symbol', 'date', 'bm']].dropna()

        # FF5使用Operating Profitability (op) 和 asset_growth
        op_data = self._calculate_op_from_financials(start_date, end_date, symbols)
        asset_growth_data = self._calculate_asset_growth_from_financials(start_date, end_date, symbols)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)
        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'bm': bm_data,
            'op': op_data,
            'asset_growth': asset_growth_data,
            'shibor': shibor_data,
        }

    def _calculate_op_from_financials(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        从财务报表计算Operating Profitability (OP)

        OP = 营业利润 / 所有者权益
        营业利润 = 营业收入 - 营业成本 - 费用
        如果财务报表中没有直接的营业利润列，则使用净利润替代

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            OP DataFrame with symbol, date, op columns
        """
        lrb = self.get_financial_data("LRB", start_date, end_date, symbols, trade_date=trade_date)
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)

        if lrb.empty or zcfz.empty:
            return pd.DataFrame()

        # 尝试使用营业利润，如果没有则使用净利润
        lrb_cols = lrb.columns.tolist()
        if 'op' in lrb_cols:
            profit_col = 'op'
        elif 'operating_profit' in lrb_cols:
            profit_col = 'operating_profit'
        elif 'oi' in lrb_cols:
            profit_col = 'oi'
        elif 'ni' in lrb_cols:
            profit_col = 'ni'  # 使用净利润作为代理
        else:
            # 使用可用的第一列作为利润代理
            profit_col = lrb_cols[-1] if lrb_cols else 'ni'

        lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({profit_col: 'last'}).reset_index()
        zcfz_agg = zcfz.groupby(['symbol', 'date'], sort=False).agg({'be': 'last'}).reset_index()

        op_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
        op_df['op'] = op_df[profit_col] / op_df['be']
        return op_df[['symbol', 'date', 'op']].dropna()

    def _calculate_asset_growth_from_financials(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        从资产负债表计算资产增长率 (asset_growth)

        asset_growth = (总资产_t - 总资产_{t-1}) / 总资产_{t-1}

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            Asset Growth DataFrame with symbol, date, asset_growth columns
        """
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)
        if zcfz.empty:
            return pd.DataFrame()

        zcfz = zcfz.sort_values(['symbol', 'date'])
        zcfz['asset_growth'] = zcfz.groupby('symbol')['ta'].pct_change()
        return zcfz[['symbol', 'date', 'asset_growth']].dropna()


class CARHARTData(FactorReturnData):
    """CARHART因子数据准备"""
    factor_type = FactorType.CARHART

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备CARHART因子所需数据

        CARHART需要:
        - 股价数据 (计算收益率和动量)
        - 市值数据
        - BM数据 (从pb派生)
        - 动量数据

        Returns:
            Dict with keys: stock_returns, market_cap, bm, momentum, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # BM数据 (从daily_basic的pb列派生)
        bm_data = daily_basic[['symbol', 'date', 'bm']].dropna()

        momentum = self._calculate_momentum(prices)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'bm': bm_data,
            'momentum': momentum,
            'shibor': shibor_data,
        }

    def _calculate_momentum(self, prices: pd.DataFrame) -> pd.DataFrame:
        """计算动量因子 (过去12个月收益率，不含最近一个月)"""
        import numpy as np

        prices = prices.sort_values(['symbol', 'date']).copy()
        # 将0值替换为NaN，避免pct_change除零错误
        prices['close'] = prices.groupby('symbol')['close'].transform(
            lambda x: x.replace(0, np.nan)
        )
        prices['return_12m'] = prices.groupby('symbol')['close'].pct_change(252)
        prices['return_1m'] = prices.groupby('symbol')['close'].pct_change(21)
        prices['momentum'] = prices['return_12m'] - prices['return_1m']

        prices['date'] = pd.to_datetime(prices['date'])
        return prices[['symbol', 'date', 'momentum']].dropna()


class NOVY_MARXData(FactorReturnData):
    """NOVY_MARX因子数据准备"""
    factor_type = FactorType.NOVY_MARX

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备NOVY_MARX因子所需数据

        NOVY_MARX使用:
        - bm: 账面市值比 (用于hml_adj，行业调整)
        - momentum: 动量因子 (用于umd)
        - gp_a: 毛利率 / 总资产 (用于盈利因子)
        - industry: 行业分类 (用于hml_adj行业调整)

        Returns:
            Dict with keys: stock_returns, market_cap, bm, momentum, gp_a, industry, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # BM数据
        bm_data = daily_basic[['symbol', 'date', 'bm']].dropna()

        # 动量数据
        momentum_data = self._calculate_momentum(prices)

        # 毛利率/总资产 (gp_a)
        gp_a_data = self._calculate_gp_a_from_financials(start_date, end_date, symbols)

        # 行业数据 (用于hml_adj行业调整)
        industry_data = self._get_industry(symbols)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'bm': bm_data,
            'momentum': momentum_data,
            'gp_a': gp_a_data,
            'industry': industry_data,
            'shibor': shibor_data,
        }

    def _calculate_momentum(self, prices: pd.DataFrame) -> pd.DataFrame:
        """计算动量因子 (过去12个月收益率，不含最近一个月)"""
        prices = prices.sort_values(['symbol', 'date']).copy()
        prices['close'] = prices.groupby('symbol')['close'].transform(
            lambda x: x.replace(0, np.nan)
        )
        prices['return_12m'] = prices.groupby('symbol')['close'].pct_change(252)
        prices['return_1m'] = prices.groupby('symbol')['close'].pct_change(21)
        prices['momentum'] = prices['return_12m'] - prices['return_1m']

        prices['date'] = pd.to_datetime(prices['date'])
        return prices[['symbol', 'date', 'momentum']].dropna()

    def _calculate_gp_a_from_financials(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        从财务报表计算 Gross Profit / Total Assets (GP/A)

        GP/A = 毛利 / 总资产 = (revenue - cogs) / ta

        优先级：
        1. (revenue - cogs) / ta (毛利 / 总资产)
        2. gross_profit / ta (直接毛利 / 总资产)
        3. (revenue - operating_expense) / ta (近似毛利 / 总资产)
        4. revenue / ta (简化代理)

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            GP/A DataFrame with symbol, date, gp_a columns
        """
        lrb = self.get_financial_data("LRB", start_date, end_date, symbols, trade_date=trade_date)
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)

        if lrb.empty or zcfz.empty:
            return pd.DataFrame()

        lrb_cols = lrb.columns.tolist()

        # 先获取总资产，用于计算 GP/A
        zcfz_agg = zcfz.groupby(['symbol', 'date'], sort=False).agg({'ta': 'last'}).reset_index()

        # 1. 优先使用 (revenue - cogs) / ta (毛利 / 总资产)
        if 'revenue' in lrb_cols and 'cogs' in lrb_cols:
            lrb = lrb.copy()
            lrb['gross_profit'] = lrb['revenue'] - lrb['cogs']
            lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'gross_profit': 'last'}).reset_index()
            gp_a_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
            gp_a_df['gp_a'] = gp_a_df['gross_profit'] / gp_a_df['ta']
            return gp_a_df[['symbol', 'date', 'gp_a']].dropna()

        # 2. 尝试使用 gross_profit / ta
        if 'gross_profit' in lrb_cols:
            lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'gross_profit': 'last'}).reset_index()
            gp_a_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
            gp_a_df['gp_a'] = gp_a_df['gross_profit'] / gp_a_df['ta']
            return gp_a_df[['symbol', 'date', 'gp_a']].dropna()

        # 3. 使用 (revenue - operating_expense) / ta 作为近似
        if 'revenue' in lrb_cols and 'operating_expense' in lrb_cols:
            lrb = lrb.copy()
            lrb['gross_profit'] = lrb['revenue'] - lrb['operating_expense']
            lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'gross_profit': 'last'}).reset_index()
            gp_a_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
            gp_a_df['gp_a'] = gp_a_df['gross_profit'] / gp_a_df['ta']
            return gp_a_df[['symbol', 'date', 'gp_a']].dropna()

        # 4. 简化代理: revenue / ta
        if 'revenue' in lrb_cols:
            lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'revenue': 'last'}).reset_index()
            gp_a_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
            gp_a_df['gp_a'] = gp_a_df['revenue'] / gp_a_df['ta']
            return gp_a_df[['symbol', 'date', 'gp_a']].dropna()

        return pd.DataFrame()



class HOU_XUE_ZHANGData(FactorReturnData):
    """HOU_XUE_ZHANG因子数据准备"""
    factor_type = FactorType.HOU_XUE_ZHANG

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备HOU_XUE_ZHANG (q-factor) 因子所需数据

        q-factor模型使用:
        - asset_growth: 资产增长率
        - roe_quarterly: 季度ROE (最近季度财报ROE)

        Returns:
            Dict with keys: stock_returns, market_cap, asset_growth, roe_quarterly
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # 季度ROE数据
        roe_quarterly_data = self._calculate_roe_quarterly(start_date, end_date, symbols)
        # 资产增长率
        asset_growth_data = self._calculate_asset_growth(start_date, end_date, symbols)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'asset_growth': asset_growth_data,
            'roe': roe_quarterly_data,
            'shibor': shibor_data,
        }

    def _calculate_roe_quarterly(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        从季度财务数据计算ROE

        使用PIT原则获取最近可用季度财务数据

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            ROE DataFrame with symbol, date, roe columns
        """
        lrb = self.get_financial_data("LRB", start_date, end_date, symbols, trade_date=trade_date)
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)

        if lrb.empty or zcfz.empty:
            return pd.DataFrame()

        lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'ni': 'last'}).reset_index()
        zcfz_agg = zcfz.groupby(['symbol', 'date'], sort=False).agg({'be': 'last'}).reset_index()

        roe_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
        roe_df['roe'] = roe_df['ni'] / roe_df['be']

        return roe_df[['symbol', 'date', 'roe']].dropna()

    def _calculate_asset_growth(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        从资产负债表计算资产增长率

        asset_growth = (总资产_t - 总资产_{t-1}) / 总资产_{t-1}

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            Asset Growth DataFrame with symbol, date, asset_growth columns
        """
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)
        if zcfz.empty:
            return pd.DataFrame()

        zcfz = zcfz.sort_values(['symbol', 'date'])
        zcfz['asset_growth'] = zcfz.groupby('symbol')['ta'].pct_change()
        return zcfz[['symbol', 'date', 'asset_growth']].dropna()



class DHSData(FactorReturnData):
    """DHS因子数据准备"""
    factor_type = FactorType.DHS

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备DHS (Daniel-Hirshleifer-Sun) 行为金融因子所需数据

        DHS模型使用:
        - pead: 盈余公告漂移 (Post-Earnings Announcement Drift, SUE)
        - fin: 融资因子 (Net Share Issuance)

        Returns:
            Dict with keys: stock_returns, market_cap, pead, fin
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # 盈余公告漂移 (pead/SUE)
        pead_data = self._calculate_pead(start_date, end_date, symbols)
        # 融资因子 (net share issuance)
        fin_data = self._calculate_fin_from_financials(start_date, end_date, symbols)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'pead': pead_data,
            'fin': fin_data,
            'shibor': shibor_data,
        }

    def _calculate_pead(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        计算盈余公告漂移因子 (Post-Earnings Announcement Drift, PEAD)

        使用标准化未预期盈余 (SUE) 作为代理:
        SUE = (EPS_t - EPS_{t-4}) / std(EPS_t - EPS_{t-4})

        如果没有EPS数据，使用净利润变化率作为代理

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            PEAD DataFrame with symbol, date, pead columns
        """
        lrb = self.get_financial_data("LRB", start_date, end_date, symbols, trade_date=trade_date)
        if lrb.empty:
            return pd.DataFrame()

        # 尝试获取EPS列，如果没有则使用净利润
        lrb_cols = lrb.columns.tolist()
        if 'eps' in lrb_cols:
            profit_col = 'eps'
        elif 'ni' in lrb_cols:
            profit_col = 'ni'
        else:
            profit_col = lrb_cols[-1] if lrb_cols else 'ni'

        lrb = lrb.sort_values(['symbol', 'date'])
        lrb['profit_qoq'] = lrb.groupby('symbol')[profit_col].diff(4)  # 4季度变化

        # 计算标准化未预期盈余
        lrb['pead'] = lrb.groupby('symbol')['profit_qoq'].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
        )

        return lrb[['symbol', 'date', 'pead']].dropna()

    def _calculate_fin_from_financials(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        计算融资因子 (Net Share Issuance)

        净股票发行率 = 股本变化率作为融资活动的代理

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            Fin DataFrame with symbol, date, fin columns
        """
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)
        if zcfz.empty:
            return pd.DataFrame()

        # 尝试获取股本/股份数据
        zcfz_cols = zcfz.columns.tolist()
        if 'shares' in zcfz_cols:
            share_col = 'shares'
        elif 'total_share' in zcfz_cols:
            share_col = 'total_share'
        elif 'share_capital' in zcfz_cols:
            share_col = 'share_capital'
        else:
            # 如果没有股本数据，使用总资产变化率作为代理
            zcfz = zcfz.sort_values(['symbol', 'date'])
            zcfz['fin'] = zcfz.groupby('symbol')['ta'].pct_change()
            return zcfz[['symbol', 'date', 'fin']].dropna()

        zcfz = zcfz.sort_values(['symbol', 'date'])
        zcfz['fin'] = zcfz.groupby('symbol')[share_col].pct_change()
        return zcfz[['symbol', 'date', 'fin']].dropna()


class CAPMData(FactorReturnData):
    """CAPM因子数据准备"""

    factor_type = FactorType.CAPM

    # 中证全指
    INDEX_SYMBOL = "sh000985"

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备CAPM因子所需数据

        CAPM模型：R_i - R_f = alpha + beta * (R_m - R_f) + epsilon
        - R_i: 股票收益率
        - R_f: 无风险收益率（使用SHIBOR 1个月期）
        - R_m: 市场收益率（使用上证指数）

        Args:
            period: 时间周期 ('M' 或 'D')
            start_date: 开始日期
            end_date: 结束日期
            symbols: 股票代码列表

        Returns:
            Dict with keys: stock_returns, market_return, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        # 1. 获取股票收益率
        prices = self.get_price_data(start_date, end_date, symbols)
        if prices.empty:
            raise ValueError("无法获取股票价格数据")

        prices = prices[prices['close'] > 0].copy()

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        if period == TimePeriod.MONTHLY:
            monthly_prices = daily_to_monthly(prices, trade_dates=trade_dates)
            stock_returns = calculate_returns(monthly_prices)
        else:
            stock_returns = calculate_returns(prices)

        # 2. 获取上证指数数据（市场收益率）
        index_data = self._get_index_data(start_date, end_date)
        if index_data.empty:
            raise ValueError("无法获取上证指数数据")

        # 3. 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        # 4. 计算市场超额收益率
        market_return = self._calculate_market_excess_return(
            index_data, shibor_data, period
        )

        return {
            'stock_returns': stock_returns,
            'market_return': market_return,
            'shibor': shibor_data,
        }

    def _get_index_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """获取上证指数历史数据"""
        client = self._get_client()
        kwargs = {'symbol': self.INDEX_SYMBOL}
        if start_date:
            kwargs['start'] = start_date
        if end_date:
            kwargs['end'] = end_date

        df = client.get_data(self._DataTypes.AK_STOCK_ZH_INDEX_DAILY_EM, **kwargs)
        df = self._to_dataframe(df)

        if df.empty:
            return pd.DataFrame()

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])

        return df.sort_values('date').reset_index(drop=True)

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def _calculate_market_excess_return(
        self,
        index_data: pd.DataFrame,
        shibor_data: pd.DataFrame,
        period: TimePeriod
    ) -> pd.DataFrame:
        """
        计算市场超额收益率

        对于月度：R_mkt_monthly - R_f_monthly
        对于日度：R_mkt_daily - R_f_daily

        SHIBOR为年化百分比，转换方式：
        - 日度Rf = SHIBOR_ON / 360
        - 月度Rf = SHIBOR_1M / 12
        """
        from ..data.transform import daily_to_monthly

        if period == TimePeriod.MONTHLY:
            # 转换指数为月度
            index_monthly = daily_to_monthly(index_data)
            index_monthly = index_monthly.sort_values('date')
            index_monthly['mkt_return'] = index_monthly['close'].pct_change()

            # 规范化日期：去除时间成分，只保留日期
            index_monthly['date'] = pd.to_datetime(index_monthly['date'].dt.date)

            # 月度SHIBOR：取每月最后一个值，转换为月度收益率
            shibor_monthly = shibor_data.copy()
            shibor_monthly['date'] = pd.to_datetime(shibor_monthly['date'].dt.date)
            shibor_monthly['year_month'] = shibor_monthly['date'].dt.to_period('M')

            # 对于每月，使用该月最后一个SHIBOR数据点的日期作为参考日期
            shibor_by_month = shibor_monthly.groupby('year_month').agg({
                'm1_rate': 'last',  # 1个月期SHIBOR
                'date': 'last'      # 该月最后一个SHIBOR日期
            }).reset_index()
            shibor_by_month['rf_monthly'] = shibor_by_month['m1_rate'] / 100 / 12
            # date列已经是该月最后一个SHIBOR日期

            # 合并计算超额收益
            result = index_monthly.merge(
                shibor_by_month[['date', 'rf_monthly']],
                on='date',
                how='left'
            )
            result['mkt_excess'] = result['mkt_return'] - result['rf_monthly']
            result = result.dropna(subset=['mkt_excess'])

            return result[['date', 'mkt_return', 'mkt_excess']]

        else:  # DAILY
            index_daily = index_data.sort_values('date').copy()
            index_daily['mkt_return'] = index_daily['close'].pct_change()
            index_daily['date'] = pd.to_datetime(index_daily['date'].dt.date)

            # 日度SHIBOR：使用隔夜SHIBOR，转换为日度收益率
            shibor_daily = shibor_data.copy()
            shibor_daily['date'] = pd.to_datetime(shibor_daily['date'].dt.date)
            shibor_daily['rf_daily'] = shibor_daily['on_rate'] / 100 / 360

            # 合并
            result = index_daily.merge(
                shibor_daily[['date', 'rf_daily']],
                on='date',
                how='left'
            )
            result['mkt_excess'] = result['mkt_return'] - result['rf_daily']
            result = result.dropna(subset=['mkt_excess'])

            return result[['date', 'mkt_return', 'mkt_excess']]


class CH3Data(FactorReturnData):
    """CH3 (中国三因子模型) 数据准备"""

    factor_type = FactorType.CH3

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备CH3 (中国三因子模型) 所需数据

        CH3模型使用:
        - mkt_cap: 市值
        - bm: 账面市值比 (用于VMG)
        - is_st: 剔除ST股

        VMG (Value Minus Growth) 因子核心：在计算价值因子时剔除"壳价值"干扰
        价值因子在分组前先剔除市场市值最小的30%股票

        Returns:
            Dict with keys: stock_returns, market_cap, bm, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # BM数据
        bm_data = daily_basic[['symbol', 'date', 'bm']].dropna()

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'bm': bm_data,
            'shibor': shibor_data,
        }


class SY4Data(FactorReturnData):
    """SY4 (Stambaugh-Yuan四因子模型) 数据准备"""

    factor_type = FactorType.SY4

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备SY4 (Stambaugh-Yuan四因子模型) 所需数据

        SY4模型使用:
        - mgmt: 管理因子 (Management Cluster)
          综合：资产增长率、应计项、净股票发行等指标
        - perf: 绩效因子 (Performance Cluster)
          综合：ROE、资产周转率变动、财务困境指标

        Returns:
            Dict with keys: stock_returns, market_cap, mgmt, perf, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # 管理因子指标 (mgmt)
        mgmt_data = self._calculate_mgmt_factor(start_date, end_date, symbols)
        # 绩效因子指标 (perf)
        perf_data = self._calculate_perf_factor(start_date, end_date, symbols)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'mgmt': mgmt_data,
            'perf': perf_data,
            'shibor': shibor_data,
        }

    def _calculate_mgmt_factor(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        计算管理因子 (Management Cluster)

        综合指标包含：
        - 资产增长率 (asset_growth)
        - 应计项 (operating_accruals)
        - 净股票发行 (net_share_issuance)

        这里使用资产增长率作为mgmt代理

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            MGMT DataFrame with symbol, date, mgmt columns
        """
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)
        if zcfz.empty:
            return pd.DataFrame()

        # 资产增长率
        zcfz = zcfz.sort_values(['symbol', 'date'])
        zcfz['asset_growth'] = zcfz.groupby('symbol')['ta'].pct_change()

        # 使用资产增长率作为mgmt代理
        zcfz['mgmt'] = zcfz['asset_growth']
        return zcfz[['symbol', 'date', 'mgmt']].dropna()

    def _calculate_perf_factor(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        trade_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        计算绩效因子 (Performance Cluster)

        综合指标包含：
        - ROE
        - 资产周转率变动
        - 财务困境指标

        这里使用ROE作为perf代理

        Args:
            start_date: 财务数据起始日期
            end_date: 财务数据结束日期
            symbols: 股票列表
            trade_date: 交易日期，用于PIT原则确定报告期

        Returns:
            PERF DataFrame with symbol, date, perf columns
        """
        lrb = self.get_financial_data("LRB", start_date, end_date, symbols, trade_date=trade_date)
        zcfz = self.get_financial_data("ZCFZ", start_date, end_date, symbols, trade_date=trade_date)

        if lrb.empty or zcfz.empty:
            return pd.DataFrame()

        # ROE
        lrb_agg = lrb.groupby(['symbol', 'date'], sort=False).agg({'ni': 'last'}).reset_index()
        zcfz_agg = zcfz.groupby(['symbol', 'date'], sort=False).agg({'be': 'last'}).reset_index()
        perf_df = lrb_agg.merge(zcfz_agg, on=['symbol', 'date'], how='inner')
        perf_df['perf'] = perf_df['ni'] / perf_df['be']
        return perf_df[['symbol', 'date', 'perf']].dropna()


class REVERSALData(FactorReturnData):
    """REVERSAL (短期反转模型) 数据准备"""

    factor_type = FactorType.REVERSAL

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备REVERSAL (短期反转模型) 所需数据

        REVERSAL模型使用:
        - rev: 过去20日累计收益率（反转因子）
          做空涨幅最大的组，做多跌幅最大的组

        Returns:
            Dict with keys: stock_returns, market_cap, rev, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # 计算20日反转因子 (短期反转)
        rev_data = self._calculate_reversal(prices)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'rev': rev_data,
            'shibor': shibor_data,
        }

    def _calculate_reversal(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        计算短期反转因子 (过去20日累计收益率)

        Args:
            prices: 日频价格数据

        Returns:
            REVERSAL DataFrame with symbol, date, rev columns
        """
        prices = prices.sort_values(['symbol', 'date']).copy()
        # 将0值替换为NaN，避免pct_change除零错误
        prices['close'] = prices.groupby('symbol')['close'].transform(
            lambda x: x.replace(0, np.nan)
        )
        # 过去20日累计收益率
        prices['rev'] = prices.groupby('symbol')['close'].pct_change(20)

        prices['date'] = pd.to_datetime(prices['date'])
        return prices[['symbol', 'date', 'rev']].dropna()


class LOW_VOLData(FactorReturnData):
    """LOW_VOL (低波动模型) 数据准备"""

    factor_type = FactorType.LOW_VOL

    def _get_shibor_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        return self._fetch_shibor_data(start_date, end_date)

    def prepare_data(
        self,
        period: Union[str, TimePeriod] = "M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        准备LOW_VOL (低波动模型) 所需数据

        LOW_VOL模型使用:
        - ivol: 特质波动率 (Idiosyncratic Volatility)
          通过CAPM或FF3模型对日收益率做残差回归，取残差的标准差
          低波动股票预期收益更高

        Returns:
            Dict with keys: stock_returns, market_cap, ivol, shibor
        """
        from ..data.transform import daily_to_monthly, calculate_returns

        if isinstance(period, str):
            period = TimePeriod(period)

        prices = self.get_price_data(start_date, end_date, symbols)
        daily_basic = self.get_daily_basic_data(start_date, end_date, symbols)

        if prices.empty or daily_basic.empty:
            raise ValueError("无法获取价格或市值数据")

        # 获取交易日历（用于月度化时确定统一的月末交易日）
        trade_dates = self._get_trade_dates(start_date, end_date)

        stock_returns = self._prepare_stock_returns(prices, period, trade_dates)
        market_cap = self._prepare_market_cap(daily_basic, period, trade_dates)

        # 计算特质波动率
        ivol_data = self._calculate_idiosyncratic_volatility(prices)

        # 获取SHIBOR数据（无风险收益率）
        shibor_data = self._get_shibor_data(start_date, end_date)

        return {
            'stock_returns': stock_returns,
            'market_cap': market_cap,
            'ivol': ivol_data,
            'shibor': shibor_data,
        }

    def _calculate_idiosyncratic_volatility(self, prices: pd.DataFrame) -> pd.DataFrame:
        """
        计算特质波动率 (Idiosyncratic Volatility)

        使用日收益率的标准差作为特质波动率的代理
        简化计算：直接使用日收益率的标准差

        Args:
            prices: 日频价格数据

        Returns:
            IVOL DataFrame with symbol, date, ivol columns
        """
        prices = prices.sort_values(['symbol', 'date']).copy()
        # 将0值替换为NaN
        prices['close'] = prices.groupby('symbol')['close'].transform(
            lambda x: x.replace(0, np.nan)
        )
        # 计算日收益率
        prices['daily_return'] = prices.groupby('symbol')['close'].pct_change()

        # 计算过去20日收益率标准差作为iv
        prices['ivol'] = prices.groupby('symbol')['daily_return'].transform(
            lambda x: x.rolling(window=20, min_periods=10).std()
        )

        prices['date'] = pd.to_datetime(prices['date'])
        return prices[['symbol', 'date', 'ivol']].dropna()


# 数据类注册表：因子类型 -> 数据类
DATA_CLASS_REGISTRY: Dict[FactorType, type] = {
    FactorType.FF3: FF3Data,
    FactorType.FF5: FF5Data,
    FactorType.CARHART: CARHARTData,
    FactorType.NOVY_MARX: NOVY_MARXData,
    FactorType.HOU_XUE_ZHANG: HOU_XUE_ZHANGData,
    FactorType.DHS: DHSData,
    FactorType.CAPM: CAPMData,
    FactorType.CH3: CH3Data,
    FactorType.SY4: SY4Data,
    FactorType.REVERSAL: REVERSALData,
    FactorType.LOW_VOL: LOW_VOLData,
}


def get_factor_data_class(factor_type: FactorType) -> type:
    """获取因子对应的数据准备类"""
    if factor_type not in DATA_CLASS_REGISTRY:
        raise ValueError(f"Unknown factor type: {factor_type}")
    return DATA_CLASS_REGISTRY[factor_type]


# 导出
__all__ = [
    "FactorReturnData",
    "FF3Data",
    "FF5Data",
    "CARHARTData",
    "NOVY_MARXData",
    "HOU_XUE_ZHANGData",
    "DHSData",
    "CAPMData",
    "CH3Data",
    "SY4Data",
    "REVERSALData",
    "LOW_VOLData",
    "get_factor_data_class",
    "DATA_CLASS_REGISTRY",
]
