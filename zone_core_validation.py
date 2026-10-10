"""
zone_core_validation_v2.py
==========================

`zone_core_validation.py` ke INPUT PARAMETERS aur RULES ko naye v2 niyamon se
badal diya gaya hai. Baaki sab (leg-in / base / leg-out checks, density scoring,
EOD range filter, duplicate detection, engulf rule, Fresh/Tested/Broken states,
SL/TP) bilkul waise hi hai -- sirf neeche likhi cheezein badli hain.

------------------------------ HATAYE GAYE (pulse/trend) ----------------------
  * RULE_TABLE_V2, resolve_rules(), apply_pulse_trend(), map_completed(),
    pulse_state(), trend_state(), PULSE_FUNCS, TREND_FUNCS aur saare indicator
    helpers (EMA stack/slope, EMA20/50, SMA200, MACD histogram, Supertrend
    ST_10_3 / ST_7_2 / ST_20_4, Donchian, DI cross).
  * Inputs: `usePulseTrend`, `requirePulseTrendAligned`.
  * Zone fields: `pulse`, `trend`, `pulseTf`, `trendTf`, `pulseRule`,
    `trendRule`, `biasAligned`.
  * scan_validated_zones() ke pulse/trend arguments.

------------------------------ NAYE v2 INPUTS --------------------------------
  requireCompletedLegOut      True    leg-out candle band hone par hi zone valid
  assumeLastBarLive           False   live scan me aakhri (forming) bar live maano
  requireEnvelopeInLegOut     False   entry+stop+target teeno lines leg-out ke andar (default OFF)
  envelopeRR                  3.0     kis RR tak envelope check (targetRR ke saath)
  envelopeCheckStopSide       False   distal (stop) line bhi block ke andar ho (default OFF)
  envelopeCheckTargetSide     False   1:RR target bhi block ke andar ho (default OFF)
  legOutContinuationCandles   3       single candle me na aaye to lagatar 3 candles
  requireHalfTfCheck          True    half time-frame validation ON
  halfTfMinAlignedPct         0.50    half bars ka aligned share
  halfTfMidBreakMode          "close" mid-line break: close par | "wick"
  halfTfMinRangeShare         0.25    har half-bar ka range >= 25% x avg half range
  halfDataMissingPolicy       "skip"  half data na ho to zone rakho ("reject" nahi)
  targetRR                    3.0     (Pine parity 5.0 -> aapka 1:3 plan)

Naye outputs (Zone fields): envelopeOK, envelopeTarget, blockCandles, blockHigh,
blockLow, legOutBarIndex, legOutComplete, validFromBarIndex, validFromTimestamp,
halfTF, halfOK, halfCheckSkipped, halfBars, halfAlignedPct, halfMidBreakBar,
halfCrossBar, + engine diagnostics (ZoneEngine.stats: reject_envelope,
env_fail_stop_side / env_fail_target_side / env_fail_both, reject_half_*).

------------------------------ HALF TIME-FRAME --------------------------------
  15m -> 5m   30m -> 15m   75m -> 30m   1H -> 30m   2H -> 1H
  4H  -> 2H   6H  -> 3H    1D  -> 3H    1W -> 2D    1M -> 2W
  (jo exactly aadha available na ho, uske aas-paas wala: 15m->5m, 75m->30m)

Half bars do tarah se milte hain:
  1. aap khud `half_df` pass karein (recommended -- jaisa backtest me kiya), ya
  2. `build_half_dataframe(zone_tf, df_base=1h_ya_daily_df)` se bana lein.

Zone TF ka half banana ke liye BARIK data chahiye (1h ya daily). Jaise 1H ka half
30m hai -- 1H bars se 30m bars nahi bana sakte, isliye df_base dena zaroori hai.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PINE_DEFAULTS: Dict[str, Any] = {
    "accountCapital": 25000.0,
    "riskPct": 0.5,
    "targetRR": 3.0,          # (v1: 5.0) aapka 1:3 plan
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

    # Pine parity (inert, jaisa zone_core.py me tha)
    "legOutToLegInBodyMult": 1.0,
    "baseBoringMaxBodyPct": 0.55,
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

    # Scanner-only EOD range inputs
    "eodHighBufferPct": 10.0,
    "eodLowBufferPct": 10.0,
    "useEodRange": True,

    # v1 ke optional validation inputs (bina pulse/trend)
    "useLegOutRRFilter": False,
    "minLegOutRR": 2.0,
    "requireEngulfForReversal": False,   # default OFF (pehle ON tha)
    "engulfLookbackBars": 25,
    "engulfAllowBrokenRef": True,
    "engulfMode": "distal_close",
    "engulfRefPosition": "high",
    "swingRangeAtrMult": 0.05,

    # ---------------- NAYE v2 niyam ----------------
    # (2) leg-out complete hone par hi valid
    "requireCompletedLegOut": True,
    "assumeLastBarLive": False,
    # (3) entry / SL / target leg-out (ya 3 continuation candles) ke andar
    "requireEnvelopeInLegOut": False,    # default OFF (pehle ON tha)
    "envelopeRR": 3.0,
    "envelopeCheckStopSide": False,    # distal (stop) check - default OFF
    "envelopeCheckTargetSide": False,  # 1:3 target check - default OFF
    "legOutContinuationCandles": 3,
    # (4) half time-frame validation
    "requireHalfTfCheck": True,
    "halfTfMinAlignedPct": 0.50,
    "halfTfMidBreakMode": "close",     # "close" | "wick"
    "halfTfMinRangeShare": 0.25,       # 0 = off
    # half data us period ke liye available na ho to: "skip" (zone chalta rahe)
    # ya "reject" (zone hata do). Default skip -- warna 60-din intraday limit
    # ki wajah se purane zones bina check ke hi mar jaate hain.
    "halfDataMissingPolicy": "skip",
}

HARD_MAX_BASE_COUNT = 3

# zone TF -> half TF (aadha; jo exactly na mile to aas-paas wala)
HALF_TF_MAP: Dict[str, str] = {
    "10m": "5m", "15m": "5m", "30m": "15m", "75m": "30m",
    "1H": "30m", "2H": "1H", "3H": "1H", "4H": "2H", "6H": "3H",
    "1D": "3H", "1W": "2D", "1M": "2W",
}


def half_timeframe_of(tf: str) -> str:
    """Zone timeframe se half timeframe. 15m -> 5m (7.5m available nahi)."""
    key = str(tf).strip()
    return HALF_TF_MAP.get(key, HALF_TF_MAP.get(key.upper(), "5m"))


@dataclass
class Box:
    left: int
    top: float
    right: int
    bottom: float
    border_color: object
    bgcolor: object

    def set_right(self, right: int) -> None:
        self.right = right

    def set_bgcolor(self, c: object) -> None:
        self.bgcolor = c

    def set_border_color(self, c: object) -> None:
        self.border_color = c


@dataclass
class Zone:
    # Original Zone fields -- same order (compatibility)
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

    # v1 ke validation outputs
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

    # v2: leg-out block + validation outputs
    legOutBarIndex: int = -1
    legOutComplete: bool = True
    blockCandles: int = 1
    blockHigh: float = float("nan")
    blockLow: float = float("nan")
    validFromBarIndex: int = -1
    validFromTimestamp: object = None
    envelopeOK: bool = False
    envelopeTarget: float = float("nan")
    halfTF: str = ""
    halfOK: bool = True
    halfCheckSkipped: bool = False
    halfBars: int = 0
    halfAlignedPct: float = float("nan")
    halfMidBreakBar: Optional[int] = None
    halfCrossBar: Optional[int] = None

    # (bug-fix) fresh_zones() crash na kare
    isFresh: bool = True


def _positive_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def get_eod_range(df: pd.DataFrame, idx: int, high_buffer_pct: float = 10.0,
                  low_buffer_pct: float = 10.0) -> Tuple[float, float]:
    try:
        day_value = df.index[idx].date()
        day = df[df.index.date == day_value]
        if day.empty:
            return float(df["low"].iloc[idx] * 0.9), float(df["high"].iloc[idx] * 1.1)
        return (float(day["low"].min() * (1 - low_buffer_pct / 100)),
                float(day["high"].max() * (1 + high_buffer_pct / 100)))
    except Exception:
        return float(df["low"].iloc[idx] * 0.9), float(df["high"].iloc[idx] * 1.1)


def check_white_area(df: pd.DataFrame, base_start_idx: int, base_end_idx: int,
                     leg_out_idx: int, curr_idx: int) -> bool:
    base_high = float(df["high"].iloc[base_start_idx: base_end_idx + 1].max())
    base_low = float(df["low"].iloc[base_start_idx: base_end_idx + 1].min())
    if leg_out_idx + 1 >= curr_idx:
        return True
    window = df.iloc[leg_out_idx + 1: curr_idx]
    return not bool(((window["low"] <= base_high) & (window["high"] >= base_low)).any())


def check_leg_out_coverage(df: pd.DataFrame, leg_out_idx: int, curr_idx: int,
                           max_cover_pct: float = 90.0) -> bool:
    high = float(df["high"].iloc[leg_out_idx])
    low = float(df["low"].iloc[leg_out_idx])
    candle_range = high - low
    if candle_range <= 0 or leg_out_idx + 1 > curr_idx:
        return True
    window = df.iloc[leg_out_idx + 1: curr_idx + 1]
    overlap = (np.minimum(window["high"], high) - np.maximum(window["low"], low)).clip(lower=0)
    return not bool(((overlap / candle_range) > max_cover_pct / 100).any())


SCAN_TRACKER: Dict[str, datetime] = {}


def should_scan_now(tf: str, force: bool = False) -> bool:
    now = datetime.now()
    if force:
        return True
    days = {"Monthly": 30, "Weekly": 7, "Daily": 1}
    key = tf if tf in days else f"Intraday_{tf}"
    last = SCAN_TRACKER.get(key)
    minutes = {"3M": 3, "5M": 5, "10M": 10, "15M": 15, "30M": 30, "75M": 75,
               "1H": 60, "2H": 120, "4H": 240, "6H": 360}.get(tf, 15)
    wait_seconds = days[tf] * 86400 if tf in days else minutes * 60
    if last is None or (now - last).total_seconds() >= wait_seconds:
        SCAN_TRACKER[key] = now
        return True
    return False


# =============================== Zone engine ===============================
SESSION_OPEN_MIN = 9 * 60 + 15        # NSE open 09:15 IST
SESSION_TOTAL_MIN = 6 * 60 + 15        # 09:15 -> 15:30

# half TF -> (bucket minutes, min_fill, source cadence)
#   source cadence = us half ko banane ke liye kitne barik data chahiye
_HALF_SPEC: Dict[str, Tuple[int, float]] = {
    "5m": (5, 0.9), "15m": (15, 0.9), "30m": (30, 0.6),
    "1H": (60, 0.9), "2H": (120, 0.9), "3H": (180, 0.9),
}


def to_naive_ist(df: pd.DataFrame) -> pd.DataFrame:
    """Timezone-naive IST wall-clock index (backtest jaisa hi)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("Asia/Kolkata").tz_localize(None)
    return out


def _median_bar_minutes(df: pd.DataFrame) -> float:
    """Data ka median bar size (minutes me)."""
    if df is None or len(df.index) < 2:
        return float("nan")
    try:
        diffs = np.diff(pd.DatetimeIndex(df.index).asi8)
        diffs = diffs[diffs > 0]
        if len(diffs) == 0:
            return float("nan")
        return float(np.median(diffs)) / 6e10
    except Exception:                                                # noqa: BLE001
        return float("nan")


def session_resample(df: pd.DataFrame, minutes: int, min_fill: float = 0.9) -> pd.DataFrame:
    """Intraday bars ko NSE session (09:15) par anchor karke resample karta hai.

    Buckets 09:15 se shuru; partial tail buckets (jaise 15:15 ka 15-min stub)
    min_fill se chhote hone par drop ho jaate hain -- yehi algorithm backtest me
    use hua hai, isliye half frames bilkul wahi bante hain.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    d = to_naive_ist(df)
    idx = pd.DatetimeIndex(d.index)
    mod = (idx.hour * 60 + idx.minute) - SESSION_OPEN_MIN
    bucket = np.floor_divide(mod.to_numpy(), minutes)
    bucket = np.where(mod.to_numpy() < 0, -1, bucket)
    work = pd.DataFrame({
        "open": d["open"].to_numpy(), "high": d["high"].to_numpy(),
        "low": d["low"].to_numpy(), "close": d["close"].to_numpy(),
        "volume": d["volume"].to_numpy() if "volume" in d.columns else 0.0,
        "__d__": idx.normalize(), "__b__": bucket, "__t__": idx,
    }, index=idx)
    work = work[work["__b__"] >= 0]
    if work.empty:
        return pd.DataFrame()
    agg = work.groupby(["__d__", "__b__"], sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), start=("__t__", "first"))
    start_min = agg.index.get_level_values("__b__").to_numpy() * minutes
    coverage = np.minimum(minutes, SESSION_TOTAL_MIN - start_min)
    agg = agg[coverage >= min_fill * minutes]
    out = pd.DataFrame({c: agg[c].to_numpy() for c in ("open", "high", "low", "close", "volume")},
                       index=pd.DatetimeIndex(agg["start"].to_numpy()))
    return out.sort_index()


def _half_from_daily(daily: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Daily bars se half frame:
       '2D' = har week ke andar do-do session ka block (Mon+Tue, Wed+Thu, Fri),
       '2W' = mahine ka 1-14 aur 15-end."""
    if daily is None or len(daily) == 0:
        return pd.DataFrame()
    d = to_naive_ist(daily)
    d = d.copy()
    d["__t__"] = pd.DatetimeIndex(d.index)
    cal = pd.DatetimeIndex(d.index).isocalendar()
    if mode == "2D":
        d["__y__"] = np.asarray(cal.year)
        d["__w__"] = np.asarray(cal.week)
        d["__pair__"] = d.groupby(["__y__", "__w__"]).cumcount().to_numpy() // 2
        keys = ["__y__", "__w__", "__pair__"]
    elif mode == "2W":
        d["__y__"] = pd.DatetimeIndex(d.index).year
        d["__m__"] = pd.DatetimeIndex(d.index).month
        d["__half__"] = (pd.DatetimeIndex(d.index).day > 14).astype(int)
        keys = ["__y__", "__m__", "__half__"]
    else:
        raise ValueError(f"unsupported mode {mode!r}")
    g = d.groupby(keys, sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), start=("__t__", "first"))
    out = pd.DataFrame({c: g[c].to_numpy() for c in ("open", "high", "low", "close", "volume")},
                       index=pd.DatetimeIndex(g["start"].to_numpy()))
    return out.sort_index()


def build_half_dataframe(zone_tf: str, df_base: Optional[pd.DataFrame] = None,
                         df_zone: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Zone TF ka half time-frame frame banata hai (backtest jaisa hi algorithm).

    df_base = zaroori barik data:
        15m -> 5m   : 5m bars       30m -> 15m  : 15m bars
        75m -> 30m  : 30m bars      1H  -> 30m  : 30m bars
        2H  -> 1H   : 1h bars       4H  -> 2H   : 1h bars
        6H  -> 3H   : 1h bars       1D  -> 3H   : 1h bars
        1W  -> 2D   : daily bars    1M  -> 2W   : daily bars
    Barik data na mile to khaali DataFrame lautata hai -- tab engine ka
    halfDataMissingPolicy lagega ("skip" default). Coarse data de kar barik half
    banane ki koshish par saaf error aata hai.
    """
    half = half_timeframe_of(zone_tf)
    if half in ("2D", "2W"):
        src = df_base if (df_base is not None and len(df_base)) else df_zone
        if src is None or len(src) == 0:
            return pd.DataFrame()
        return _half_from_daily(src, half)

    spec = _HALF_SPEC.get(half)
    if spec is None:
        return pd.DataFrame()
    minutes, min_fill = spec
    src = df_base if (df_base is not None and len(df_base)) else df_zone
    if src is None or len(src) == 0:
        return pd.DataFrame()
    cadence = _median_bar_minutes(src)
    if np.isfinite(cadence) and cadence > minutes + 1e-9:
        raise ValueError(
            f"{zone_tf} ka half ({half}) banane ke liye {minutes}-minute ya usse barik "
            f"data chahiye, par diya gaya data ~{cadence:.0f}-minute hai.")
    return session_resample(src, minutes, min_fill)


class ZoneEngine:
    def __init__(self, df: pd.DataFrame, half_df: Optional[pd.DataFrame] = None,
                 **kwargs: Any):
        self.df = df.copy()
        if "volume" not in self.df.columns:
            self.df["volume"] = 0.0
        self.df["volume"] = self.df["volume"].fillna(0.0)
        for key, default in PINE_DEFAULTS.items():
            setattr(self, key, kwargs.get(key, default))

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
        self.ns = time_index.astype("datetime64[ns]").astype(np.int64)

        # zone TF ka nominal duration (minutes)
        if self.n > 1:
            diffs = np.diff(self.ns)
            diffs = diffs[diffs > 0]
            self.bar_minutes = float(np.median(diffs)) / 6e10 if len(diffs) else 0.0
        else:
            self.bar_minutes = 0.0
        self.is_intraday_tf = self.bar_minutes < 24 * 60 * 0.9

        # half time-frame data
        self.half_tf_name = str(kwargs.get("half_tf_name", ""))
        if half_df is not None and len(half_df):
            hdf = half_df.copy()
            hidx = hdf.index
            if hidx.tz is not None:
                hidx = hidx.tz_convert("UTC").tz_localize(None)
            self.half_ns = hidx.astype("datetime64[ns]").astype(np.int64)
            self.half_o = hdf["open"].to_numpy(float)
            self.half_h = hdf["high"].to_numpy(float)
            self.half_l = hdf["low"].to_numpy(float)
            self.half_c = hdf["close"].to_numpy(float)
            self.half_n = len(hdf)
        else:
            self.half_ns = np.empty(0, dtype=np.int64)
            self.half_o = self.half_h = self.half_l = self.half_c = np.empty(0, dtype=float)
            self.half_n = 0

        self.active_zones: List[Zone] = []
        self.live_zones: List[Zone] = []
        self.pattern_registry: List[Zone] = []
        self.stats: Counter = Counter()
        self._prepare()

    # ---------------------------- helpers ----------------------------
    def _rma(self, values: np.ndarray, length: int) -> np.ndarray:
        result = np.full(len(values), np.nan)
        if len(values) < length:
            return result
        result[length - 1] = np.mean(values[:length])
        for i in range(length, len(values)):
            result[i] = (values[i] - result[i - 1]) / length + result[i - 1]
        return result

    def _prepare(self) -> None:
        true_range = self.h - self.l
        if self.n > 1:
            previous_close = self.c[:-1]
            true_range[1:] = np.maximum(
                true_range[1:],
                np.maximum(np.abs(self.h[1:] - previous_close),
                           np.abs(self.l[1:] - previous_close)))
        self.atr = self._rma(true_range, self.atrPeriod)
        self.vol_sma = self.df["volume"].rolling(self.volSmaPeriod).mean().to_numpy()
        day_key = self.df.index.normalize()
        self.day_high = self.df["high"].groupby(day_key).transform("max").to_numpy()
        self.day_low = self.df["low"].groupby(day_key).transform("min").to_numpy()

    def _tr(self, p: int) -> float:
        previous_close = self.c[p - 1]
        return max(self.h[p] - self.l[p], abs(self.h[p] - previous_close),
                   abs(self.l[p] - previous_close))

    def _bull(self, p: int) -> bool:
        return bool(self.c[p] > self.o[p])

    def _bear(self, p: int) -> bool:
        return bool(self.o[p] > self.c[p])

    def _wick_pct(self, p: int) -> float:
        candle_range = self.h[p] - self.l[p]
        if candle_range == 0:
            return 0.0
        wick = (self.h[p] - max(self.o[p], self.c[p])) + (min(self.o[p], self.c[p]) - self.l[p])
        return wick / candle_range

    def _body_pct(self, p: int) -> float:
        candle_range = self.h[p] - self.l[p]
        if candle_range == 0:
            return 0.0
        return abs(self.c[p] - self.o[p]) / candle_range

    def _swing_ok(self, p: int) -> bool:
        candle_range = self.h[p] - self.l[p]
        atr_value = self.atr[p]
        if not np.isfinite(atr_value) or atr_value <= 0:
            return False
        return candle_range >= self.swingRangeAtrMult * atr_value

    def _overnight(self, i: int) -> bool:
        if i == 0:
            return False
        return bool(self.dow[i] != self.dow[i - 1]
                    or (self.time_ms[i] - self.time_ms[i - 1]) > 86400000)

    def _is_complete_bar(self, j: int) -> bool:
        """Naya niyam (2): adhoora candle (assumeLastBarLive) complete nahi mana jata."""
        if j < 0 or j >= self.n:
            return False
        if self.assumeLastBarLive and j >= self.n - 1:
            return False
        return True

    # -------------------- half time-frame validation --------------------
    def _bar_span_ns(self, i: int, k: int) -> Tuple[int, int]:
        start = int(self.ns[i])
        end = start + int(self.bar_minutes * k * 6e10)
        if not self.is_intraday_tf:
            nxt = i + k
            if nxt < self.n:
                end = int(self.ns[nxt])
            return start, end
        nxt = i + k
        if nxt < self.n and int(self.ns[nxt]) > start:
            end = min(end, int(self.ns[nxt]))
        return start, end

    def _half_missing(self, info: Dict[str, Any], reason: str) -> Tuple[bool, Dict[str, Any]]:
        """Half bar hi na mile to policy: skip (pass) ya reject."""
        info["halfSkipped"] = True
        info["reason"] = reason
        if str(self.halfDataMissingPolicy).lower().startswith("reject"):
            return (not bool(self.requireHalfTfCheck)), info
        return True, info

    def _half_validate(self, start_ns: int, end_ns: int, is_demand: bool,
                       block_high: float, block_low: float) -> Tuple[bool, Dict[str, Any]]:
        info: Dict[str, Any] = dict(halfBars=0, halfAlignedPct=float("nan"),
                                    halfMidBreakBar=None, halfCrossBar=None,
                                    halfSkipped=False, reason="")
        if self.half_n == 0:
            return self._half_missing(info, "no_half_data")

        lo = int(np.searchsorted(self.half_ns, start_ns, "left"))
        hi = int(np.searchsorted(self.half_ns, end_ns, "left"))
        if hi <= lo:
            # span ke andar koi half-bar shuru nahi hota -> us bar ko lena jo span
            # ke start ko COVER karta ho; agar half data ki coverage hi nahi hai to
            # check skip (pass) -- warna galat bar par valid/reject ho jaata.
            pos = int(np.searchsorted(self.half_ns, start_ns, "right")) - 1
            if pos < 0 or pos >= self.half_n:
                return self._half_missing(info, "half_data_out_of_range")
            half_dur_ns = 0
            if self.half_n > 1:
                _d = np.diff(self.half_ns)
                _d = _d[_d > 0]
                half_dur_ns = int(np.median(_d)) if len(_d) else 0
            if half_dur_ns and not (int(self.half_ns[pos]) <= start_ns < int(self.half_ns[pos]) + half_dur_ns):
                return self._half_missing(info, "half_data_out_of_range")
            if pos == self.half_n - 1 and start_ns > int(self.half_ns[-1]):
                return self._half_missing(info, "half_data_out_of_range")
            lo, hi = pos, pos + 1
        idxs = list(range(lo, hi))
        info["halfBars"] = len(idxs)

        mid = (float(block_high) + float(block_low)) / 2.0
        ho, hh, hl, hc = self.half_o, self.half_h, self.half_l, self.half_c

        aligned = 0
        for j in idxs:
            if (hc[j] > ho[j]) if is_demand else (hc[j] < ho[j]):
                aligned += 1
        info["halfAlignedPct"] = aligned / len(idxs)

        cross: Optional[int] = None
        for j in idxs:
            if (hh[j] >= mid) if is_demand else (hl[j] <= mid):
                cross = j
                break
        info["halfCrossBar"] = None if cross is None else int(cross)
        if cross is None:
            info["reason"] = "half_never_crossed_mid"
            return False, info
        if (hc[cross] < mid) if is_demand else (hc[cross] > mid):
            info["reason"] = "half_cross_bar_closed_wrong_side"
            return False, info

        use_wick = str(self.halfTfMidBreakMode).lower().startswith("wick")
        for j in idxs:
            if j <= cross:
                continue
            if is_demand:
                bad = (hl[j] < mid) if use_wick else (hc[j] < mid)
            else:
                bad = (hh[j] > mid) if use_wick else (hc[j] > mid)
            if bad:
                info["halfMidBreakBar"] = int(j)
                info["reason"] = "half_mid_break"
                return False, info

        if float(info["halfAlignedPct"]) < float(self.halfTfMinAlignedPct):
            info["reason"] = "half_aligned_share_low"
            return False, info

        if float(self.halfTfMinRangeShare) > 0:
            even = (float(block_high) - float(block_low)) / max(1, len(idxs))
            need = float(self.halfTfMinRangeShare) * even
            for j in idxs:
                if (hh[j] - hl[j]) < need:
                    info["reason"] = "half_bar_not_explosive"
                    return False, info
        return True, info

    # -------------------- leg-out block + envelope --------------------
    def _continuation_block(self, i: int, max_candles: int) -> int:
        """leg-out candle se shuru karke lagatar same-direction candles (max 3)."""
        k = 1
        if max_candles <= 1:
            return k
        want_bull = self._bull(i)
        j = i + 1
        while k < max_candles and self._is_complete_bar(j):
            if (self._bull(j) if want_bull else self._bear(j)):
                k += 1
                j += 1
            else:
                break
        return k

    @staticmethod
    def _envelope_check(is_demand: bool, proximal: float, distal: float,
                        block_high: float, block_low: float, rr: float,
                        check_stop_side: bool = True,
                        check_target_side: bool = True) -> Tuple[bool, float]:
        """Teen lines (entry=proximal, stop=distal, target) block ke andar?
        check_stop_side / check_target_side se dono hisse alag-alag band kiye ja sakte hain."""
        if is_demand:
            target = proximal + rr * (proximal - distal)
            stop_ok = (block_low <= distal + 1e-9)
            target_ok = (target <= block_high + 1e-9)
        else:
            target = proximal - rr * (distal - proximal)
            stop_ok = (block_high >= distal - 1e-9)
            target_ok = (target >= block_low - 1e-9)
        ok = True
        if check_stop_side:
            ok = ok and stop_ok
        if check_target_side:
            ok = ok and target_ok
        return bool(ok), float(target)

    # ------------------------- engulf (unchanged) -------------------------
    @staticmethod
    def _is_dbd_like(zone: Zone) -> bool:
        return (not zone.isDemand) and (zone.patternType == "DBD"
                                        or zone.zoneCategory == "Continuation")

    @staticmethod
    def _is_rbr_like(zone: Zone) -> bool:
        return zone.isDemand and (zone.patternType == "RBR"
                                  or zone.zoneCategory == "Continuation")

    def _find_engulf_ref(self, i: int, is_demand: bool, in_high: float, in_low: float,
                         out_close: float, atr_now: float, max_prox: float, min_prox: float,
                         out_high: float, out_low: float) -> Optional[Zone]:
        best: Optional[Zone] = None
        minimum_zone_width = self.swingRangeAtrMult * atr_now
        ref_position = (self.engulfRefPosition or "high").lower()
        engulf_mode = (self.engulfMode or "distal_close").lower()
        use_proximal = engulf_mode.startswith("proximal")
        use_wick = engulf_mode.endswith("wick")
        probe = (out_high if is_demand else out_low) if use_wick else out_close

        for zone in reversed(self.pattern_registry):
            age = i - zone.legOutBarIndex
            if age > self.engulfLookbackBars:
                break
            if zone.legOutBarIndex >= i:
                continue
            if not self.engulfAllowBrokenRef and zone.state == "Broken":
                continue
            if abs(zone.proxVal - zone.distVal) < minimum_zone_width:
                continue
            if is_demand:
                if not self._is_dbd_like(zone):
                    continue
                level = max_prox if ref_position == "base" else (in_high if ref_position == "high" else in_low)
                if zone.distVal <= level:
                    continue
                reference_line = zone.proxVal if use_proximal else zone.distVal
                if not probe > reference_line:
                    continue
                if best is None:
                    best = zone
                else:
                    best_line = best.proxVal if use_proximal else best.distVal
                    if reference_line < best_line:
                        best = zone
            else:
                if not self._is_rbr_like(zone):
                    continue
                level = min_prox if ref_position == "base" else (in_low if ref_position == "high" else in_high)
                if zone.distVal >= level:
                    continue
                reference_line = zone.proxVal if use_proximal else zone.distVal
                if not probe < reference_line:
                    continue
                if best is None:
                    best = zone
                else:
                    best_line = best.proxVal if use_proximal else best.distVal
                    if reference_line > best_line:
                        best = zone
        return best

    # ------------------------------ scan ------------------------------
    def _scan_bar(self, i: int) -> None:
        if self.requireCompletedLegOut and not self._is_complete_bar(i):
            self.stats["skip_legout_incomplete"] += 1
            return

        atr_now = self.atr[i]
        found = False
        for base_count in range(self.minBaseCount, self.maxBaseCount + 1):
            if found:
                break
            leg_in_offset = base_count + 1
            previous_offset = leg_in_offset + 1
            p_in = i - leg_in_offset
            p_prev = i - previous_offset
            p_out = i
            if p_prev < 0 or np.isnan(self.atr[p_in]):
                continue

            if not (self._swing_ok(p_in) and self._swing_ok(p_out)):
                self.stats["reject_swing_range"] += 1
                continue

            leg_in_tr = self._tr(p_in)
            in_low, in_high, in_close = self.l[p_in], self.h[p_in], self.c[p_in]
            in_vol = self.v[p_in]
            in_range = in_high - in_low
            in_bull, in_bear = self._bull(p_in), self._bear(p_in)
            if in_range == 0 or self._body_pct(p_in) < self.legInMinBodyPct:
                self.stats["reject_legin_body"] += 1
                continue

            if (in_bull and self._bear(p_prev)) or (in_bear and self._bull(p_prev)):
                previous_body_high = max(self.o[p_prev], self.c[p_prev])
                previous_body_low = min(self.o[p_prev], self.c[p_prev])
                overlap = max(0.0, min(previous_body_high, in_high) - max(previous_body_low, in_low))
                if overlap / in_range >= self.rejectOppositeCoverPct:
                    self.stats["reject_opposite_cover"] += 1
                    continue

            bull_clv = (in_close - in_low) / in_range
            bear_clv = (in_high - in_close) / in_range

            valid_base = True
            max_base_tr = 0.0
            max_base_high = -1.0
            min_base_low = 1_000_000_000.0
            for base_offset in range(1, base_count + 1):
                p_base = i - base_offset
                if np.isnan(self.atr[p_base]):
                    valid_base = False
                    break
                base_tr = self._tr(p_base)
                if base_tr > self.maxBaseAtrMult * self.atr[p_base]:
                    valid_base = False
                    break
                max_base_tr = max(max_base_tr, base_tr)
                max_base_high = max(max_base_high, self.h[p_base])
                min_base_low = min(min_base_low, self.l[p_base])
            if not valid_base or max_base_tr == 0:
                self.stats["reject_base"] += 1
                continue

            effective_multiplier = 1.5 if base_count == 1 else self.legInToBaseSizeMult
            if leg_in_tr < effective_multiplier * max_base_tr:
                self.stats["reject_legin_to_base"] += 1
                continue
            if leg_in_tr < self.legInMinAtrMult * self.atr[p_in]:
                self.stats["reject_legin_atr"] += 1
                continue

            leg_out_tr = self._tr(p_out)
            out_high, out_low = self.h[p_out], self.l[p_out]
            out_close, out_open = self.c[p_out], self.o[p_out]
            out_vol = self.v[p_out]
            is_demand = self._bull(p_out)
            is_supply = self._bear(p_out)
            if not (is_demand or is_supply):
                self.stats["reject_legout_doji"] += 1
                continue

            explosive = leg_out_tr >= self.legOutTrMult * self.atr[p_out]
            wick_ok = self._wick_pct(p_out) <= self.maxWickPct
            tr_hierarchy_ok = (leg_out_tr >= self.legOutMinTrRatio * leg_in_tr
                               and leg_in_tr > max_base_tr)
            volume_ok = out_vol > in_vol
            is_overnight = self._overnight(i)

            has_imbalance = True
            has_gap = False
            gap_size = 0.0
            if self.useImbalance:
                if is_demand:
                    has_gap = out_low > max_base_high
                    has_imbalance = has_gap or (out_close > in_high)
                    gap_size = max(0.0, out_low - max_base_high)
                else:
                    has_gap = out_high < min_base_low
                    has_imbalance = has_gap or (out_close < in_low)
                    gap_size = max(0.0, min_base_low - out_high)

            if (min(out_open, out_close) <= min_base_low
                    and max(out_open, out_close) >= max_base_high and not has_gap):
                self.stats["reject_out_inside_base"] += 1
                continue

            is_rbr = in_bull and bull_clv >= self.minClvPct and is_demand
            is_dbr = in_bear and bear_clv >= self.minClvPct and is_demand
            is_dbd = in_bear and bear_clv >= self.minClvPct and is_supply
            is_rbd = in_bull and bull_clv >= self.minClvPct and is_supply
            if not (is_rbr or is_dbr or is_dbd or is_rbd):
                self.stats["reject_pattern"] += 1
                continue
            if not (explosive and wick_ok and tr_hierarchy_ok and volume_ok and has_imbalance):
                self.stats["reject_legout_quality"] += 1
                continue

            score = 0
            if base_count == 1:
                score += 15
            if leg_in_tr >= self.hqLegInAtrMult * self.atr[p_in]:
                score += 10
            if leg_out_tr >= self.hqLegOutTrMult * leg_in_tr:
                score += 15
            if leg_in_tr >= 2.0 * max_base_tr and leg_out_tr >= 2.0 * leg_in_tr:
                score += 15
            if out_vol > self.vol_sma[p_out]:
                score += 10
            out_range = out_high - out_low
            if is_demand:
                close_position = (out_close - out_low) / out_range if out_range > 0 else 0
                own_body = self._body_pct(p_out)
                if is_dbr:
                    if close_position >= 0.80 or own_body >= self.legOutBodyHeavyPct:
                        score += 15
                elif close_position >= 0.80:
                    score += 15
            else:
                close_position = (out_high - out_close) / out_range if out_range > 0 else 0
                if close_position >= 0.80:
                    score += 15

            opposite_base = any((is_demand and self._bear(i - offset))
                                or (is_supply and self._bull(i - offset))
                                for offset in range(1, base_count + 1))
            if opposite_base:
                score += 10
            score += 10
            if has_gap:
                score += self.genuineGapBonus
            if is_overnight and has_gap:
                score += self.overnightGapBonus
            if score < self.minValidScore:
                self.stats["reject_score"] += 1
                continue

            proximal = max_base_high if is_demand else min_base_low
            distal = min_base_low if is_demand else max_base_high
            if self.useEodRange:
                eod_high = self.day_high[i] * (1 + self.eodHighBufferPct / 100.0)
                eod_low = self.day_low[i] * (1 - self.eodLowBufferPct / 100.0)
                if not (eod_low <= proximal <= eod_high):
                    self.stats["reject_eod_range"] += 1
                    continue

            sl = (distal - self.slBufferAtr * atr_now if is_demand
                  else distal + self.slBufferAtr * atr_now)
            risk = abs(proximal - sl)
            tp = (proximal + risk * self.targetRR if is_demand
                  else proximal - risk * self.targetRR)
            if is_demand:
                mid = out_high - self.testedLegOutRetracePct * (out_high - out_low)
                leg_out_reward = out_high - proximal
            else:
                mid = out_low + self.testedLegOutRetracePct * (out_high - out_low)
                leg_out_reward = proximal - out_low
            leg_out_rr = leg_out_reward / risk if risk > 0 else float("nan")
            leg_out_passes_rr = bool(np.isfinite(leg_out_rr) and leg_out_rr >= self.minLegOutRR)
            if self.useLegOutRRFilter and not leg_out_passes_rr:
                self.stats["reject_legout_rr"] += 1
                continue

            pattern = "RBR" if is_rbr else ("DBR" if is_dbr else ("DBD" if is_dbd else "RBD"))
            category = "Continuation" if (is_rbr or is_dbd) else "Reversal"

            engulf_ref: Optional[Zone] = None
            rule1_ok = bool(is_rbr)
            rule2_ok = bool(is_dbd)
            rule3_ok = False
            rule4_ok = False
            if is_dbr:
                if self.requireEngulfForReversal:
                    engulf_ref = self._find_engulf_ref(i, True, in_high, in_low, out_close,
                                                       atr_now, max_prox=proximal,
                                                       min_prox=proximal,
                                                       out_high=out_high, out_low=out_low)
                    rule3_ok = engulf_ref is not None
                else:
                    rule3_ok = True
                if not rule3_ok:
                    self.stats["reject_engulf_dbr"] += 1
                    continue
            elif is_rbd:
                if self.requireEngulfForReversal:
                    engulf_ref = self._find_engulf_ref(i, False, in_high, in_low, out_close,
                                                       atr_now, max_prox=proximal,
                                                       min_prox=proximal,
                                                       out_high=out_high, out_low=out_low)
                    rule4_ok = engulf_ref is not None
                else:
                    rule4_ok = True
                if not rule4_ok:
                    self.stats["reject_engulf_rbd"] += 1
                    continue

            valid_demand = bool((is_rbr and rule1_ok) or (is_dbr and rule3_ok))
            valid_supply = bool((is_dbd and rule2_ok) or (is_rbd and rule4_ok))
            if is_demand and not valid_demand:
                self.stats["reject_valid_demand"] += 1
                continue
            if is_supply and not valid_supply:
                self.stats["reject_valid_supply"] += 1
                continue

            # ---------- NAYA (3): trade envelope leg-out ke andar ----------
            max_candles = int(self.legOutContinuationCandles) if self.requireEnvelopeInLegOut else 1
            if max_candles < 1:
                max_candles = 1
            k_avail = self._continuation_block(i, max_candles)
            block_k = 0
            block_high = block_low = float("nan")
            env_target = float("nan")
            env_ok = False
            if not self.requireEnvelopeInLegOut:
                block_k, block_high, block_low = 1, out_high, out_low
                env_ok, env_target = True, float("nan")
            else:
                for k in range(1, k_avail + 1):
                    hi_k = float(np.max(self.h[i: i + k]))
                    lo_k = float(np.min(self.l[i: i + k]))
                    ok_k, tgt_k = self._envelope_check(
                        is_demand, proximal, distal, hi_k, lo_k, float(self.envelopeRR),
                        bool(self.envelopeCheckStopSide), bool(self.envelopeCheckTargetSide))
                    if ok_k:
                        block_k, block_high, block_low = k, hi_k, lo_k
                        env_ok, env_target = True, tgt_k
                        break
                if not env_ok:
                    self.stats["reject_envelope"] += 1
                    # diagnosis: single-candle par kaun-si shart fail hui?
                    hi1, lo1 = float(self.h[i]), float(self.l[i])
                    rr = float(self.envelopeRR)
                    if is_demand:
                        t_ok = (proximal + rr * (proximal - distal)) <= hi1 + 1e-9
                        s_ok = lo1 <= distal + 1e-9
                    else:
                        t_ok = (proximal - rr * (distal - proximal)) >= lo1 - 1e-9
                        s_ok = hi1 >= distal - 1e-9
                    if t_ok and not s_ok:
                        self.stats["env_fail_stop_side"] += 1
                    elif s_ok and not t_ok:
                        self.stats["env_fail_target_side"] += 1
                    else:
                        self.stats["env_fail_both"] += 1
                    continue

            block_end = i + block_k - 1
            block_last_complete = self._is_complete_bar(block_end)
            if self.requireCompletedLegOut and not block_last_complete:
                self.stats["reject_block_incomplete"] += 1
                continue

            # ---------- NAYA (4): half time-frame validation ----------
            h_ok, h_info = True, dict(halfBars=0, halfAlignedPct=float("nan"),
                                      halfMidBreakBar=None, halfCrossBar=None,
                                      halfSkipped=True, reason="disabled")
            if self.requireHalfTfCheck:
                start_ns, end_ns = self._bar_span_ns(i, block_k)
                h_ok, h_info = self._half_validate(start_ns, end_ns, is_demand,
                                                   block_high, block_low)
                if h_info.get("halfSkipped"):
                    self.stats["half_skipped"] += 1
                if not h_ok:
                    self.stats[f"reject_half_{h_info.get('reason', 'other')}"] += 1
                    continue

            # duplicate check (purana behaviour)
            found = True
            duplicate = False
            checked = 0
            for existing in reversed(self.live_zones):
                if (existing.isDemand == is_demand
                        and abs(existing.proxVal - proximal) < atr_now * 0.25):
                    duplicate = True
                    break
                checked += 1
                if checked >= 11:
                    break
            if duplicate:
                self.stats["reject_duplicate"] += 1
                continue

            border = "green" if is_demand else "red"
            fill = ("green", 0.15) if is_demand else ("red", 0.15)
            vol_sma_in, vol_sma_out = self.vol_sma[p_in], self.vol_sma[p_out]
            valid_from = block_end + 1
            zone = Zone(
                proxVal=proximal, distVal=distal, slVal=sl, tpVal=tp,
                isDemand=is_demand, isHQ=bool(score >= self.hqScoreThreshold),
                densityScore=score, patternType=pattern, zoneCategory=category,
                state="Fresh", touchCount=0,
                startBarIndex=i - base_count, createdBarIndex=block_end,
                baseCount=base_count, legOutHigh=out_high, legOutLow=out_low,
                legOutMidLevel=mid, isOvernight=is_overnight, legInTR=leg_in_tr,
                legOutTR=leg_out_tr,
                zoneBox=Box(i - base_count - 1, proximal, i + 15, distal, border, fill),
                timestamp=self.df.index[i],
                riskPct=risk / proximal * 100.0 if proximal else float("nan"),
                score10=round(score / 10.0, 1), hasGenuineGap=has_gap, gapToLegIn=gap_size,
                legInVolX=(in_vol / vol_sma_in if vol_sma_in and not np.isnan(vol_sma_in) else float("nan")),
                legOutVolX=(out_vol / vol_sma_out if vol_sma_out and not np.isnan(vol_sma_out) else float("nan")),
                legOutReward=float(leg_out_reward), legOutRR=float(leg_out_rr),
                legOutPassesRR=leg_out_passes_rr,
                legInBarIndex=int(p_in), legInHigh=float(in_high),
                legInLow=float(in_low), legOutClose=float(out_close),
                engulfRefPattern=(engulf_ref.patternType if engulf_ref is not None else ""),
                engulfRefDist=(float(engulf_ref.distVal) if engulf_ref is not None else float("nan")),
                engulfRefBar=(int(engulf_ref.legOutBarIndex) if engulf_ref is not None else None),
                engulfOK=engulf_ref is not None,
                rule1OK=rule1_ok, rule2OK=rule2_ok, rule3OK=rule3_ok, rule4OK=rule4_ok,
                validDemand=valid_demand, validSupply=valid_supply,
                legOutBarIndex=int(i), legOutComplete=bool(block_last_complete),
                blockCandles=int(block_k), blockHigh=float(block_high), blockLow=float(block_low),
                validFromBarIndex=int(valid_from),
                validFromTimestamp=(self.df.index[valid_from] if valid_from < self.n else None),
                envelopeOK=bool(env_ok), envelopeTarget=float(env_target),
                halfTF=self.half_tf_name, halfOK=bool(h_ok),
                halfCheckSkipped=bool(h_info.get("halfSkipped", False)),
                halfBars=int(h_info.get("halfBars", 0)),
                halfAlignedPct=float(h_info.get("halfAlignedPct", float("nan"))),
                halfMidBreakBar=h_info.get("halfMidBreakBar"),
                halfCrossBar=h_info.get("halfCrossBar"),
            )
            self.active_zones.append(zone)
            self.live_zones.append(zone)
            self.pattern_registry.append(zone)
            self.stats["zones_created"] += 1
            self.stats[f"zones_block_{block_k}c"] += 1

    def _update_states(self, i: int) -> None:
        if not self.live_zones:
            return
        low, high = self.l[i], self.h[i]
        for k in range(len(self.live_zones) - 1, -1, -1):
            zone = self.live_zones[k]
            if zone.validFromBarIndex > i:
                continue          # naya niyam (2): complete hone se pehle zone active nahi
            if zone.state == "Fresh":
                if zone.isDemand:
                    if low <= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break_before_test"
                    elif low <= zone.proxVal:
                        zone.state = "Tested"
                        zone.touchCount += 1
                        zone.isFresh = False
                        if zone.entryBarIndex is None:
                            zone.entryBarIndex = i
                            zone.entryTimestamp = self.df.index[i]
                            zone.entryPrice = zone.proxVal
                            zone.entryStatus = "ENTERED_FRESH"
                else:
                    if high >= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break_before_test"
                    elif high >= zone.proxVal:
                        zone.state = "Tested"
                        zone.touchCount += 1
                        zone.isFresh = False
                        if zone.entryBarIndex is None:
                            zone.entryBarIndex = i
                            zone.entryTimestamp = self.df.index[i]
                            zone.entryPrice = zone.proxVal
                            zone.entryStatus = "ENTERED_FRESH"
            elif zone.state == "Tested":
                if zone.isDemand:
                    if low <= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break"
                    elif low <= zone.proxVal:
                        zone.touchCount += 1
                else:
                    if high >= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break"
                    elif high >= zone.proxVal:
                        zone.touchCount += 1

            if zone.state == "Broken":
                zone.breakBarIndex = i
                zone.isFresh = False
                zone.zoneBox.set_bgcolor(("gray", 0.05))
                zone.zoneBox.set_border_color(("gray", 0.20))
                self.live_zones.pop(k)
            else:
                zone.zoneBox.set_right(i + 15)

    def run(self) -> List[Zone]:
        min_bar = max(self.atrPeriod, self.maxBaseCount + 3, 11)
        for i in range(self.n):
            if i >= min_bar and not np.isnan(self.atr[i]):
                self._scan_bar(i)
            self._update_states(i)
        return self.active_zones


def settings(accountCapital: Optional[float] = None, **overrides: Any) -> Dict[str, Any]:
    result = dict(PINE_DEFAULTS)
    if accountCapital is not None:
        overrides["accountCapital"] = accountCapital
    for key, value in overrides.items():
        if key in PINE_DEFAULTS:
            result[key] = value
    result["accountCapital"] = _positive_float(result["accountCapital"], "accountCapital")
    return result


def scan_zones(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None,
               accountCapital: Optional[float] = None, tf: Optional[str] = None,
               half_df: Optional[pd.DataFrame] = None, **overrides: Any) -> List[Zone]:
    """v2 scanner: pulse/trend nahi, lekin leg-out complete + envelope + half-TF niyam.

    tf diya jaye to half time-frame ka naam HALF_TF_MAP se apne aap chun liya jata hai.
    Naye v2 inputs seedhe keyword se bhi de sakte hain, jaise:
        scan_zones(df, tf="2H", half_df=h, envelopeRR=1.0, envelopeCheckStopSide=False)
    """
    incoming = dict(params or {})
    incoming.update(overrides)
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    config = settings(**incoming)
    half_name = half_timeframe_of(tf) if tf else ""
    engine = ZoneEngine(df, half_df=half_df, half_tf_name=half_name, **config)
    return engine.run()


def scan_validated_zones(df_zone: pd.DataFrame, half_df: Optional[pd.DataFrame] = None,
                         zone_tf: Optional[str] = None, df_base: Optional[pd.DataFrame] = None,
                         dtf: Optional[str] = None, **legacy: Any) -> List[Zone]:
    """v1 ka drop-in naam -- lekin ab pulse/trend arguments nahi, v2 niyam chalte hain.

    half_df na dein to df_base (barik data) se khud half frame banane ki koshish hoti hai.
    Purane pulse/trend kwargs (df_pulse, df_trend, pulse_rule, trend_rule, require_aligned)
    bhejne par saaf error milega -- unhe hata dein.
    """
    bad = [k for k in legacy if k in {"df_pulse", "df_trend", "pulse_rule", "pulse_tf",
                                      "trend_rule", "trend_tf", "require_aligned"}]
    if bad:
        raise TypeError("v2 me pulse/trend niyam hata diye gaye hain -- ye arguments na dein: "
                        + ", ".join(sorted(bad)))
    params = dict(legacy.pop("params", {}) or {})
    params.update(legacy)
    tf = zone_tf or dtf
    if half_df is None and df_base is not None and tf:
        half_df = build_half_dataframe(tf, df_base=df_base)
    return scan_zones(df_zone, params=params, tf=tf, half_df=half_df)


def leg_out_envelope_zones(zones: List[Zone]) -> List[Zone]:
    """Sirf wo zones jinka entry/SL/target leg-out (ya 3-candle block) ke andar tha."""
    return [z for z in zones if z.envelopeOK]


def half_confirmed_zones(zones: List[Zone]) -> List[Zone]:
    """Sirf wo zones jo half time-frame me mid-line se nahi toote."""
    return [z for z in zones if z.halfOK and not z.halfCheckSkipped]


def latest_active_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.state in ("Fresh", "Tested")]


def high_quality_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.isHQ]


def fresh_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.state == "Fresh" and zone.isFresh]


def tradable_zones(zones: List[Zone]) -> List[Zone]:
    result: List[Zone] = []
    for zone in zones:
        if zone.state not in ("Fresh", "Tested"):
            continue
        if not (zone.validDemand or zone.validSupply):
            continue
        if not zone.envelopeOK or not zone.halfOK:
            continue
        if zone.entryBarIndex is None and zone.state != "Fresh":
            continue
        result.append(zone)
    return result


def summarize_zones(zones: List[Zone]) -> pd.DataFrame:
    if not zones:
        return pd.DataFrame()
    rows = []
    for zone in zones:
        rows.append({
            "timestamp": zone.timestamp,
            "leg_out_bar": zone.legOutBarIndex,
            "block_candles": zone.blockCandles,
            "valid_from": zone.validFromTimestamp,
            "pattern": zone.patternType,
            "category": zone.zoneCategory,
            "side": "Demand" if zone.isDemand else "Supply",
            "state": zone.state,
            "proximal": zone.proxVal,
            "distal": zone.distVal,
            "sl": zone.slVal,
            "tp": zone.tpVal,
            "envelope_target": zone.envelopeTarget,
            "block_high": zone.blockHigh,
            "block_low": zone.blockLow,
            "risk_pct": zone.riskPct,
            "legOutRR": zone.legOutRR,
            "rr_ok": zone.legOutPassesRR,
            "engulf": zone.engulfOK,
            "engulf_ref": zone.engulfRefPattern,
            "rule1": zone.rule1OK, "rule2": zone.rule2OK,
            "rule3": zone.rule3OK, "rule4": zone.rule4OK,
            "score": zone.densityScore,
            "HQ": zone.isHQ,
            "half_tf": zone.halfTF,
            "half_ok": zone.halfOK,
            "half_bars": zone.halfBars,
            "half_aligned_pct": zone.halfAlignedPct,
            "half_mid_break_bar": zone.halfMidBreakBar,
            "entry_bar": zone.entryBarIndex,
            "entry_price": zone.entryPrice,
            "break_bar": zone.breakBarIndex,
        })
    return pd.DataFrame(rows)
