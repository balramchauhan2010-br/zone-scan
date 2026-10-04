"""
zone_core_validation.py
=======================
zone_core.py (Pine-parity zone scanner) ka upgraded version, jisme 5 sudhaar hain:

  (1) FRESH ZONE = jis zone ki PROXIMAL LINE ko price ne touch NA kiya ho.
      Jaise hi price proximal line chhoo le -> zone "Tested" (aur wahi entry bar hai).
      PURANA CODE BUG: state tracking `legOutMidLevel` use karta tha, jiski wajah se
      har zone CREATION WALE BAR PAR HI "Tested" ban jata tha (demand: mid = out_low,
      aur usi bar ka low == out_low). Is file me:
          * tracking creation bar ke BAAD se shuru hoti hai
          * touch = proximal line (proxVal), na ki legOutMidLevel

  (2) FRESH-ZONE ENTRY: entry proximal line par, SL distal line par.
      Trade tabhi, jab ZONE BANANE WALI SINGLE LEG-OUT CANDLE ne khud
      >= 1:3 reward diya ho  (legOutHigh - prox) / risk >= 3.0   [demand]
                              (prox - legOutLow)  / risk >= 3.0   [supply]
      Nahin to zone reject (config: minLegOutRR, useLegOutRRFilter).

  (3) RULE-3  Reversal DEMAND (DBR):
      * pattern DBR (leg-in bearish, leg-out bullish)
      * leg-in candle ke UPAR pahle se ek DBD / DBD-like SUPPLY zone bana ho
      * DBR ka leg-out CLOSE us DBD zone ke DISTAL (high) se upar band ho = engulf
      Tabhi DBR valid demand.

  (4) RULE-4  Reversal SUPPLY (RBD):
      * pattern RBD (leg-in bullish, leg-out bearish)
      * leg-in candle ke NEECHE pahle se ek RBR / RBR-like DEMAND zone bana ho
      * RBD ka leg-out CLOSE us RBR zone ke DISTAL (low) se neeche band ho = engulf
      Tabhi RBD valid supply.

  (5) FINAL DECISION
      demand valid = (RBR and rule-1)  or  (DBR and rule-3)
      supply valid = (DBD and rule-2)  or  (RBD and rule-4)
      rule-1 / rule-2 = maujuda core validity checks (explosive, wick, TR hierarchy,
                        volume, imbalance, engulf-of-base, minValidScore).

  (6) SWING RANGE: swing/leg candle ki minimum range = swingRangeAtrMult x ATR
      (default 0.05) — config me badla ja sakta hai.

  (7) PULSE + TREND (FINAL RULE TABLE v2 se) — har zone par tag lagta hai:
      pulse  = higher timeframe bias   (EMA_SLOPE / MACD_HIST / SMA200 / EMA_STACK /
                                        SUPERTREND / EMA20_50)
      trend  = middle timeframe direction (ST_20_4 / ST_10_3 / ST_7_2 / DONCHIAN /
                                        EMA_TRIPLE / DI_CROSS)
      Zone tabhi "aligned" jab demand zone par pulse=+1 & trend=+1,
      ya supply zone par pulse=-1 & trend=-1.
      Higher-TF value sirf COMPLETED higher-TF bar se aati hai (no look-ahead).

Backward compatibility: purane Zone fields, settings(), scan_zones(),
latest_active_zones(), high_quality_zones() sab kaam karte hain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# =====================================================================================
#  FINAL RULE TABLE v2  —  pulse / trend rules (backtest se nikle hue)
#  key = zone timeframe
# =====================================================================================
RULE_TABLE_V2: Dict[str, Dict[str, str]] = {
    "10m": dict(pulse="SUPERTREND", pulse_tf="2W", trend="ST_20_4",    trend_tf="3D"),
    "15m": dict(pulse="MACD_HIST",  pulse_tf="2M", trend="ST_20_4",    trend_tf="1W"),
    "30m": dict(pulse="MACD_HIST",  pulse_tf="1M", trend="ST_20_4",    trend_tf="3D"),
    "1H":  dict(pulse="SUPERTREND", pulse_tf="6H", trend="DONCHIAN",   trend_tf="1H"),
    "2H":  dict(pulse="SMA200",     pulse_tf="2H", trend="EMA_TRIPLE", trend_tf="2H"),
    "4H":  dict(pulse="EMA_STACK",  pulse_tf="3M", trend="ST_20_4",    trend_tf="1W"),
    "6H":  dict(pulse="EMA_STACK",  pulse_tf="2M", trend="ST_10_3",    trend_tf="3D"),
    "1D":  dict(pulse="EMA_SLOPE",  pulse_tf="3M", trend="ST_20_4",    trend_tf="2W"),
    "1W":  dict(pulse="MACD_HIST",  pulse_tf="3M", trend="ST_20_4",    trend_tf="2W"),
    "1M":  dict(pulse="SUPERTREND", pulse_tf="3M", trend="ST_7_2",     trend_tf="3M"),
}

# =====================================================================================
#  DEFAULTS  (PINE_DEFAULTS + naye validation params)
# =====================================================================================
PINE_DEFAULTS: Dict[str, Any] = {
    "accountCapital": 25000.0,
    "riskPct": 0.5,
    "targetRR": 3.0,              # (2) 1:3 rule ke saath consistent
    "slBufferAtr": 0.1,
    "atrPeriod": 14,
    "volSmaPeriod": 20,
    "legOutTrMult": 1.2,
    "legOutMinTrRatio": 1.0,
    "hqLegOutTrMult": 2.0,
    "hqLegInAtrMult": 1.5,
    "maxBaseAtrMult": 1.0,
    "maxWickPct": 0.30,
    "minBaseCountInput": 1,
    "maxBaseCountInput": 3,
    "legInMinAtrMult": 1.0,
    "minClvPct": 0.60,
    "legInToBaseSizeMult": 2.0,
    "legInMinBodyPct": 0.60,
    "useImbalance": True,
    "maxImbalanceMult": 1.0,
    "relaxGapCapOvernight": True,
    "genuineGapBonus": 10,
    "overnightGapBonus": 15,
    "rejectOppositeCoverPct": 0.50,
    "minValidScore": 40,
    "hqScoreThreshold": 90,
    "legOutBodyHeavyPct": 0.60,
    "testedLegOutRetracePct": 1.00,
    "maxTestedCount": 1,

    # ---- Pine "PARITY INPUTS" (inert) ----
    "legOutToLegInBodyMult": 1.0,
    "baseBoringMaxBodyPct": 0.55,
    "scanAfterCandleComplete": True,
    "scanMonthlyOnce": True,
    "scanWeeklyOnce": True,
    "scanDailyOnce": True,
    "enableClosingWickCheck": True,
    "legInMinClosingWickPct": 0.1,
    "enableLegOutCoverCheck": True,
    "legOutMaxCoverPct": 90.0,
    "enableHQBaseColourCheck": True,
    "hqBaseColourProbabilityPct": 90.0,
    "enableWhiteAreaCheck": True,

    # ---- EOD range (scanner-only) ----
    "eodHighBufferPct": 10.0,
    "eodLowBufferPct": 10.0,
    "useEodRange": True,

    # ================= NEW: VALIDATION =================
    "freshUsesProximal": True,
    "trackFromNextBar": True,
    "useLegOutRRFilter": False,
    "minLegOutRR": 3.0,
    "requireEngulfForReversal": True,
    "engulfLookbackBars": 250,
    "engulfAllowBrokenRef": True,
    "engulfMode": "distal_close",
    "engulfRefPosition": "high",
    "swingRangeAtrMult": 0.05,
    "usePulseTrend": True,
    "requirePulseTrendAligned": False,
}

HARD_MAX_BASE_COUNT = 3


def resolve_rules(zone_tf: str) -> Dict[str, str]:
    key = str(zone_tf).strip()
    alias = {"1D": "1D", "D": "1D", "DAILY": "1D", "1DAY": "1D",
             "1W": "1W", "W": "1W", "WEEKLY": "1W",
             "1M": "1M", "M": "1M", "MONTHLY": "1M",
             "15M": "15m", "30M": "30m", "10M": "10m",
             "1H": "1H", "2H": "2H", "4H": "4H", "6H": "6H"}
    key = alias.get(key.upper(), key)
    if key not in RULE_TABLE_V2:
        # fallback to closest if not in table
        return dict(pulse="SUPERTREND", pulse_tf="2W", trend="ST_20_4", trend_tf="3D")
    return dict(RULE_TABLE_V2[key])


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()

def _true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - pc).abs(),
                      (df["low"] - pc).abs()], axis=1).max(axis=1)

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(_true_range(df), n)

def _supertrend_dir(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    hl2 = (df["high"] + df["low"]) / 2.0
    a = _atr(df, period)
    ub = (hl2 + mult * a).to_numpy()
    lb = (hl2 - mult * a).to_numpy()
    c = df["close"].to_numpy()
    n = len(df)
    fub, flb, st = np.zeros(n), np.zeros(n), np.zeros(n)
    d = np.zeros(n, dtype=int)
    fub[0], flb[0], st[0], d[0] = ub[0], lb[0], ub[0], -1
    for i in range(1, n):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if st[i - 1] == fub[i - 1]:
            st[i] = fub[i] if c[i] <= fub[i] else flb[i]
        else:
            st[i] = flb[i] if c[i] >= flb[i] else fub[i]
        d[i] = -1 if st[i] == fub[i] else 1
    return pd.Series(d, index=df.index)

def _macd(c: pd.Series, f=12, s=26, sig=9):
    m = _ema(c, f) - _ema(c, s)
    return m, _ema(m, sig)

def _di(df: pd.DataFrame, n: int = 14):
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = _atr(df, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 * _wilder(pdm, n) / a, 100 * _wilder(ndm, n) / a

def p_ema2050(df: pd.DataFrame) -> pd.Series:
    c = df["close"]; e1, e2 = _ema(c, 20), _ema(c, 50)
    return pd.Series(np.where((c > e1) & (c > e2), 1, np.where((c < e1) & (c < e2), -1, 0)), index=df.index)

def p_ema_stack(df: pd.DataFrame) -> pd.Series:
    c = df["close"]; e1, e2, e3 = _ema(c, 20), _ema(c, 50), _ema(c, 100)
    return pd.Series(np.where((e1 > e2) & (e2 > e3), 1, np.where((e1 < e2) & (e2 < e3), -1, 0)), index=df.index)

def p_ema_slope(df: pd.DataFrame) -> pd.Series:
    c = df["close"]; e = _ema(c, 20); sl = e.diff(5)
    return pd.Series(np.where((sl > 0) & (c > e), 1, np.where((sl < 0) & (c < e), -1, 0)), index=df.index)

def p_sma200(df: pd.DataFrame) -> pd.Series:
    c = df["close"]; s = c.rolling(200).mean()
    return pd.Series(np.where(c > s, 1, np.where(c < s, -1, 0)), index=df.index)

def p_macd_hist(df: pd.DataFrame) -> pd.Series:
    m, s = _macd(df["close"]); h = m - s
    return pd.Series(np.where(h > 0, 1, np.where(h < 0, -1, 0)), index=df.index)

def p_supertrend(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 10, 3.0)

def t_st_10_3(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 10, 3.0)

def t_st_7_2(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 7, 2.0)

def t_st_20_4(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 20, 4.0)

def t_ema_triple(df: pd.DataFrame) -> pd.Series:
    c = df["close"]; e1, e2 = _ema(c, 20), _ema(c, 50)
    return pd.Series(np.where((c > e1) & (e1 > e2), 1, np.where((c < e1) & (e1 < e2), -1, 0)), index=df.index)

def t_donchian(df: pd.DataFrame, n: int = 20) -> pd.Series:
    c = df["close"]
    up = df["high"].rolling(n).max().shift(1)
    dn = df["low"].rolling(n).min().shift(1)
    mid = (up + dn) / 2
    return pd.Series(np.where(c > mid, 1, np.where(c < mid, -1, 0)), index=df.index)

def t_di_cross(df: pd.DataFrame) -> pd.Series:
    pdi, mdi = _di(df, 14)
    return pd.Series(np.where(pdi > mdi, 1, np.where(mdi > pdi, -1, 0)), index=df.index)

PULSE_FUNCS = {"EMA20_50": p_ema2050, "EMA_STACK": p_ema_stack, "EMA_SLOPE": p_ema_slope,
               "SMA200": p_sma200, "MACD_HIST": p_macd_hist, "SUPERTREND": p_supertrend}
TREND_FUNCS = {"ST_10_3": t_st_10_3, "ST_7_2": t_st_7_2, "ST_20_4": t_st_20_4,
               "EMA_TRIPLE": t_ema_triple, "DONCHIAN": t_donchian, "DI_CROSS": t_di_cross}

def pulse_state(df: pd.DataFrame, rule: str) -> pd.Series:
    if rule not in PULSE_FUNCS:
        raise KeyError(f"unknown pulse rule '{rule}'. Available: {sorted(PULSE_FUNCS)}")
    return PULSE_FUNCS[rule](df).astype(int)

def trend_state(df: pd.DataFrame, rule: str) -> pd.Series:
    if rule not in TREND_FUNCS:
        raise KeyError(f"unknown trend rule '{rule}'. Available: {sorted(TREND_FUNCS)}")
    return TREND_FUNCS[rule](df).astype(int)

def map_completed(entry_index: pd.DatetimeIndex, htf_index: pd.DatetimeIndex) -> np.ndarray:
    vt = pd.DatetimeIndex(htf_index).values.astype("datetime64[ns]")
    vf = np.concatenate([vt[1:], [np.datetime64("2262-01-01")]])
    et = pd.DatetimeIndex(entry_index).values.astype("datetime64[ns]")
    return np.searchsorted(vf, et, side="right") - 1

@dataclass
class Box:
    left: int
    top: float
    right: int
    bottom: float
    border_color: object
    bgcolor: object
    def set_right(self, right: int) -> None: self.right = right
    def set_bgcolor(self, c: object) -> None: self.bgcolor = c
    def set_border_color(self, c: object) -> None: self.border_color = c

@dataclass
class Zone:
    proxVal: float
    distVal: float
    slVal: float
    tpVal: float
    isDemand: bool
    isHQ: bool
    densityScore: int
    patternType: str
    zoneCategory: str
    state: str
    touchCount: int
    startBarIndex: int
    createdBarIndex: int
    baseCount: int
    legOutHigh: float
    legOutLow: float
    legOutMidLevel: float
    isOvernight: bool
    legInTR: float
    legOutTR: float
    zoneBox: Box
    timestamp: object = None
    riskPct: float = float("nan")
    score10: float = 0.0
    hasGenuineGap: bool = False
    gapToLegIn: float = 0.0
    legInVolX: float = float("nan")
    legOutVolX: float = float("nan")
    entryBarIndex: Optional[int] = None
    entryTimestamp: object = None
    breakBarIndex: Optional[int] = None
    baseColourOK: bool = False
    retestVolX: float = float("nan")
    entryStatus: str = ""
    entryPrice: float = 0.0
    hqProbabilityPct: float = float("nan")
    hqReason: str = ""
    whiteAreaOK: Optional[bool] = None
    breakReason: str = ""
    baseIndecision: bool = False
    baseDojiCount: int = 0
    isFresh: bool = True
    testedBarIndex: Optional[int] = None
    testedTimestamp: object = None
    legOutReward: float = float("nan")
    legOutRR: float = float("nan")
    legOutPassesRR: bool = False
    legInBarIndex: Optional[int] = None
    legInHigh: float = float("nan")
    legInLow: float = float("nan")
    legOutClose: float = float("nan")
    engulfRefPattern: str = ""
    engulfRefDist: float = float("nan")
    engulfRefBar: Optional[int] = None
    engulfOK: bool = False
    rule1OK: bool = False
    rule2OK: bool = False
    rule3OK: bool = False
    rule4OK: bool = False
    validDemand: bool = False
    validSupply: bool = False
    pulse: int = 0
    trend: int = 0
    pulseTf: str = ""
    trendTf: str = ""
    pulseRule: str = ""
    trendRule: str = ""
    biasAligned: bool = False

def _positive_float(value: Any, name: str) -> float:
    try:
        r = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(r) or r <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return r

def get_eod_range(df: pd.DataFrame, idx: int, high_buffer_pct: float = 10.0, low_buffer_pct: float = 10.0):
    try:
        d = df.index[idx].date()
        day = df[df.index.date == d]
        if day.empty:
            return float(df["low"].iloc[idx] * .9), float(df["high"].iloc[idx] * 1.1)
        return (float(day["low"].min() * (1 - low_buffer_pct / 100)), float(day["high"].max() * (1 + high_buffer_pct / 100)))
    except Exception:
        return float(df["low"].iloc[idx] * .9), float(df["high"].iloc[idx] * 1.1)

def check_white_area(df: pd.DataFrame, base_start_idx: int, base_end_idx: int, leg_out_idx: int, curr_idx: int) -> bool:
    bh = float(df["high"].iloc[base_start_idx:base_end_idx + 1].max())
    bl = float(df["low"].iloc[base_start_idx:base_end_idx + 1].min())
    if leg_out_idx + 1 >= curr_idx:
        return True
    w = df.iloc[leg_out_idx + 1:curr_idx]
    return not bool(((w["low"] <= bh) & (w["high"] >= bl)).any())

def check_leg_out_coverage(df: pd.DataFrame, leg_out_idx: int, curr_idx: int, max_cover_pct: float = 90.0) -> bool:
    hi, lo = float(df["high"].iloc[leg_out_idx]), float(df["low"].iloc[leg_out_idx])
    rng = hi - lo
    if rng <= 0 or leg_out_idx + 1 > curr_idx:
        return True
    w = df.iloc[leg_out_idx + 1:curr_idx + 1]
    ov = (np.minimum(w["high"], hi) - np.maximum(w["low"], lo)).clip(lower=0)
    return not bool(((ov / rng) > max_cover_pct / 100).any())

def resample_ohlc(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    tf = str(tf).strip().upper()
    if tf in ("1D", "D", "DAILY"):
        return df.copy()
    rules = {"2D": "2D", "3D": "3D", "1W": "W-FRI", "2W": "2W-FRI", "1M": "ME", "2M": "2ME", "3M": "3ME"}
    if tf in rules:
        o = df.resample(rules[tf], label="left", closed="left").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum") if "volume" in df else ("close", "last"))
        return o.dropna(subset=["open", "high", "low", "close"])
    if tf in ("1H", "15M", "15m", "30M", "30m", "10M", "10m"):
        return df.copy()
    if tf in ("2H", "4H", "6H", "10M", "10m"):
        k = int(tf[0]) if tf[-1] in "Hh" else 1
        src = df
        d = src[["open", "high", "low", "close"] + (["volume"] if "volume" in src else [])].copy()
        d.index.name = "ts"
        d = d.reset_index()
        d["_d"] = pd.to_datetime(d["ts"]).dt.date
        d["_g"] = d.groupby("_d").cumcount() // k
        agg = dict(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), ts=("ts", "first"), _n=("close", "size"))
        if "volume" in d:
            agg["volume"] = ("volume", "sum")
        o = d.groupby(["_d", "_g"]).agg(**agg)
        o = o[o["_n"] >= k].drop(columns=["_n"]).reset_index()
        o = o.set_index("ts").sort_index()
        o.index.name = src.index.name
        return o
    raise ValueError(f"resample_ohlc: unsupported timeframe '{tf}'")

class ZoneEngine:
    def __init__(self, df: pd.DataFrame, **kwargs: Any):
        self.df = df.copy()
        if "volume" not in self.df.columns:
            self.df["volume"] = 0.0
        self.df["volume"] = self.df["volume"].fillna(0.0)
        for k, d in PINE_DEFAULTS.items():
            setattr(self, k, kwargs.get(k, d))
        self.accountCapital = _positive_float(self.accountCapital, "accountCapital")
        self.minBaseCount = max(1, min(self.minBaseCountInput, self.maxBaseCountInput))
        self.maxBaseCount = min(self.maxBaseCountInput, HARD_MAX_BASE_COUNT)
        self.o = self.df["open"].to_numpy(float)
        self.h = self.df["high"].to_numpy(float)
        self.l = self.df["low"].to_numpy(float)
        self.c = self.df["close"].to_numpy(float)
        self.v = self.df["volume"].to_numpy(float)
        self.n = len(self.df)
        self.dow = self.df.index.dayofweek.to_numpy()
        time_index = self.df.index
        if time_index.tz is not None:
            time_index = time_index.tz_convert("UTC").tz_localize(None)
        self.time_ms = time_index.astype("datetime64[ns]").astype(np.int64) // 10 ** 6
        self.active_zones: List[Zone] = []
        self.live_zones: List[Zone] = []
        self.zone_history: List[Zone] = []
        self.pattern_registry: List[Zone] = []
        self.gate_counts: Dict[str, int] = {}
        self._prepare()

    def _rej(self, name: str) -> None:
        self.gate_counts[name] = self.gate_counts.get(name, 0) + 1

    def funnel(self) -> pd.DataFrame:
        if not self.gate_counts:
            return pd.DataFrame()
        df = (pd.DataFrame([dict(gate=k, rejected=v) for k, v in self.gate_counts.items()]).sort_values("rejected", ascending=False).reset_index(drop=True))
        df["pct"] = (100 * df.rejected / df.rejected.sum()).round(1)
        return df

    def _rma(self, s: np.ndarray, length: int) -> np.ndarray:
        r = np.full(len(s), np.nan)
        if len(s) < length:
            return r
        r[length - 1] = np.mean(s[:length])
        for i in range(length, len(s)):
            r[i] = (s[i] - r[i - 1]) / length + r[i - 1]
        return r

    def _prepare(self) -> None:
        n = self.n
        tr = self.h - self.l
        if n > 1:
            pc = self.c[:-1]
            tr[1:] = np.maximum(tr[1:], np.maximum(np.abs(self.h[1:] - pc), np.abs(self.l[1:] - pc)))
        self.atr = self._rma(tr, self.atrPeriod)
        self.vol_sma = self.df["volume"].rolling(self.volSmaPeriod).mean().to_numpy()
        day_key = self.df.index.normalize()
        self.day_high = self.df["high"].groupby(day_key).transform("max").to_numpy()
        self.day_low = self.df["low"].groupby(day_key).transform("min").to_numpy()

    def _tr(self, p: int) -> float:
        pc = self.c[p - 1]
        return max(self.h[p] - self.l[p], abs(self.h[p] - pc), abs(self.l[p] - pc))

    def _bull(self, p: int) -> bool: return bool(self.c[p] > self.o[p])
    def _bear(self, p: int) -> bool: return bool(self.o[p] > self.c[p])

    def _wick_pct(self, p: int) -> float:
        rng = self.h[p] - self.l[p]
        if rng == 0: return 0.0
        w = (self.h[p] - max(self.o[p], self.c[p])) + (min(self.o[p], self.c[p]) - self.l[p])
        return w / rng

    def _body_pct(self, p: int) -> float:
        rng = self.h[p] - self.l[p]
        if rng == 0: return 0.0
        return abs(self.c[p] - self.o[p]) / rng

    def _swing_ok(self, p: int) -> bool:
        rng = self.h[p] - self.l[p]
        a = self.atr[p]
        if not np.isfinite(a) or a <= 0:
            return False
        return rng >= self.swingRangeAtrMult * a

    def _overnight(self, i: int) -> bool:
        if i == 0: return False
        return bool(self.dow[i] != self.dow[i - 1] or (self.time_ms[i] - self.time_ms[i - 1]) > 86400000)

    @staticmethod
    def _is_dbd_like(z: Zone) -> bool:
        return (not z.isDemand) and (z.patternType == "DBD" or z.zoneCategory == "Continuation")

    @staticmethod
    def _is_rbr_like(z: Zone) -> bool:
        return z.isDemand and (z.patternType == "RBR" or z.zoneCategory == "Continuation")

    def _find_engulf_ref(self, i: int, is_demand: bool, in_high: float, in_low: float, out_close: float, atr_now: float, max_prox: float = float("nan"), min_prox: float = float("nan"), out_high: float = float("nan"), out_low: float = float("nan")) -> Optional[Zone]:
        best: Optional[Zone] = None
        min_zone_range = self.swingRangeAtrMult * atr_now
        for z in reversed(self.pattern_registry):
            if i - z.createdBarIndex > self.engulfLookbackBars:
                break
            if z.createdBarIndex >= i:
                continue
            if (not self.engulfAllowBrokenRef) and z.state == "Broken":
                continue
            if abs(z.proxVal - z.distVal) < min_zone_range:
                continue
            mode = (self.engulfRefPosition or "high").lower()
            emode = (self.engulfMode or "distal_close").lower()
            use_prox = emode.startswith("proximal")
            use_wick = emode.endswith("wick")
            probe = (out_high if is_demand else out_low) if use_wick else out_close
            if is_demand:
                if not self._is_dbd_like(z):
                    continue
                lvl = max_prox if mode == "base" else (in_high if mode == "high" else in_low)
                if z.distVal <= lvl:
                    continue
                ref = z.proxVal if use_prox else z.distVal
                if not probe > ref:
                    continue
                if best is None or ref < (best.proxVal if use_prox else best.distVal):
                    best = z
            else:
                if not self._is_rbr_like(z):
                    continue
                lvl = min_prox if mode == "base" else (in_low if mode == "high" else in_high)
                if z.distVal >= lvl:
                    continue
                ref = z.proxVal if use_prox else z.distVal
                if not probe < ref:
                    continue
                if best is None or ref > (best.proxVal if use_prox else best.distVal):
                    best = z
        return best

    def _scan_bar(self, i: int) -> None:
        atr_now = self.atr[i]
        found = False
        for bc in range(self.minBaseCount, self.maxBaseCount + 1):
            if found:
                break
            li = bc + 1
            pi = li + 1
            p_in, p_prev, p_out = i - li, i - pi, i
            self._rej("00_candidates")
            if p_prev < 0 or np.isnan(self.atr[p_in]):
                self._rej("00a_warmup")
                continue
            if not (self._swing_ok(p_in) and self._swing_ok(p_out)):
                self._rej("01_swing_range")
                continue
            leg_in_tr = self._tr(p_in)
            in_low, in_high, in_close = self.l[p_in], self.h[p_in], self.c[p_in]
            in_vol = self.v[p_in]
            in_rng = in_high - in_low
            in_bull, in_bear = self._bull(p_in), self._bear(p_in)
            if in_rng == 0 or self._body_pct(p_in) < self.legInMinBodyPct:
                self._rej("02_legIn_body")
                continue
            if (in_bull and self._bear(p_prev)) or (in_bear and self._bull(p_prev)):
                pbh, pbl = max(self.o[p_prev], self.c[p_prev]), min(self.o[p_prev], self.c[p_prev])
                overlap = max(0.0, min(pbh, in_high) - max(pbl, in_low))
                if overlap / in_rng >= self.rejectOppositeCoverPct:
                    self._rej("03_opposite_cover")
                    continue
            bull_clv = (in_close - in_low) / in_rng
            bear_clv = (in_high - in_close) / in_rng
            ok = True
            max_base_tr = 0.0
            max_base_high = -1.0
            min_base_low = 1e18
            for b in range(1, bc + 1):
                pb = i - b
                if np.isnan(self.atr[pb]):
                    ok = False; break
                btr = self._tr(pb)
                if btr > self.maxBaseAtrMult * self.atr[pb]:
                    ok = False; break
                max_base_tr = max(max_base_tr, btr)
                max_base_high = max(max_base_high, self.h[pb])
                min_base_low = min(min_base_low, self.l[pb])
            if not ok or max_base_tr == 0:
                self._rej("04_base_TR")
                continue
            eff_mult = 1.5 if bc == 1 else self.legInToBaseSizeMult
            if leg_in_tr < eff_mult * max_base_tr:
                self._rej("05_legIn_vs_base")
                continue
            if not (leg_in_tr >= self.legInMinAtrMult * self.atr[p_in]):
                self._rej("06_legIn_vs_ATR")
                continue
            leg_out_tr = self._tr(p_out)
            out_high, out_low = self.h[p_out], self.l[p_out]
            out_close, out_open = self.c[p_out], self.o[p_out]
            out_vol = self.v[p_out]
            is_demand = self._bull(p_out)
            is_supply = self._bear(p_out)
            if not (is_demand or is_supply):
                self._rej("07_legOut_doji")
                continue
            explosive = leg_out_tr >= self.legOutTrMult * self.atr[p_out]
            wick_ok = self._wick_pct(p_out) <= self.maxWickPct
            tr_hier = (leg_out_tr >= self.legOutMinTrRatio * leg_in_tr) and (leg_in_tr > max_base_tr)
            vol_ok = out_vol > in_vol
            is_overnight = self._overnight(i)
            has_imb = True
            has_gap = False
            gap_size = 0.0
            if self.useImbalance:
                if is_demand:
                    has_gap = out_low > max_base_high
                    has_imb = has_gap or (out_close > in_high)
                    gap_size = max(0.0, out_low - max_base_high)
                else:
                    has_gap = out_high < min_base_low
                    has_imb = has_gap or (out_close < in_low)
                    gap_size = max(0.0, min_base_low - out_high)
            if (min(out_open, out_close) <= min_base_low and max(out_open, out_close) >= max_base_high and not has_gap):
                self._rej("08_base_engulfed")
                continue
            is_rbr = in_bull and bull_clv >= self.minClvPct and is_demand
            is_dbr = in_bear and bear_clv >= self.minClvPct and is_demand
            is_dbd = in_bear and bear_clv >= self.minClvPct and is_supply
            is_rbd = in_bull and bull_clv >= self.minClvPct and is_supply
            if not (is_rbr or is_dbr or is_dbd or is_rbd):
                self._rej("09_classification_CLV")
                continue
            if not explosive:
                self._rej("10_legOut_explosive")
                continue
            if not wick_ok:
                self._rej("11_legOut_wick")
                continue
            if not tr_hier:
                self._rej("12_TR_hierarchy")
                continue
            if not vol_ok:
                self._rej("13_volume_out_gt_in")
                continue
            if not has_imb:
                self._rej("14_imbalance_gap")
                continue
            score = 0
            if bc == 1: score += 15
            if leg_in_tr >= self.hqLegInAtrMult * self.atr[p_in]: score += 10
            if leg_out_tr >= self.hqLegOutTrMult * leg_in_tr: score += 15
            if leg_in_tr >= 2.0 * max_base_tr and leg_out_tr >= 2.0 * leg_in_tr: score += 15
            if out_vol > self.vol_sma[p_out]: score += 10
            out_rng = out_high - out_low
            if is_demand:
                pos = (out_close - out_low) / out_rng if out_rng > 0 else 0
                own_body = self._body_pct(p_out)
                if is_dbr:
                    if pos >= 0.80 or own_body >= self.legOutBodyHeavyPct: score += 15
                elif pos >= 0.80: score += 15
            else:
                pos = (out_high - out_close) / out_rng if out_rng > 0 else 0
                if pos >= 0.80: score += 15
            opp_base = False
            for b in range(1, bc + 1):
                if (is_demand and self._bear(i - b)) or (is_supply and self._bull(i - b)):
                    opp_base = True; break
            if opp_base: score += 10
            score += 10
            if has_gap: score += self.genuineGapBonus
            if is_overnight and has_gap: score += self.overnightGapBonus
            if score < self.minValidScore:
                self._rej("15_minValidScore")
                continue
            prox = max_base_high if is_demand else min_base_low
            dist = min_base_low if is_demand else max_base_high
            if self.useEodRange:
                eod_high = self.day_high[i] * (1 + self.eodHighBufferPct / 100.0)
                eod_low = self.day_low[i] * (1 - self.eodLowBufferPct / 100.0)
                if not (eod_low <= prox <= eod_high):
                    self._rej("16_EOD_range")
                    continue
            sl = dist - self.slBufferAtr * atr_now if is_demand else dist + self.slBufferAtr * atr_now
            risk = abs(prox - sl)
            if risk <= 0:
                self._rej("17_risk_zero")
                continue
            pattern = "RBR" if is_rbr else ("DBR" if is_dbr else ("DBD" if is_dbd else "RBD"))
            cat = "Continuation" if (is_rbr or is_dbd) else "Reversal"
            border = "green" if is_demand else "red"
            fill = ("green", 0.15) if is_demand else ("red", 0.15)
            vs_in, vs_out = self.vol_sma[p_in], self.vol_sma[p_out]
            tp = prox + self.targetRR * risk if is_demand else prox - self.targetRR * risk
            if is_demand:
                mid = out_high - self.testedLegOutRetracePct * (out_high - out_low)
            else:
                mid = out_low + self.testedLegOutRetracePct * (out_high - out_low)
            is_hq = bool(score >= self.hqScoreThreshold)
            z = Zone(proxVal=prox, distVal=dist, slVal=sl, tpVal=tp, isDemand=is_demand, isHQ=is_hq, densityScore=score, patternType=pattern, zoneCategory=cat, state="Fresh", touchCount=0, startBarIndex=i - bc, createdBarIndex=i, baseCount=bc, legOutHigh=out_high, legOutLow=out_low, legOutMidLevel=mid, isOvernight=is_overnight, legInTR=leg_in_tr, legOutTR=leg_out_tr, zoneBox=Box(i - bc - 1, prox, i + 15, dist, border, fill), timestamp=self.df.index[i], riskPct=risk / prox * 100.0 if prox else float("nan"), score10=round(score / 10.0, 1), hasGenuineGap=has_gap, gapToLegIn=gap_size, legInVolX=in_vol / vs_in if vs_in and not np.isnan(vs_in) else float("nan"), legOutVolX=out_vol / vs_out if vs_out and not np.isnan(vs_out) else float("nan"), legInBarIndex=int(p_in), legInHigh=float(in_high), legInLow=float(in_low), legOutClose=float(out_close), isFresh=True)
            self.pattern_registry.append(z)
            if is_demand:
                legout_reward = out_high - prox
            else:
                legout_reward = prox - out_low
            legout_rr = legout_reward / risk
            legout_pass = bool(legout_rr >= self.minLegOutRR)
            if self.useLegOutRRFilter and not legout_pass:
                self._rej("18_legOut_RR_3")
                continue
            rule1_ok = bool(is_rbr and explosive and wick_ok and tr_hier and vol_ok and has_imb)
            rule2_ok = bool(is_dbd and explosive and wick_ok and tr_hier and vol_ok and has_imb)
            rule3_ok, rule4_ok = False, False
            engulf_ref = None
            if is_dbr:
                engulf_ref = self._find_engulf_ref(i, True, in_high, in_low, out_close, atr_now, max_prox=prox, min_prox=prox, out_high=out_high, out_low=out_low)
                rule3_ok = engulf_ref is not None
                if self.requireEngulfForReversal and not rule3_ok:
                    self._rej("19_rule3_DBR_engulf")
                    continue
            if is_rbd:
                engulf_ref = self._find_engulf_ref(i, False, in_high, in_low, out_close, atr_now, max_prox=prox, min_prox=prox, out_high=out_high, out_low=out_low)
                rule4_ok = engulf_ref is not None
                if self.requireEngulfForReversal and not rule4_ok:
                    self._rej("20_rule4_RBD_engulf")
                    continue
            if not self.requireEngulfForReversal:
                rule3_ok = bool(is_dbr)
                rule4_ok = bool(is_rbd)
            demand_valid = bool((is_rbr and rule1_ok) or (is_dbr and rule3_ok))
            supply_valid = bool((is_dbd and rule2_ok) or (is_rbd and rule4_ok))
            if is_demand and not demand_valid:
                self._rej("21_demand_final_rule")
                continue
            if is_supply and not supply_valid:
                self._rej("22_supply_final_rule")
                continue
            dup = False
            checked = 0
            for zz in reversed(self.live_zones):
                if zz.isDemand == is_demand and abs(zz.proxVal - prox) < atr_now * 0.25:
                    dup = True; break
                checked += 1
                if checked >= 11: break
            if dup:
                self._rej("23_duplicate")
                continue
            z.legOutReward = float(legout_reward)
            z.legOutRR = float(legout_rr)
            z.legOutPassesRR = bool(legout_pass)
            z.engulfRefPattern = (engulf_ref.patternType if engulf_ref is not None else "")
            z.engulfRefDist = (float(engulf_ref.distVal) if engulf_ref is not None else float("nan"))
            z.engulfRefBar = (int(engulf_ref.createdBarIndex) if engulf_ref is not None else None)
            z.engulfOK = engulf_ref is not None
            z.rule1OK, z.rule2OK, z.rule3OK, z.rule4OK = rule1_ok, rule2_ok, rule3_ok, rule4_ok
            z.validDemand, z.validSupply = demand_valid, supply_valid
            self.active_zones.append(z)
            self.live_zones.append(z)
            self.zone_history.append(z)

    def _update_states(self, i: int) -> None:
        if self.pattern_registry:
            lo_r, hi_r = self.l[i], self.h[i]
            for z in self.pattern_registry:
                if z.state == "Broken" or i <= z.createdBarIndex:
                    continue
                if z.isDemand:
                    if lo_r <= z.distVal: z.state = "Broken"
                    elif lo_r <= z.proxVal: z.state = "Tested"
                else:
                    if hi_r >= z.distVal: z.state = "Broken"
                    elif hi_r >= z.proxVal: z.state = "Tested"
        if not self.live_zones:
            return
        lo, hi = self.l[i], self.h[i]
        for k in range(len(self.live_zones) - 1, -1, -1):
            z = self.live_zones[k]
            if self.trackFromNextBar and i <= z.createdBarIndex:
                z.zoneBox.set_right(i + 15)
                continue
            if z.state == "Fresh":
                if z.isDemand:
                    if lo <= z.distVal:
                        z.state = "Broken"
                    elif lo <= z.proxVal:
                        z.state = "Tested"
                        z.touchCount = 1
                        z.isFresh = False
                        z.testedBarIndex = i
                        z.testedTimestamp = self.df.index[i]
                        z.entryBarIndex = i
                        z.entryTimestamp = self.df.index[i]
                        z.entryPrice = z.proxVal
                        z.entryStatus = "ENTERED_FRESH"
                else:
                    if hi >= z.distVal:
                        z.state = "Broken"
                    elif hi >= z.proxVal:
                        z.state = "Tested"
                        z.touchCount = 1
                        z.isFresh = False
                        z.testedBarIndex = i
                        z.testedTimestamp = self.df.index[i]
                        z.entryBarIndex = i
                        z.entryTimestamp = self.df.index[i]
                        z.entryPrice = z.proxVal
                        z.entryStatus = "ENTERED_FRESH"
            elif z.state == "Tested":
                if z.isDemand:
                    if lo <= z.distVal:
                        z.state = "Broken"
                    elif lo <= z.proxVal:
                        z.touchCount += 1
                else:
                    if hi >= z.distVal:
                        z.state = "Broken"
                    elif hi >= z.proxVal:
                        z.touchCount += 1
            if z.state == "Tested" and z.touchCount > self.maxTestedCount:
                z.state = "Broken"
            if z.state == "Broken":
                z.breakBarIndex = i
                z.isFresh = False
                z.breakReason = "distal_break"
                z.zoneBox.set_bgcolor(("gray", 0.05))
                z.zoneBox.set_border_color(("gray", 0.20))
                self.live_zones.pop(k)
            else:
                z.zoneBox.set_right(i + 15)

    def run(self) -> List[Zone]:
        min_bar = max(self.atrPeriod, self.maxBaseCount + 3, 11)
        for i in range(self.n):
            if i >= min_bar and not np.isnan(self.atr[i]):
                self._scan_bar(i)
            self._update_states(i)
        return self.active_zones

def apply_pulse_trend(zones: List[Zone], df_pulse: pd.DataFrame, df_trend: pd.DataFrame, pulse_rule: str, trend_rule: str, pulse_tf: str = "", trend_tf: str = "") -> List[Zone]:
    if not zones or df_pulse is None or df_trend is None:
        return zones
    try:
        ps = pulse_state(df_pulse, pulse_rule).to_numpy()
        ts = trend_state(df_trend, trend_rule).to_numpy()
        p_idx = pd.DatetimeIndex(df_pulse.index)
        t_idx = pd.DatetimeIndex(df_trend.index)
        z_times = pd.DatetimeIndex([z.timestamp for z in zones])
        ppos = map_completed(z_times, p_idx)
        tpos = map_completed(z_times, t_idx)
        pv = np.where(ppos >= 0, ps[np.clip(ppos, 0, None)], 0).astype(int)
        tv = np.where(tpos >= 0, ts[np.clip(tpos, 0, None)], 0).astype(int)
        for z, p, t in zip(zones, pv, tv):
            z.pulse, z.trend = int(p), int(t)
            z.pulseRule, z.trendRule = pulse_rule, trend_rule
            z.pulseTf, z.trendTf = pulse_tf, trend_tf
            if z.isDemand:
                z.biasAligned = bool(p == 1 and t == 1)
            else:
                z.biasAligned = bool(p == -1 and t == -1)
    except Exception:
        pass
    return zones

PRESETS: Dict[str, Dict[str, Any]] = {
    "spec_strict": dict(),
    "max_zones": dict(legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0, requireEngulfForReversal=False, useLegOutRRFilter=False),
    "better_wr": dict(legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0, requireEngulfForReversal=False, requirePulseTrendAligned=True, useLegOutRRFilter=False),
    "high_accuracy": dict(legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0, requireEngulfForReversal=True, engulfMode="distal_close", requirePulseTrendAligned=True, useLegOutRRFilter=True),
    "no_rr_gate": dict(useLegOutRRFilter=False, legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0),
    "no_engulf": dict(requireEngulfForReversal=False, legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0),
    "no_pulse_trend": dict(requirePulseTrendAligned=False, legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0),
}

def _positive_float(value: Any, name: str) -> float:
    try:
        r = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(r) or r <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return r

def settings(accountCapital: Optional[float] = None, **overrides: Any) -> Dict[str, Any]:
    result = dict(PINE_DEFAULTS)
    if accountCapital is not None:
        overrides["accountCapital"] = accountCapital
    for k, v in overrides.items():
        if k in PINE_DEFAULTS:
            result[k] = v
    result["accountCapital"] = _positive_float(result["accountCapital"], "accountCapital")
    return result

def scan_zones(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None, accountCapital: Optional[float] = None, tf: Optional[str] = None) -> List[Zone]:
    incoming = dict(params or {})
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    cfg = settings(**incoming)
    return ZoneEngine(df, **cfg).run()

def scan_validated_zones(df_zone: pd.DataFrame, df_base: Optional[pd.DataFrame] = None, zone_tf: str = "1D", df_pulse: Optional[pd.DataFrame] = None, df_trend: Optional[pd.DataFrame] = None, pulse_rule: Optional[str] = None, pulse_tf: Optional[str] = None, trend_rule: Optional[str] = None, trend_tf: Optional[str] = None, require_aligned: bool = False, params: Optional[Dict[str, Any]] = None, accountCapital: Optional[float] = None) -> List[Zone]:
    incoming = dict(params or {})
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    cfg = settings(**incoming)
    zones = ZoneEngine(df_zone, **cfg).run()
    if not zones or not cfg.get("usePulseTrend", True):
        return [z for z in zones if (not require_aligned or z.biasAligned)]
    try:
        rules = resolve_rules(zone_tf)
        pulse_rule = pulse_rule or rules["pulse"]
        pulse_tf = pulse_tf or rules["pulse_tf"]
        trend_rule = trend_rule or rules["trend"]
        trend_tf = trend_tf or rules["trend_tf"]
        if df_pulse is None:
            if df_base is None:
                df_pulse = None
            else:
                try:
                    df_pulse = df_base if str(pulse_tf).upper() in ("", "SAME") else resample_ohlc(df_base, pulse_tf)
                except Exception:
                    df_pulse = df_base
        if df_trend is None:
            if df_base is None:
                df_trend = None
            else:
                try:
                    df_trend = df_base if str(trend_tf).upper() in ("", "SAME") else resample_ohlc(df_base, trend_tf)
                except Exception:
                    df_trend = df_base
        apply_pulse_trend(zones, df_pulse, df_trend, pulse_rule, trend_rule, pulse_tf, trend_tf)
    except Exception:
        pass
    if require_aligned or cfg.get("requirePulseTrendAligned", False):
        zones = [z for z in zones if z.biasAligned]
    return zones

def latest_active_zones(zones: List[Zone]) -> List[Zone]:
    return [z for z in zones if z.state in ("Fresh", "Tested")]

def high_quality_zones(zones: List[Zone]) -> List[Zone]:
    return [z for z in zones if z.isHQ]

def fresh_zones(zones: List[Zone]) -> List[Zone]:
    return [z for z in zones if z.state == "Fresh" and z.isFresh]

def tradable_zones(zones: List[Zone], require_aligned: bool = False) -> List[Zone]:
    out = []
    for z in zones:
        if not (z.validDemand or z.validSupply):
            continue
        if not z.legOutPassesRR:
            continue
        if z.entryBarIndex is None and z.state != "Fresh":
            continue
        if require_aligned and not z.biasAligned:
            continue
        out.append(z)
    return out

def summarize_zones(zones: List[Zone]) -> pd.DataFrame:
    if not zones:
        return pd.DataFrame()
    rows = []
    for z in zones:
        rows.append(dict(timestamp=z.timestamp, pattern=z.patternType, category=z.zoneCategory, side="Demand" if z.isDemand else "Supply", state=z.state, fresh=z.isFresh, proximal=z.proxVal, distal=z.distVal, sl=z.slVal, tp=z.tpVal, risk_pct=z.riskPct, legOutRR=z.legOutRR, rr_ok=z.legOutPassesRR, engulf=z.engulfOK, engulf_ref=z.engulfRefPattern, rule1=z.rule1OK, rule2=z.rule2OK, rule3=z.rule3OK, rule4=z.rule4OK, score=z.densityScore, HQ=z.isHQ, pulse=z.pulse, trend=z.trend, aligned=z.biasAligned, pulse_rule=f"{z.pulseRule}@{z.pulseTf}" if z.pulseRule else "", trend_rule=f"{z.trendRule}@{z.trendTf}" if z.trendRule else "", entry_bar=z.entryBarIndex, entry_price=z.entryPrice, break_bar=z.breakBarIndex))
    return pd.DataFrame(rows)
