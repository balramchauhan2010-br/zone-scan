"""
zone_core.py  -  Pine Script "Zone MTF" indicator ka Python scanner version.
=================================================================================
*** PINE PARITY REVISION (v2) ***
Ye revision zone_core.py ko Pine Script "Zone MTF" ke saath match karata hai,
taaki jo zone Pine par active (Fresh/Tested) nahi hai wo scanner me bhi na aaye.

Sabse pehle: ASLI WAJAH samajhna zaroori hai
-------------------------------------------
Aapka INFY 2H DEMAND zone (Entry 992.70 / SL 979.32) Python scanner me isliye
nikal raha tha kyunki 2H frame ka leg-out candle **15:15 ki 15-minute candle**
thi. NSE me 03-Aug-2026 se F&O stocks (poore Nifty 50) me **continuous trading
15:15 par band** ho jaati hai; 15:15 ke baad Closing Auction Session (CAS) sirf
ek single print deta hai. Yahoo ise 15:15 ki alag candle bana deta hai, aur
purana frame builder us 15-minute candle ko poora **2H candle** maan leta tha.
TradingView ke 2H chart par aisi koi candle nahi hoti (uska session 09:15-15:15
hai) - isliye Pine me ye zone kabhi banta hi nahi, ya turant Broken ho jata hai.

Is revision me do tarah ke Pine-parity fixes hain:

  A. FRAME parity (naya): session ke bahar ki candles (jaise post-CAS 15:15
     auction bar) intraday frame se hata di jaati hain --
     `trim_out_of_session_bars()` (app me wired) aur `session_bars()`
     (raw 1h/15m data se Pine-jaisa frame banane ke liye).

  B. RULE parity (naya): state rules --
     (1) State ka faisla leg-out candle COMPLETE hone ke baad wali bars par hota
         hai (zone usi candle se banta hai) -- creation bar khud ko test nahi karta.
     (2) testedBasis = "proximal_or_mid" (DEFAULT) : Fresh zone "Tested" ho jaata
         hai jab price PROXIMAL line chhue YA leg-out mid level chhue (dono me se
         jo pehle aa jaye). Sirf-proximal ke liye preset TESTED_AT_PROXIMAL,
         sirf Pine-jaisa leg-out mid ke liye preset PINE_PARITY.
         (legOutMidLevel: testedLegOutRetracePct = 1.00 -> demand me leg-out
          candle ka low / supply me leg-out candle ka high.)
     (3) BROKEN SIRF DISTAL BREAK PAR -- useMaxTestedCountBreak = False (DEFAULT):
         zone tab tak Tested rehta hai jab tak price DISTAL line ko chhu kar tod
         na de. Touch count badhne se zone apne aap Broken NAHI hota.
         (Pine script ka auto-break variant chahiye to preset PINE_STRICT.)
     (4) useEodRange = False : Pine me EOD Range filter hai hi nahi, aur scanner ko
         bahut saare stocks me zones dhoondhne hain (EOD filter door ke zones ko
         gira deta hai) -- isliye ye scanner-only filter default OFF hai.

Purana (custom) behaviour ek switch se turant wapas milta hai:
    zone_core.scan_zones(df, params=dict(zone_core.LEGACY_SCANNER))
    ya ZoneEngine(df, **zone_core.settings(**zone_core.LEGACY_SCANNER))
Presets: DEFAULT_RULES (module defaults) | PINE_PARITY | PINE_STRICT |
         LEGACY_SCANNER | TESTED_AT_PROXIMAL.

Inputs sync: PINE_DEFAULTS ke core/inert/scanner-only inputs purane zone_core.py
jaise hi hain (naam aur default). Pine ke display-only inputs (MTF lines, Shadow,
Swing) sirf reference ke liye rakhe gaye hain - Pine me bhi ye display-only hain.

Baaki SAB kuch jaisa tha: leg-in/base/leg-out gates, imbalance/engulf check,
RBR/DBR/DBD/RBD classification, density score (minValidScore/hqScoreThreshold),
duplicate check (11 zones, 0.25 ATR), EOD range function, SL (distal +/- ATR
buffer), TP (targetRR), legOutMidLevel, legOutReward, zoneBox, state flow
Fresh/Tested/Broken aur entry tracking (ENTRY_FRESH) -- same.

Timestamp: naive aur timezone-aware (IST) DatetimeIndex dono support.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# NSE session constants (Pine / TradingView intraday bar convention)
# ---------------------------------------------------------------------------
SESSION_OPEN_MIN = 9 * 60 + 15          # 09:15 IST - session open
CONTINUOUS_END_MIN = 15 * 60 + 15       # 15:15 IST - F&O stocks: continuous trading khatam (CAS ke baad)
SESSION_END_MIN = 15 * 60 + 30          # 15:30 IST - purana (pre-CAS) session end
CAS_FROM = "2026-08-03"                 # NSE Closing Auction Session Phase-1 live

PINE_DEFAULTS: Dict[str, Any] = {
    # ---------------- original indicator inputs (same defaults) ----------------
    "accountCapital": 25000.0,          # "Account Capital"
    "riskPct": 0.5,                     # "Risk %"
    "targetRR": 5.0,                    # "Target RR"
    "slBufferAtr": 0.1,                 # "SL Buffer ATR"
    "atrPeriod": 14,                    # "ATR Period"
    "volSmaPeriod": 20,                 # "Volume SMA Period"
    "legOutTrMult": 1.2,                # "Leg-Out TR Multiplier"
    "legOutMinTrRatio": 1.0,            # "Leg-Out Min TR Ratio vs Leg-In"
    "hqLegOutTrMult": 2.0,              # "HQ Leg-Out TR Multiplier"
    "hqLegInAtrMult": 1.5,              # "HQ Leg-In ATR Multiplier"
    "maxBaseAtrMult": 1.0,              # "Max Base TR ATR Multiplier"
    "maxWickPct": 0.30,                 # "Max Wick %"
    "minBaseCountInput": 1,             # "Min Base Count"
    "maxBaseCountInput": 3,             # "Max Base Count"
    "legInMinAtrMult": 1.0,             # "Leg-In Min ATR Multiplier"
    "minClvPct": 0.60,                  # "Min CLV %"
    "legInToBaseSizeMult": 2.0,         # "Leg-In to Base Size Multiplier"
    "legInMinBodyPct": 0.60,            # "Leg-In Min Body %"
    "useImbalance": True,               # "Use Imbalance"
    "maxImbalanceMult": 1.0,            # "Max Imbalance vs Leg-In Mult"
    "relaxGapCapOvernight": True,       # "Relax Gap Cap on Overnight"
    "genuineGapBonus": 10,              # "Genuine Gap Score Bonus"
    "overnightGapBonus": 15,            # "Overnight Gap Score Bonus"
    "rejectOppositeCoverPct": 0.50,     # "Reject Opposite Cover %"
    "minValidScore": 40,                # "Min Valid Score"
    "hqScoreThreshold": 90,             # "HQ Score Threshold"
    "legOutBodyHeavyPct": 0.60,         # "Leg-Out Body Heavy Pressure %"
    "testedLegOutRetracePct": 1.00,     # "Tested Leg-Out Retrace %"  (mid level)
    "maxTestedCount": 1,                # "Max Tested Count"

    # ---------------- Pine parity inputs (inert, jaise pehle the) ---------------
    "legOutToLegInBodyMult": 1.0,       # "Leg-Out to Leg-In Body Mult"
    "baseBoringMaxBodyPct": 0.55,       # "Base Small-Body (Indecision) %"
    "scanAfterCandleComplete": True,    # "Scan After Candle Complete"
    "scanMonthlyOnce": True,            # "Scan Monthly Once"
    "scanWeeklyOnce": True,             # "Scan Weekly Once"
    "scanDailyOnce": True,              # "Scan Daily Once"
    "enableClosingWickCheck": True,     # "Use Closing-Side Wick Guard"
    "legInMinClosingWickPct": 0.1,      # "Leg-In Min Closing Wick %"
    "enableLegOutCoverCheck": True,     # "Use Leg-Out Coverage Guard"
    "legOutMaxCoverPct": 90.0,          # "Leg-Out Max Cover %"
    "enableHQBaseColourCheck": True,    # "Use Boring-Colour HQ Flag"
    "hqBaseColourProbabilityPct": 90.0, # "HQ Base Colour Probability %"
    "enableWhiteAreaCheck": True,       # "Use White Area Check"

    # ---------------- Pine display-only inputs (scanner se koi asar nahi) -------
    "showMTF": True,                    # "Show other-TF proximal lines"
    "filterDistantMTF": True,           # "Hide distant MTF lines (display only)"
    "mtfNearPct": 8.0,                  # "Show lines within % of last price"
    "showShadow": True,                 # "Shadow when prior zone behind / broken"
    "showFlags": True,                  # "Show BASE BREAK / SWING labels"
    "shadowAtr": 0.08,                  # "Shadow padding x ATR"
    "swingLeft": 3,                     # "Confirmed swing: bars on left"
    "swingRight": 3,                    # "Confirmed swing: bars on right"
    "maxStored": 220,                   # "Max chart zones"

    # ---------------- SCANNER-ONLY (Pine me nahi) -------------------------------
    "eodHighBufferPct": 10.0,           # "EOD High Buffer %"   (useEodRange=True par)
    "eodLowBufferPct": 10.0,            # "EOD Low Buffer %"    (useEodRange=True par)
    "useEodRange": False,               # Pine me EOD filter nahi + kai stocks ke zones chahiye (purana: True)
    "testedBasis": "proximal_or_mid",   # DEFAULT: Tested jab proximal YA legOutMid chhue
                                        # ("proximal" = sirf proximal | "legOutMid" = sirf Pine mid)
    "useMaxTestedCountBreak": False,    # DEFAULT OFF: Broken SIRF distal break par (touches se auto-break nahi)
    "sessionAwareFrames": True,         # PINE PARITY: session bahar ki candles (CAS 15:15) hataao
}

HARD_MAX_BASE_COUNT = 3

# ---------------------------------------------------------------------------
# Presets (params me **preset pass kar dein)
# ---------------------------------------------------------------------------
# DEFAULT_RULES -- module defaults ka mirror (jo bina kuch pass kiye chalta hai):
#   Tested = proximal YA leg-out mid | Broken = sirf distal break | EOD filter OFF.
DEFAULT_RULES: Dict[str, Any] = dict(
    useEodRange=False,
    testedBasis="proximal_or_mid",
    useMaxTestedCountBreak=False,
)
# Pine "Zone MTF" jaisa tested level (sirf leg-out mid), par Broken sirf distal par.
PINE_PARITY: Dict[str, Any] = dict(
    useEodRange=False,
    testedBasis="legOutMid",
    useMaxTestedCountBreak=False,
)
# Purana scanner: EOD filter ON + tested proximal par (+ distal break).
LEGACY_SCANNER: Dict[str, Any] = dict(
    useEodRange=True,
    testedBasis="proximal",
    useMaxTestedCountBreak=False,
)
# Sirf proximal par Tested (EOD filter OFF).
TESTED_AT_PROXIMAL: Dict[str, Any] = dict(
    useEodRange=False,
    testedBasis="proximal",
    useMaxTestedCountBreak=False,
)
# Reference only: Pine script ka poora variant (touches > maxTestedCount => Broken).
# User-approved rule "Broken sirf distal par" ke khilaaf hai, isliye default me NAHI.
PINE_STRICT: Dict[str, Any] = dict(
    useEodRange=False,
    testedBasis="legOutMid",
    useMaxTestedCountBreak=True,
)
RULE_PRESETS: Dict[str, Dict[str, Any]] = {
    "default_rules": dict(DEFAULT_RULES),
    "pine_parity": dict(PINE_PARITY),
    "legacy_scanner": dict(LEGACY_SCANNER),
    "tested_at_proximal": dict(TESTED_AT_PROXIMAL),
    "pine_strict": dict(PINE_STRICT),
    "pine_auto_break": dict(PINE_STRICT),   # purana naam (backward-compatible)
}


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
    # Original zone_core.py Zone fields -- same order (scanner.py compatibility).
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

    legOutReward: float = float("nan")
    legInBarIndex: Optional[int] = None
    legInHigh: float = float("nan")
    legInLow: float = float("nan")
    legOutClose: float = float("nan")
    isFresh: bool = True


def _positive_float(value: Any, name: str) -> float:
    try:
        r = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(r) or r <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return r


def get_eod_range(df: pd.DataFrame, idx: int, high_buffer_pct: float = 10.0,
                  low_buffer_pct: float = 10.0) -> Tuple[float, float]:
    try:
        d = df.index[idx].date()
        day = df[df.index.date == d]
        if day.empty:
            return float(df["low"].iloc[idx] * .9), float(df["high"].iloc[idx] * 1.1)
        return (float(day["low"].min() * (1 - low_buffer_pct / 100)),
                float(day["high"].max() * (1 + high_buffer_pct / 100)))
    except Exception:
        return float(df["low"].iloc[idx] * .9), float(df["high"].iloc[idx] * 1.1)


def check_white_area(df: pd.DataFrame, base_start_idx: int, base_end_idx: int,
                     leg_out_idx: int, curr_idx: int) -> bool:
    bh = float(df["high"].iloc[base_start_idx:base_end_idx + 1].max())
    bl = float(df["low"].iloc[base_start_idx:base_end_idx + 1].min())
    if leg_out_idx + 1 >= curr_idx:
        return True
    window = df.iloc[leg_out_idx + 1:curr_idx]
    return not bool(((window["low"] <= bh) & (window["high"] >= bl)).any())


def check_leg_out_coverage(df: pd.DataFrame, leg_out_idx: int, curr_idx: int,
                           max_cover_pct: float = 90.0) -> bool:
    hi, lo = float(df["high"].iloc[leg_out_idx]), float(df["low"].iloc[leg_out_idx])
    rng = hi - lo
    if rng <= 0 or leg_out_idx + 1 > curr_idx:
        return True
    window = df.iloc[leg_out_idx + 1:curr_idx + 1]
    overlap = (np.minimum(window["high"], hi) - np.maximum(window["low"], lo)).clip(lower=0)
    return not bool(((overlap / rng) > max_cover_pct / 100).any())


SCAN_TRACKER: Dict[str, datetime] = {}


def should_scan_now(tf: str, force: bool = False) -> bool:
    now = datetime.now()
    if force:
        return True
    days = {"Monthly": 30, "Weekly": 7, "Daily": 1}
    key = tf if tf in days else f"Intraday_{tf}"
    last = SCAN_TRACKER.get(key)
    mins = {"3M": 3, "5M": 5, "10M": 10, "15M": 15, "30M": 30, "75M": 75,
            "1H": 60, "2H": 120, "4H": 240, "6H": 360}.get(tf, 15)
    if last is None or (now - last).total_seconds() >= (days[tf] * 86400 if tf in days else mins * 60):
        SCAN_TRACKER[key] = now
        return True
    return False


# ---------------------------------------------------------------------------
# PINE PARITY: NSE session / frame helpers
# ---------------------------------------------------------------------------
TF_MINUTES: Dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "75m": 75,
    "1H": 60, "2H": 120, "3H": 180, "4H": 240, "6H": 360,
}


def tf_minutes(tf: str) -> int:
    return int(TF_MINUTES.get(str(tf).strip(), 0))


def _bar_end_minutes(idx: pd.DatetimeIndex,
                     session_end_min: int = SESSION_END_MIN,
                     cas_from: str = CAS_FROM) -> np.ndarray:
    """Har bar ke liye us din ka session-end (minutes since midnight).
    Post-CAS (>= cas_from) par F&O stocks ka continuous session 15:15 par khatam."""
    try:
        cas_date = _date.fromisoformat(str(cas_from))
        post = np.array([d >= cas_date for d in idx.date], dtype=bool)
    except Exception:
        post = np.zeros(len(idx), dtype=bool)
    return np.where(post, CONTINUOUS_END_MIN, int(session_end_min)).astype(int)


def trim_out_of_session_bars(frame: pd.DataFrame,
                             session_end_min: int = SESSION_END_MIN,
                             cas_from: str = CAS_FROM) -> pd.DataFrame:
    """Pine/TV parity: session ke bahar start hone wali candles hataata hai.

    Post-CAS (03-Aug-2026 se) F&O stocks me 15:15 ki CAS/auction candle kisi bhi
    intraday bar ka hissa nahi hoti (TradingView session 09:15-15:15 hai), isliye
    aisi candles frame se hata di jaati hain. Pre-CAS history me 15:15-15:30 ka
    normal trading tha, wo bani rehti hai.

    Yahi wajah thi ki INFY 2H ka ghost zone (Entry 992.70 / SL 979.32) scanner me
    aa raha tha -- us zone ka leg-out candle 15:15 ki 15-minute auction candle thi.
    """
    if frame is None or len(frame) == 0 or not isinstance(frame.index, pd.DatetimeIndex):
        return frame
    idx = frame.index
    mins = idx.hour * 60 + idx.minute
    ends = _bar_end_minutes(idx, session_end_min=session_end_min, cas_from=cas_from)
    keep = mins < ends
    if bool(keep.all()):
        return frame
    return frame.loc[keep]


def trim_frames(frames: Dict[str, pd.DataFrame],
                session_end_min: int = SESSION_END_MIN,
                cas_from: str = CAS_FROM) -> Dict[str, pd.DataFrame]:
    """trim_out_of_session_bars() ko {symbol: frame} dict par lagao (app ke liye)."""
    if not frames:
        return frames
    out: Dict[str, pd.DataFrame] = {}
    for sym, frame in frames.items():
        try:
            out[sym] = trim_out_of_session_bars(frame, session_end_min=session_end_min,
                                                cas_from=cas_from)
        except Exception:
            out[sym] = frame
    return out


def session_bars(df: pd.DataFrame, minutes: int,
                 session_open_min: int = SESSION_OPEN_MIN,
                 session_end_min: int = SESSION_END_MIN,
                 cas_from: str = CAS_FROM) -> pd.DataFrame:
    """Raw intraday data -> NSE session-anchored frame (09:15 anchor), Pine jaisa.

    Post-CAS par 15:15 ke baad ki candles hata di jaati hain, isliye 2H frame me
    3 candles aati hain (09:15, 11:15, 13:15) -- TradingView ke 2H jaisa hi.
    """
    if df is None or len(df) == 0:
        return df
    empty_cols = ["open", "high", "low", "close", "volume"]
    minutes = int(minutes)
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    idx = pd.DatetimeIndex(df.index)
    mod = (idx.hour * 60 + idx.minute) - int(session_open_min)
    bucket = np.where(mod < 0, -1, np.floor_divide(mod, minutes))
    start_min = int(session_open_min) + bucket * minutes
    ends = _bar_end_minutes(idx, session_end_min=session_end_min, cas_from=cas_from)
    keep = (bucket >= 0) & (start_min < ends)
    if not bool(np.any(keep)):
        return pd.DataFrame(columns=empty_cols)
    work = pd.DataFrame({
        "open": df["open"].to_numpy(float),
        "high": df["high"].to_numpy(float),
        "low": df["low"].to_numpy(float),
        "close": df["close"].to_numpy(float),
        "volume": (df["volume"].to_numpy(float) if "volume" in df.columns else 0.0),
        "__d__": pd.DatetimeIndex(idx).normalize(),
        "__s__": start_min,
        "__t__": idx,
    }, index=idx)
    work = work[keep]
    agg = work.groupby(["__d__", "__s__"], sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), start=("__t__", "first"),
    )
    out = pd.DataFrame({
        "open": agg["open"].to_numpy(float),
        "high": agg["high"].to_numpy(float),
        "low": agg["low"].to_numpy(float),
        "close": agg["close"].to_numpy(float),
        "volume": agg["volume"].to_numpy(float),
    }, index=pd.DatetimeIndex(agg["start"].to_numpy()))
    return out.sort_index()


class ZoneEngine:
    def __init__(self, df: pd.DataFrame, **kwargs: Any):
        self.df = df.copy()
        if "volume" not in self.df.columns:
            self.df["volume"] = 0.0
        self.df["volume"] = self.df["volume"].fillna(0.0)
        for key, default in PINE_DEFAULTS.items():
            setattr(self, key, kwargs.get(key, default))

        self.accountCapital = _positive_float(self.accountCapital, "accountCapital")
        # Original zone_core.py base-count behaviour.
        self.minBaseCount = max(1, min(self.minBaseCountInput, self.maxBaseCountInput))
        self.maxBaseCount = min(self.maxBaseCountInput, HARD_MAX_BASE_COUNT)
        # Tested trigger basis: "proximal" | "legoutmid" | "either" (default)
        _basis = str(self.testedBasis).strip().lower()
        if _basis in ("proximal", "prox"):
            self.tested_basis = "proximal"
        elif _basis in ("legoutmid", "legout", "mid", "leg_out_mid"):
            self.tested_basis = "legoutmid"
        else:  # "proximal_or_mid", "either", "both", default
            self.tested_basis = "either"

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
        self.time_ms = time_index.astype("datetime64[ns]").astype(np.int64) // 10**6
        self.active_zones: List[Zone] = []
        self.live_zones: List[Zone] = []
        self.pattern_registry: List[Zone] = []
        self._prepare()

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
                           np.abs(self.l[1:] - previous_close)),
            )
        self.atr = self._rma(true_range, self.atrPeriod)
        self.vol_sma = self.df["volume"].rolling(self.volSmaPeriod).mean().to_numpy()
        day_key = self.df.index.normalize()
        self.day_high = self.df["high"].groupby(day_key).transform("max").to_numpy()
        self.day_low = self.df["low"].groupby(day_key).transform("min").to_numpy()

    def _tr(self, p: int) -> float:
        pc = self.c[p - 1]
        return max(self.h[p] - self.l[p], abs(self.h[p] - pc), abs(self.l[p] - pc))

    def _bull(self, p: int) -> bool:
        return bool(self.c[p] > self.o[p])

    def _bear(self, p: int) -> bool:
        return bool(self.o[p] > self.c[p])

    def _wick_pct(self, p: int) -> float:
        rng = self.h[p] - self.l[p]
        if rng == 0:
            return 0.0
        w = (self.h[p] - max(self.o[p], self.c[p])) + (min(self.o[p], self.c[p]) - self.l[p])
        return w / rng

    def _body_pct(self, p: int) -> float:
        rng = self.h[p] - self.l[p]
        if rng == 0:
            return 0.0
        return abs(self.c[p] - self.o[p]) / rng

    def _overnight(self, i: int) -> bool:
        if i == 0:
            return False
        return bool(self.dow[i] != self.dow[i - 1] or (self.time_ms[i] - self.time_ms[i - 1]) > 86400000)

    def _tested_trigger(self, zone: Zone) -> float:
        """Wo level jise chhute hi zone Tested ho jaata hai.

        default ("either") = proximal YA leg-out mid, jo bhi pehle aa jaye:
            demand me dono me se upar wala level (low usse neeche jate hi),
            supply me dono me se neeche wala level (high usse upar jate hi).
        """
        if self.tested_basis == "proximal":
            return zone.proxVal
        if self.tested_basis == "legoutmid":
            return zone.legOutMidLevel
        if zone.isDemand:
            return max(zone.proxVal, zone.legOutMidLevel)
        return min(zone.proxVal, zone.legOutMidLevel)

    # ------------------------------------------------------------------
    # original candidate scan (same gates, same order, same scoring)
    # ------------------------------------------------------------------
    def _scan_bar(self, i: int) -> None:
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

            leg_in_tr = self._tr(p_in)
            in_low, in_high, in_close = self.l[p_in], self.h[p_in], self.c[p_in]
            in_vol = self.v[p_in]
            in_range = in_high - in_low
            in_bull, in_bear = self._bull(p_in), self._bear(p_in)
            if in_range == 0 or self._body_pct(p_in) < self.legInMinBodyPct:
                continue

            if (in_bull and self._bear(p_prev)) or (in_bear and self._bull(p_prev)):
                previous_body_high = max(self.o[p_prev], self.c[p_prev])
                previous_body_low = min(self.o[p_prev], self.c[p_prev])
                overlap = max(0.0, min(previous_body_high, in_high) - max(previous_body_low, in_low))
                if overlap / in_range >= self.rejectOppositeCoverPct:
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
                continue

            effective_multiplier = 1.5 if base_count == 1 else self.legInToBaseSizeMult
            if leg_in_tr < effective_multiplier * max_base_tr:
                continue
            if leg_in_tr < self.legInMinAtrMult * self.atr[p_in]:
                continue

            leg_out_tr = self._tr(p_out)
            out_high, out_low = self.h[p_out], self.l[p_out]
            out_close, out_open = self.c[p_out], self.o[p_out]
            out_vol = self.v[p_out]
            is_demand = self._bull(p_out)
            is_supply = self._bear(p_out)
            if not (is_demand or is_supply):
                continue

            explosive = leg_out_tr >= self.legOutTrMult * self.atr[p_out]
            wick_ok = self._wick_pct(p_out) <= self.maxWickPct
            tr_hierarchy_ok = (
                leg_out_tr >= self.legOutMinTrRatio * leg_in_tr
                and leg_in_tr > max_base_tr
            )
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
                    and max(out_open, out_close) >= max_base_high
                    and not has_gap):
                continue

            is_rbr = in_bull and bull_clv >= self.minClvPct and is_demand
            is_dbr = in_bear and bear_clv >= self.minClvPct and is_demand
            is_dbd = in_bear and bear_clv >= self.minClvPct and is_supply
            is_rbd = in_bull and bull_clv >= self.minClvPct and is_supply
            if not (is_rbr or is_dbr or is_dbd or is_rbd):
                continue
            if not (explosive and wick_ok and tr_hierarchy_ok and volume_ok and has_imbalance):
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

            opposite_base = any(
                (is_demand and self._bear(i - offset))
                or (is_supply and self._bull(i - offset))
                for offset in range(1, base_count + 1)
            )
            if opposite_base:
                score += 10
            score += 10
            if has_gap:
                score += self.genuineGapBonus
            if is_overnight and has_gap:
                score += self.overnightGapBonus
            if score < self.minValidScore:
                continue

            proximal = max_base_high if is_demand else min_base_low
            distal = min_base_low if is_demand else max_base_high
            if self.useEodRange:
                eod_high = self.day_high[i] * (1 + self.eodHighBufferPct / 100.0)
                eod_low = self.day_low[i] * (1 - self.eodLowBufferPct / 100.0)
                if not (eod_low <= proximal <= eod_high):
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
            pattern = "RBR" if is_rbr else ("DBR" if is_dbr else ("DBD" if is_dbd else "RBD"))
            category = "Continuation" if (is_rbr or is_dbd) else "Reversal"

            found = True
            duplicate = False
            checked = 0
            for existing in reversed(self.live_zones):
                if existing.isDemand == is_demand and abs(existing.proxVal - proximal) < atr_now * 0.25:
                    duplicate = True
                    break
                checked += 1
                if checked >= 11:
                    break
            if duplicate:
                continue

            border = "green" if is_demand else "red"
            fill = ("green", 0.15) if is_demand else ("red", 0.15)
            vol_sma_in, vol_sma_out = self.vol_sma[p_in], self.vol_sma[p_out]
            zone = Zone(
                proxVal=proximal,
                distVal=distal,
                slVal=sl,
                tpVal=tp,
                isDemand=is_demand,
                isHQ=bool(score >= self.hqScoreThreshold),
                densityScore=score,
                patternType=pattern,
                zoneCategory=category,
                state="Fresh",
                touchCount=0,
                startBarIndex=i - base_count,
                createdBarIndex=i,
                baseCount=base_count,
                legOutHigh=out_high,
                legOutLow=out_low,
                legOutMidLevel=mid,
                isOvernight=is_overnight,
                legInTR=leg_in_tr,
                legOutTR=leg_out_tr,
                zoneBox=Box(i - base_count - 1, proximal, i + 15, distal, border, fill),
                timestamp=self.df.index[i],
                riskPct=risk / proximal * 100.0 if proximal else float("nan"),
                score10=round(score / 10.0, 1),
                hasGenuineGap=has_gap,
                gapToLegIn=gap_size,
                legInVolX=(in_vol / vol_sma_in if vol_sma_in and not np.isnan(vol_sma_in) else float("nan")),
                legOutVolX=(out_vol / vol_sma_out if vol_sma_out and not np.isnan(vol_sma_out) else float("nan")),
                legOutReward=float(leg_out_reward),
                legInBarIndex=int(p_in),
                legInHigh=float(in_high),
                legInLow=float(in_low),
                legOutClose=float(out_close),
            )
            self.active_zones.append(zone)
            self.live_zones.append(zone)
            self.pattern_registry.append(zone)

    # ------------------------------------------------------------------
    # STATE TRACKING
    #   Fresh --(tested trigger touch)--> Tested
    #        tested trigger = proximal YA leg-out mid, jo pehle aaye (DEFAULT),
    #        ya sirf ek (testedBasis preset se).
    #   Fresh ya Tested --(distal line touch/break)--> Broken   <-- Broken SIRF yahan
    #   useMaxTestedCountBreak=True hone par hi Tested zone touches se auto-Broken
    #   hota hai; DEFAULT False hai, isliye zone tab tak active rehta hai jab tak
    #   price distal line ko chhu kar tod na de.
    # ------------------------------------------------------------------
    def _update_states(self, i: int) -> None:
        if not self.live_zones:
            return
        low, high = self.l[i], self.h[i]
        for k in range(len(self.live_zones) - 1, -1, -1):
            zone = self.live_zones[k]
            # Zone leg-out candle complete hone ke BAAD se hi test/break hota hai
            # (aapka rule: "zone sirf leg-out candle complete hone par valid").
            # Creation bar (leg-out khud) apne hi range se zone ko Tested/Broken
            # nahi karta -- warna har naya zone usi candle par Tested dikhta.
            if zone.createdBarIndex == i:
                zone.zoneBox.set_right(i + 15)
                continue
            tested_level = self._tested_trigger(zone)

            if zone.state == "Fresh":
                if zone.isDemand:
                    if low <= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break_before_test"
                    elif low <= tested_level:
                        zone.state = "Tested"
                        zone.touchCount += 1
                        zone.isFresh = False
                else:
                    if high >= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break_before_test"
                    elif high >= tested_level:
                        zone.state = "Tested"
                        zone.touchCount += 1
                        zone.isFresh = False

            elif zone.state == "Tested":
                if zone.isDemand:
                    if low <= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break"
                    elif low <= tested_level:
                        zone.touchCount += 1
                else:
                    if high >= zone.distVal:
                        zone.state = "Broken"
                        zone.breakReason = "distal_break"
                    elif high >= tested_level:
                        zone.touchCount += 1

            # DEFAULT OFF: zone tab tak active rehta hai jab tak price distal
            # line ko chhu kar tod na de. (Auto-break sirf tab jab param True ho.)
            if (self.useMaxTestedCountBreak and zone.state == "Tested"
                    and zone.touchCount > self.maxTestedCount):
                zone.state = "Broken"
                zone.breakReason = "max_tested_count"

            if zone.state == "Broken":
                zone.breakBarIndex = i
                zone.isFresh = False
                zone.zoneBox.set_bgcolor(("gray", 0.05))
                zone.zoneBox.set_border_color(("gray", 0.20))
                self.live_zones.pop(k)
            else:
                # entry tracking (scanner-only): ENTRY line (proximal) chhute hi mark
                if zone.entryBarIndex is None:
                    touched_prox = (low <= zone.proxVal) if zone.isDemand else (high >= zone.proxVal)
                    if touched_prox:
                        zone.entryBarIndex = i
                        zone.entryTimestamp = self.df.index[i]
                        zone.entryPrice = zone.proxVal
                        zone.entryStatus = "ENTERED_FRESH"
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


def scan_zones(
    df: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
    accountCapital: Optional[float] = None,
    tf: Optional[str] = None,
) -> List[Zone]:
    incoming = dict(params or {})
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    config = settings(**incoming)
    return ZoneEngine(df, **config).run()


def latest_active_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.state in ("Fresh", "Tested")]


def high_quality_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.isHQ]


def fresh_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.state == "Fresh" and zone.isFresh]


def summarize_zones(zones: List[Zone]) -> pd.DataFrame:
    if not zones:
        return pd.DataFrame()
    rows = []
    for zone in zones:
        rows.append({
            "timestamp": zone.timestamp,
            "pattern": zone.patternType,
            "category": zone.zoneCategory,
            "side": "Demand" if zone.isDemand else "Supply",
            "state": zone.state,
            "touches": zone.touchCount,
            "proximal": zone.proxVal,
            "distal": zone.distVal,
            "sl": zone.slVal,
            "tp": zone.tpVal,
            "risk_pct": zone.riskPct,
            "legOutRR": zone.legOutReward / abs(zone.proxVal - zone.slVal) if zone.proxVal != zone.slVal else float("nan"),
            "score": zone.densityScore,
            "HQ": zone.isHQ,
            "entry_bar": zone.entryBarIndex,
            "entry_price": zone.entryPrice,
            "break_reason": zone.breakReason,
            "break_bar": zone.breakBarIndex,
        })
    return pd.DataFrame(rows)
