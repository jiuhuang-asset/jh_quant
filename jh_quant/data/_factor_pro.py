"""
内部模块：将 ts_daily / ts_daily_qfq / ts_daily_hfq / ts_daily_basic 四张基表
衍生计算为 ts_stk_factor_pro 的全部列。

背景：
  jiuhaung data 服务端已停止生成 ts_stk_factor_pro 数据。服务端的数据在
  2025-05-30 之后不再更新。本模块在不依赖服务端 ts_stk_factor_pro 的前提
  下，完全从基表复现该数据集的全部字段。

差异较大的指标（设 NaN，不计算）：
  以下指标需要 Tushare 全量历史数据起点一致 或 依赖 Tushare 内部实现细节
  才能精确匹配，当前不计算，保留列但返回 NaN：
  - asi_* / asit_*       Wilder 的 Swing Index 公式复杂，Tushare 版本不明
  - cr_*                 CR 中位价定义不确定
  - dmi_adx_* / dmi_adxr_*  ADX/ADXR 需要 Wilder 平滑且依赖全历史
  - obv_*                OBV 绝对值依赖历史起点，每日变化量正确（已归一化但偏移无法确定）
  - xsii_td1/2/3/4_*     DeMark TD Sequential，Tushare 内部实现细节不明
  - taq_down/up/mid_*    TAQ 通道 = MA(20) ± 2*ATR，ATR 依赖 Wilder 平滑起点

用法（内部）:
  from jh_quant.data._factor_pro import derive_factor_pro
  df = derive_factor_pro(jhd, ts_code="600000.SH", start="2024-01-01", end="2025-05-30")
"""
import numpy as np
import pandas as pd
from typing import Optional

# ---- 工具函数 ----


def _ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, n: int, m: float = 1.0) -> pd.Series:
    """递归 SMA: S_t = (m * X_t + (n-m) * S_{t-1}) / n"""
    result = series.copy().astype(float)
    result.iloc[:n] = series.iloc[:n].mean()
    for i in range(n, len(series)):
        result.iloc[i] = (m * series.iloc[i] + (n - m) * result.iloc[i - 1]) / n
    return result


def _tp(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return (high + low + close) / 3.0


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder 平滑: 首值是前 N 期平均，后续 S_t = (X_t + (N-1)*S_{t-1}) / N"""
    n = len(series)
    result = pd.Series(np.nan, index=series.index, dtype=float)
    if n < period:
        return result
    result.iloc[period - 1] = series.iloc[:period].mean()
    prev = result.iloc[period - 1]
    alpha = 1.0 / period
    one_minus = 1.0 - alpha
    for i in range(period, n):
        prev = alpha * series.iloc[i] + one_minus * prev
        result.iloc[i] = prev
    return result


# ---- 指标计算器 ----


class _IndicatorCalc:
    """为单套价格（bfq/hfq/qfq）计算全部技术指标"""

    def __init__(self, o, h, l, c, v, amt):
        self.o = o
        self.h = h
        self.l = l
        self.c = c
        self.v = v
        self.amt = amt

    # -- MA --
    def _ma_n(self, n):
        return _ma(self.c, n)

    # -- EMA --
    def _ema_n(self, n):
        return _ema(self.c, n)

    # -- MACD --
    def macd(self):
        dif = _ema(self.c, 12) - _ema(self.c, 26)
        dea = _ema(dif, 9)
        return dif, dea, 2.0 * (dif - dea)

    # -- KDJ (9,3,3) --
    def kdj(self):
        lo = self.l.rolling(9, min_periods=9).min()
        hi = self.h.rolling(9, min_periods=9).max()
        rsv = (self.c - lo) / (hi - lo) * 100
        rsv = rsv.fillna(50)
        k = _sma(rsv, 3, 1)
        d = _sma(k, 3, 1)
        return k, d, 3.0 * k - 2.0 * d

    # -- RSI --
    def rsi(self, period: int):
        delta = self.c.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        return 100.0 - (100.0 / (1.0 + rs))

    # -- BOLL (20,2) --
    def boll(self):
        mid = _ma(self.c, 20)
        std = self.c.rolling(20, min_periods=20).std(ddof=0)
        return mid + 2.0 * std, mid, mid - 2.0 * std

    # -- ATR (14) --
    def atr(self):
        tr1 = self.h - self.l
        tr2 = (self.h - self.c.shift(1)).abs()
        tr3 = (self.l - self.c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return _wilder_smooth(tr, 14)

    # -- BIAS --
    def bias(self, period: int):
        m = _ma(self.c, period)
        return (self.c - m) / m * 100.0

    # -- CCI (14) --
    def cci(self):
        tp = _tp(self.h, self.l, self.c)
        ma_tp = _ma(tp, 14)
        md = tp.rolling(14, min_periods=14).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        return (tp - ma_tp) / (0.015 * md)

    # -- DMI (14) --
    def dmi(self):
        up = self.h.diff()
        dn = -self.l.diff()
        p_dm = up.where(up > dn, 0.0)
        m_dm = dn.where(dn > up, 0.0)
        tr1 = self.h - self.l
        tr2 = (self.h - self.c.shift(1)).abs()
        tr3 = (self.l - self.c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        a14 = _wilder_smooth(tr, 14)
        pdi = _wilder_smooth(p_dm, 14) / a14 * 100.0
        mdi = _wilder_smooth(m_dm, 14) / a14 * 100.0
        dx = (pdi - mdi).abs() / (pdi + mdi) * 100.0
        adx = _wilder_smooth(dx, 14)
        adxr = (adx + adx.shift(14)) / 2.0
        return pdi, mdi, adx, adxr

    # -- WR (10) / WR1 (6) --
    def wr(self, p: int):
        hi = self.h.rolling(p, min_periods=p).max()
        lo = self.l.rolling(p, min_periods=p).min()
        return (hi - self.c) / (hi - lo) * 100.0

    # -- MFI (14) --
    def mfi(self):
        tp = _tp(self.h, self.l, self.c)
        mf = tp * self.v
        diff = tp.diff()
        pos = mf.where(diff > 0, 0.0).rolling(14, min_periods=14).sum()
        neg = mf.where(diff < 0, 0.0).rolling(14, min_periods=14).sum()
        mr = pos / neg.replace(0, np.nan)
        return 100.0 - (100.0 / (1.0 + mr))

    # -- ROC (12) --
    def roc(self):
        v = (self.c / self.c.shift(12) - 1.0) * 100.0
        return v, _ma(v, 6)

    # -- MTM (12) --
    def mtm(self):
        v = self.c - self.c.shift(12)
        return v, _ma(v, 6)

    # -- PSY (12) --
    def psy(self):
        up = (self.c > self.c.shift(1)).rolling(12, min_periods=12).sum()
        v = up / 12.0 * 100.0
        return v, _ma(v, 6)

    # -- DPO (20) --
    def dpo(self):
        v = self.c - _ma(self.c, 20).shift(10)
        return v, _ma(v, 6)

    # -- BBI --
    def bbi(self):
        return (_ma(self.c, 3) + _ma(self.c, 6) + _ma(self.c, 12) + _ma(self.c, 24)) / 4.0

    # -- KTN (Keltner, 20) --
    def ktn(self):
        tr1 = self.h - self.l
        tr2 = (self.h - self.c.shift(1)).abs()
        tr3 = (self.l - self.c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        a20 = _wilder_smooth(tr, 20)
        mid = _ema(self.c, 20)
        return mid + 2.0 * a20, mid, mid - 2.0 * a20

    # -- TRIX (12) --
    def trix(self):
        tr = _ema(_ema(_ema(self.c, 12), 12), 12)
        v = (tr / tr.shift(1) - 1.0) * 100.0
        return v, _ma(v, 20)

    # -- VR (26) --
    def vr(self):
        d = self.c.diff()
        av = self.v.where(d > 0, 0.0).rolling(26, min_periods=26).sum()
        bv = self.v.where(d < 0, 0.0).rolling(26, min_periods=26).sum()
        cv = self.v.where(d == 0, 0.0).rolling(26, min_periods=26).sum()
        return (av + 0.5 * cv) / (bv + 0.5 * cv).replace(0, np.nan) * 100.0

    # -- EMV (14) --
    def emv(self):
        mid = (self.h + self.l) / 2.0
        hl = self.h - self.l
        br = self.v / hl.replace(0, np.nan) / 10000.0
        v = (mid - mid.shift(1)) / br.replace(0, np.nan)
        return v, _ma(v, 14)

    # -- BRAR (26) --
    def brar(self):
        ho = self.h - self.o
        ol = self.o - self.l
        ar = ho.rolling(26, min_periods=26).sum() / ol.rolling(26, min_periods=26).sum().replace(0, np.nan) * 100
        pc = self.c.shift(1)
        hp = (self.h - pc).clip(lower=0)
        pl = (pc - self.l).clip(lower=0)
        br = hp.rolling(26, min_periods=26).sum() / pl.rolling(26, min_periods=26).sum().replace(0, np.nan) * 100
        return ar, br

    # -- MASS (25) --
    def mass(self):
        hl = self.h - self.l
        e1 = _ema(hl, 9)
        e2 = _ema(e1, 9)
        v = (e1 / e2.replace(0, np.nan)).rolling(25, min_periods=25).sum()
        return v, _ma(v, 9)

    # -- DFMA --
    def dfma(self):
        dif = _ema(self.c, 12) - _ema(self.c, 26)
        return dif, _ema(dif, 9)

    # -- 涨跌天数 --
    def updown_toplow_days(self):
        n = len(self.c)
        up = pd.Series(0, index=self.c.index)
        dn = pd.Series(0, index=self.c.index)
        top = pd.Series(0, index=self.c.index)
        low = pd.Series(0, index=self.c.index)

        run_max = None
        run_min = None
        for i in range(n):
            if i == 0:
                continue
            ci, ci1 = self.c.iloc[i], self.c.iloc[i - 1]
            # up/down
            if ci > ci1:
                up.iloc[i] = up.iloc[i - 1] + 1
            else:
                up.iloc[i] = 0
            if ci < ci1:
                dn.iloc[i] = dn.iloc[i - 1] + 1
            else:
                dn.iloc[i] = 0
            # top/low
            if run_max is None or ci > run_max:
                run_max = ci
                top.iloc[i] = top.iloc[i - 1] + 1 if i > 0 else 1
            else:
                top.iloc[i] = 0
            if run_min is None or ci < run_min:
                run_min = ci
                low.iloc[i] = low.iloc[i - 1] + 1 if i > 0 else 1
            else:
                low.iloc[i] = 0

        return up.astype(float), dn.astype(float), top.astype(float), low.astype(float)

    # -- TAQ --
    def taq(self):
        mid = _ma(self.c, 20)
        a = self.atr()
        return mid + 2.0 * a, mid, mid - 2.0 * a

    # ================================================================
    # 批量输出
    # ================================================================

    def compute_all(self) -> pd.DataFrame:
        r = pd.DataFrame(index=self.c.index)

        # MA
        r["ma_5"] = self._ma_n(5)
        r["ma_10"] = self._ma_n(10)
        r["ma_20"] = self._ma_n(20)
        r["ma_30"] = self._ma_n(30)
        r["ma_60"] = self._ma_n(60)
        r["ma_90"] = self._ma_n(90)
        r["ma_250"] = self._ma_n(250)

        # EMA
        r["ema_5"] = self._ema_n(5)
        r["ema_10"] = self._ema_n(10)
        r["ema_20"] = self._ema_n(20)
        r["ema_30"] = self._ema_n(30)
        r["ema_60"] = self._ema_n(60)
        r["ema_90"] = self._ema_n(90)
        r["ema_250"] = self._ema_n(250)

        # EXPMA
        r["expma_12"] = self._ema_n(12)
        r["expma_50"] = self._ema_n(50)

        # MACD
        dif, dea, m = self.macd()
        r["macd_dif"] = dif
        r["macd_dea"] = dea
        r["macd"] = m

        # KDJ
        k, d, j = self.kdj()
        r["kdj_k"] = k
        r["kdj_d"] = d
        r["kdj"] = j

        # RSI
        r["rsi_6"] = self.rsi(6)
        r["rsi_12"] = self.rsi(12)
        r["rsi_24"] = self.rsi(24)

        # BOLL
        up, mid, lo = self.boll()
        r["boll_upper"] = up
        r["boll_mid"] = mid
        r["boll_lower"] = lo

        # ATR
        r["atr"] = self.atr()

        # BIAS
        r["bias1"] = self.bias(6)
        r["bias2"] = self.bias(12)
        r["bias3"] = self.bias(24)

        # CCI
        r["cci"] = self.cci()

        # DMI — 注：PDI/MDI/ADX/ADXR 全部依赖 Wilder 平滑的全历史起点
        # 与 Tushare 差异较大，不计算，设为 NaN
        # — 如果你接受近似值，可解开下面注释 —
        # pdi, mdi, adx, adxr = self.dmi()
        # r["dmi_pdi"] = pdi
        # r["dmi_mdi"] = mdi
        # r["dmi_adx"] = adx
        # r["dmi_adxr"] = adxr

        # WR
        r["wr"] = self.wr(10)
        r["wr1"] = self.wr(6)

        # MFI
        r["mfi"] = self.mfi()

        # ROC / MAROC
        v, mv = self.roc()
        r["roc"] = v
        r["maroc"] = mv

        # MTM / MTMMA
        v, mv = self.mtm()
        r["mtm"] = v
        r["mtmma"] = mv

        # PSY / PSYMA
        v, mv = self.psy()
        r["psy"] = v
        r["psyma"] = mv

        # DPO / MADPO
        v, mv = self.dpo()
        r["dpo"] = v
        r["madpo"] = mv

        # BBI
        r["bbi"] = self.bbi()

        # KTN
        up, mid, lo = self.ktn()
        r["ktn_upper"] = up
        r["ktn_mid"] = mid
        r["ktn_down"] = lo

        # TRIX / TRMA
        v, mv = self.trix()
        r["trix"] = v
        r["trma"] = mv

        # VR
        r["vr"] = self.vr()

        # EMV / MAEMV
        v, mv = self.emv()
        r["emv"] = v
        r["maemv"] = mv

        # BRAR
        ar, br = self.brar()
        r["brar_ar"] = ar
        r["brar_br"] = br

        # MASS
        v, mv = self.mass()
        r["mass"] = v
        r["ma_mass"] = mv

        # DFMA
        dif, difma = self.dfma()
        r["dfma_dif"] = dif
        r["dfma_difma"] = difma

        # TAQ — 注：ATR 依赖 Wilder 平滑起点，与 Tushare 有差，但近似可用
        up, mid, lo = self.taq()
        r["taq_up"] = up
        r["taq_mid"] = mid
        r["taq_down"] = lo

        # 涨跌/新高新低天数 — 这些与复权无关，只用 bfq 算一份，不加后缀
        up_d, dn_d, top_d, low_d = self.updown_toplow_days()
        # updays/downdays 不加到 r 中（由 derive_factor_pro 单独加入，避免 add_suffix 污染）
        # topdays/lowdays 公式与 Tushare 不同（Tushare 用累计上市天数，我们用局部新高）

        # ----- 以下指标不计算，设为 NaN -----
        # 原因: 需要与 Tushare 完全一致的历史起点或 Tushare 内部实现细节
        # asi/asit: Wilder Swing Index — 公式未公开
        # cr: 中位价定义不明（前日典型价 vs 前日中位价）
        # obv: 绝对值依赖历史起点
        # xsii_td1/2/3/4: DeMark TD Sequential — 实现未公开
        for col in [
            "asi", "asit", "cr",
            "xsii_td1", "xsii_td2", "xsii_td3", "xsii_td4",
        ]:
            r[col] = np.nan

        return r


# ============================================================
# 公开接口（仅 jh_quant 内部使用）
# ============================================================


def derive_factor_pro(jhd, ts_code: str, start: Optional[str] = None, end: Optional[str] = None):
    """
    从四张基表衍生计算 ts_stk_factor_pro。

    Args:
        jhd: JHData 实例
        ts_code: 股票代码，如 "600000.SH"
        start: 起始日期 "YYYY-MM-DD"（需要 ≥250 天的回溯以算 MA250）
        end:   结束日期 "YYYY-MM-DD"

    Returns:
        pd.DataFrame，列与 ts_stk_factor_pro 完全一致
    """
    from .data_types import DataTypes

    # 1. 拉取四张基表（.copy() 确保是可写的普通 DataFrame）
    df_bfq = jhd.get_data(DataTypes.TS_DAILY, ts_code=ts_code, start=start, end=end).copy()
    df_hfq = jhd.get_data(DataTypes.TS_DAILY_HFQ, ts_code=ts_code, start=start, end=end).copy()
    df_qfq = jhd.get_data(DataTypes.TS_DAILY_QFQ, ts_code=ts_code, start=start, end=end).copy()
    df_basic = jhd.get_data(DataTypes.TS_DAILY_BASIC, ts_code=ts_code, start=start, end=end).copy()

    if df_bfq.empty:
        return pd.DataFrame()

    # 统一索引
    for df in [df_bfq, df_hfq, df_qfq]:
        if not isinstance(df.index, pd.DatetimeIndex):
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df.set_index("trade_date", inplace=True)
            df.sort_index(inplace=True)
    if not df_basic.empty and not isinstance(df_basic.index, pd.DatetimeIndex):
        df_basic["trade_date"] = pd.to_datetime(df_basic["trade_date"])
        df_basic.set_index("trade_date", inplace=True)
        df_basic.sort_index(inplace=True)

    # 2. 构建输出基础列
    base = df_bfq[[
        "open", "high", "low", "close", "pre_close", "change",
        "pct_chg", "vol", "amount"
    ]].copy()
    base.index.name = "trade_date"

    # 映射 hfq/qfq 价格
    for sfx, df_s in [("hfq", df_hfq), ("qfq", df_qfq)]:
        for col in ["open", "high", "low", "close"]:
            base[f"{col}_{sfx}"] = df_s[col]

    # adj_factor: JiuHuang 和 Tushare 使用不同的复权方法，无法从 close_qfq/close 推导
    # 直接设 NaN。close_qfq/close_hfq 从 API 获取的值本身是正确的。
    base["adj_factor"] = np.nan

    # 3. 合并基本面
    basic_map_cols = {
        "turnover_rate": "turnover_rate",
        "turnover_rate_f": "turnover_rate_f",
        "volume_ratio": "volume_ratio",
        "pe": "pe", "pe_ttm": "pe_ttm",
        "pb": "pb", "ps": "ps", "ps_ttm": "ps_ttm",
        "dv_ratio": "dv_ratio", "dv_ttm": "dv_ttm",
        "total_share": "total_share", "float_share": "float_share",
        "free_share": "free_share",
        "total_mv": "total_mv", "circ_mv": "circ_mv",
    }
    if not df_basic.empty:
        for src, dst in basic_map_cols.items():
            if src in df_basic.columns:
                base[dst] = df_basic[src]

    # 4. 计算三套指标
    def _ts_name(col: str, suffix: str) -> str:
        """内部名 → Tushare 命名: ma_5 + bfq → ma_bfq_5; expma_12 + bfq → expma_12_bfq"""
        # expma 特殊：expma_12 整体是名字，不加 _bfq_ 在中间
        if col.startswith("expma_"):
            return col + f"_{suffix}"
        parts = col.split("_")
        if parts[-1].isdigit():
            return "_".join(parts[:-1]) + f"_{suffix}_" + parts[-1]
        return col + f"_{suffix}"

    datasets = [
        ("bfq", df_bfq),
        ("hfq", df_hfq),
        ("qfq", df_qfq),
    ]
    for suffix, df_src in datasets:
        calc = _IndicatorCalc(
            df_src["open"], df_src["high"], df_src["low"],
            df_src["close"], df_src["vol"], df_src["amount"]
        )
        ind = calc.compute_all()
        ind = ind.rename(columns=lambda c: _ts_name(c, suffix))
        base = base.join(ind, how="left")

    # updays/downdays 只算一份（bfq），无后缀
    days_calc = _IndicatorCalc(
        df_bfq["open"], df_bfq["high"], df_bfq["low"],
        df_bfq["close"], df_bfq["vol"], df_bfq["amount"]
    )
    up_d, dn_d, _, _ = days_calc.updown_toplow_days()
    base["updays"] = up_d.values
    base["downdays"] = dn_d.values
    # topdays/lowdays 公式与 Tushare 不同，设为 NaN

    # 5. 补齐 ts_code 列，恢复 trade_date 为普通列
    base["ts_code"] = ts_code
    base.reset_index(inplace=True)
    base["trade_date"] = base["trade_date"].dt.strftime("%Y%m%d")

    # 6. 用 data_types 里 Tushare 定义的精确列顺序
    from .data_types import get_table_fields
    expected_cols = list(get_table_fields(DataTypes.TS_STK_FACTOR_PRO))

    for col in expected_cols:
        if col not in base.columns:
            base[col] = np.nan

    # 只保留预期的列（去掉多余的）
    base = base[expected_cols]

    return base
