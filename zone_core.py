from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# Configuration
#   PINE_DEFAULTS me scoring parameters (hqLegOutTrMult, hqLegInAtrMult,
#   genuineGapBonus, overnightGapBonus, minValidScore, hqScoreThreshold,
#   legOutBodyHeavyPct) wapas aa gaye hain - config me available hain, lekin
#   scoring jaan-boojh kar DISABLED hai: densityScore = 0, score10 = 0.0.
#   + New EOD Range Option
#   + New Rules: (2) Leg-out Coverage Guard  (3) Boring-Colour High-Quality
#                Zone Flag  (4) White-Area Check
#   (Rule 1 - Leg-in Closing-Side Small Wick Guard: REMOVED, Pine jaisa)
# -----------------------------------------------------------------------------
# CHANGES (is version me):
#   (a) legInMinBodyPct: 0.55 -> 0.60 (Pine default par wapas)
#   (b) legOutTrMult gate: legOutTR >= mult * ATR  (Pine ka '>=' wapas, '>' nahi)
#   (c) Scoring parameters config me wapas (values set, scoring nahi hoti)
#   (d) BASE_BORING_MAX_BODY_PCT ka GATING hata diya gaya. Uski value ab
#       settings() se badalne layak "baseBoringMaxBodyPct" key hai, aur use
#       sirf DISPLAY-ONLY Doji/Indecision highlight tag ke liye hota hai
#       (core scan logic me koi filter nahi).
#   (e) Leg-out "full-range engulf" REJECT rule REMOVED (Pine me ye rule hai nahi)
#   (f) Volume rule: legOutVol > legInVal. JAB data me volume column na ho
#       (ya leg-out ka volume 0/NaN ho) to rule SKIP ho jaata hai -
#       leg_out_volume_missing = not np.isfinite(leg_out_vol) or leg_out_vol <= 0
#       passes_volume = leg_out_volume_missing or leg_out_vol > leg_in_vol
#       Isse volume-less CSV par bhi zones scan hote hain (Pine me volume
#       hamesha hota hai, wahan ye rule hamesha lagta hi hai). Volume data
#       maujood hone par rule bilkul strict chalta hai, koi fark nahi padta.
#   (g) RULE 1 - Leg-in Closing-Side "Small Wick" Guard POORI TARAH HATAYA
#       gaya: config keys (enableClosingWickCheck, legInMinClosingWickPct),
#       scan ka check block, aur _closing_side_wick_price() helper - teeno.
#       Ye rule Pine script me hai hi nahi, aur ye leg-in candle ki baaki
#       sharte (body% >= legInMinBodyPct, CLV >= minClvPct, TR hierarchy)
#       ke saath directly contradict karta tha - perfect impulse leg-in
#       (jo apne high/low par close karta hai) hamesha reject ho jata tha.
#       Isliye zaroorat padne par almost koi zone hi nahi banta tha.
#   Baaki koi logic/rule/state-machine/field nahi badla gaya.
# -----------------------------------------------------------------------------

PINE_DEFAULTS: Dict[str, Any] = {
    "accountCapital": 25000.0,
    "riskPct": 0.5,
    "targetRR": 5.0,
    "slBufferAtr": 0.1,
    "atrPeriod": 14,
    "volSmaPeriod": 20,
    "legOutTrMult": 1.2,
    "legOutMinTrRatio": 1.0,
    # --- Scoring parameters (present for parity; scoring DISABLED, value = 0) ---
    "hqLegOutTrMult": 2.0,
    "hqLegInAtrMult": 1.5,
    "genuineGapBonus": 10,
    "overnightGapBonus": 15,
    "minValidScore": 40,
    "hqScoreThreshold": 90,
    "legOutBodyHeavyPct": 0.60,
    # ------------------------------------------------------------------------
    "maxBaseAtrMult": 1.0,
    "maxWickPct": 0.30,
    "minBaseCountInput": 1,
    "maxBaseCountInput": 3,
    "legInMinAtrMult": 1.0,
    "minClvPct": 0.60,
    "legInToBaseSizeMult": 2.0,
    "legOutToLegInBodyMult": 1.0,
    "legInMinBodyPct": 0.60,
    # baseBoringMaxBodyPct: pehle hard-coded BASE_BORING_MAX_BODY_PCT tha.
    # Ab settings() se changeable hai - par sirf Doji/Indecision HIGHLIGHT
    # tag ke liye (koi filter/condition nahi).
    "baseBoringMaxBodyPct": 0.55,
    "useImbalance": True,
    "maxImbalanceMult": 1.0,
    "relaxGapCapOvernight": True,
    "rejectOppositeCoverPct": 0.50,
    "testedLegOutRetracePct": 1.00,
    "maxTestedCount": 1,
    # NEW - EOD Range Scan - Day Candle Close High+10% Low-10% Option
    "eodHighBufferPct": 10.0,  # Changeable - High Price +10% default
    "eodLowBufferPct": 10.0,   # Changeable - Low Price -10% default
    "scanAfterCandleComplete": True,  # Zone scan candle complete होने के बाद ही
    "scanMonthlyOnce": True,   # Monthly एक बार
    "scanWeeklyOnce": True,    # Weekly एक बार
    "scanDailyOnce": True,     # Daily एक बार

    # ------------------------------------------------------------------
    # NEW RULE 2 - Leg-out "Coverage" Guard
    # Zone बनने के बाद, Leg-out के बाद आने वाली किसी भी single candle का range
    # अगर Leg-out के range को इतने % (default 90%) से ज़्यादा cover (overlap)
    # कर दे, तो zone को Fresh रहते हुए ही Broken/Invalid मान लिया जाता है।
    # ------------------------------------------------------------------
    "enableLegOutCoverCheck": True,
    "legOutMaxCoverPct": 90.0,       # % overlap threshold (changeable)

    # ------------------------------------------------------------------
    # NEW RULE 3 - Boring-Colour High-Quality (HQ) Zone Flag
    # Demand Zone में सारी Base/Boring candles RED (bearish) हों, या
    # Supply Zone में सारी Base/Boring candles GREEN (bullish) हों, तो यह
    # High-Probability (~90%) setup माना जाता है और isHQ / baseColourOK
    # flag के ज़रिए highlight होता है। (सिर्फ़ flag - कोई score/filtering नहीं)
    # ------------------------------------------------------------------
    "enableHQBaseColourCheck": True,
    "hqBaseColourProbabilityPct": 90.0,  # display-only probability tag (changeable)

    # ------------------------------------------------------------------
    # NEW RULE 4 - White Area Validation (Freshness Check)
    # जब zone पहली बार Fresh -> Tested transition करती है, उसी समय यह चेक
    # किया जाता है कि Leg-out के बाद से Retest candle तक का area पूरी तरह
    # साफ़ (कोई candle base range को touch न करे) था या नहीं। Result सिर्फ़
    # zone.whiteAreaOK field में tag/report होता है - Tested state पर कोई
    # असर नहीं पड़ता (fail होने पर भी zone Tested ही रहेगी, बस flag False रहेगा)।
    # ------------------------------------------------------------------
    "enableWhiteAreaCheck": True,
}

# -----------------------------------------------------------------------------
# Data objects
# -----------------------------------------------------------------------------
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
    def set_bgcolor(self, bgcolor: object) -> None:
        self.bgcolor = bgcolor
    def set_border_color(self, border_color: object) -> None:
        self.border_color = border_color

@dataclass
class Zone:
    proxVal: float
    distVal: float
    slVal: float
    tpVal: float
    isDemand: bool
    densityScore: int
    isHQ: bool
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
    baseColourOK: bool = False
    legInVolX: float = float("nan")
    legOutVolX: float = float("nan")
    retestVolX: float = float("nan")
    entryStatus: str = ""
    entryPrice: float = 0.0
    gapToLegIn: float = 0.0
    # NEW fields (Rules 1-4)
    hqProbabilityPct: float = float("nan")   # Rule 3 - display-only probability tag
    hqReason: str = ""                        # Rule 3 - why marked HQ
    whiteAreaOK: Optional[bool] = None        # Rule 4 - freshness/white-area tag
    breakReason: str = ""                     # Why zone was marked Broken (e.g. Rule 2)
    entryBarIndex: Optional[int] = None       # Bar index of first Fresh->Tested entry trigger
    entryTimestamp: object = None             # Timestamp of that same bar (for backtest use)
    # DISPLAY-ONLY tags (no filtering) - small-body / Doji / Indecision base candles
    baseIndecision: bool = False              # kam-se-kam 1 base candle ka body small (indecision)
    baseDojiCount: int = 0                    # kitni base candles exactly Doji (open == close)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _positive_float(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return result

# EOD Range Calculation - Day Candle Close High+10% Low-10%
def get_eod_range(df: pd.DataFrame, idx: int, high_buffer_pct: float = 10.0, low_buffer_pct: float = 10.0) -> tuple[float, float]:
    """
    Day Candle Close (EOD) का High Price+10% और Low Price -10% Range
    Changeable option: high_buffer_pct, low_buffer_pct कम ज्यादा कर सकते हैं
    """
    try:
        # Get date for current index
        current_date = df.index[idx].date()
        # Get all bars for that date
        day_df = df[df.index.date == current_date]
        if day_df.empty:
            return float(df['low'].iloc[idx] * 0.9), float(df['high'].iloc[idx] * 1.1)
        
        day_high = day_df['high'].max()
        day_low = day_df['low'].min()
        
        # High +10%, Low -10% with changeable option
        range_high = day_high * (1 + high_buffer_pct / 100.0)
        range_low = day_low * (1 - low_buffer_pct / 100.0)
        
        return float(range_low), float(range_high)
    except:
        # Fallback
        return float(df['low'].iloc[idx] * 0.9), float(df['high'].iloc[idx] * 1.1)

# -----------------------------------------------------------------------------
# NEW RULE 4 - White Area Validation Logic (as supplied)
# -----------------------------------------------------------------------------
def check_white_area(
    df: pd.DataFrame,
    base_start_idx: int,
    base_end_idx: int,
    leg_out_idx: int,
    curr_idx: int,
) -> bool:
    """Rule No. 4: White Area Validation Logic

    Validates that the area in front of the Boring/Base Candle(s) is
    absolutely clear with no body or wick of any intervening candle
    touching the base range (Leg-out के बाद से Retest candle से ठीक पहले तक)।
    """
    # 1. Base / Boring Candle(s) की उच्चतम और निम्नतम रेंज
    base_high = float(df['high'].iloc[base_start_idx: base_end_idx + 1].max())
    base_low = float(df['low'].iloc[base_start_idx: base_end_idx + 1].min())

    # 2. Leg-out के बाद से लेकर रीटेस्ट कैंडल से ठीक पहले तक की रेंज तय करें
    scan_start = leg_out_idx + 1
    scan_end = curr_idx

    # यदि Leg-out के तुरंत बाद वाली कैंडल ही रीटेस्ट कैंडल है, तो White Area साफ़ है
    if scan_start >= scan_end:
        return True

    # 3. बीच की कैंडल्स की High और Low सीरीज़ निकालें
    window_highs = df['high'].iloc[scan_start:scan_end]
    window_lows = df['low'].iloc[scan_start:scan_end]

    # 4. Overlap Check: क्या किसी कैंडल ने बेस एरिया को टच किया है?
    has_overlap = (window_lows <= base_high) & (window_highs >= base_low)

    if has_overlap.any():
        # यदि किसी भी कैंडल की बॉडी या विक सामने आ गई है -> White Area Failed
        return False

    # क्षेत्र पूरी तरह साफ़ (Fresh & Clean Area) है
    return True

# -----------------------------------------------------------------------------
# NEW RULE 2 - Leg-out Coverage Validation Logic (standalone / testable)
# -----------------------------------------------------------------------------
def check_leg_out_coverage(
    df: pd.DataFrame,
    leg_out_idx: int,
    curr_idx: int,
    max_cover_pct: float = 90.0,
) -> bool:
    """Rule No. 2: Leg-out Coverage Validation

    Leg-out candle को उसके बाद आने वाली किसी भी single candle द्वारा
    `max_cover_pct` % (default 90%) से अधिक cover (overlap) नहीं होना चाहिए।
    पहली ऐसी candle मिलते ही zone invalid माना जाता है (return False)।

    (ZoneEngine के अंदर performance के लिए इसी logic का एक incremental/
    bar-by-bar equivalent इस्तेमाल होता है - यह function standalone
    verification/testing के लिए दिया गया है।)
    """
    leg_out_high = float(df['high'].iloc[leg_out_idx])
    leg_out_low = float(df['low'].iloc[leg_out_idx])
    leg_out_range = leg_out_high - leg_out_low
    if leg_out_range <= 0:
        return True

    scan_start = leg_out_idx + 1
    scan_end = curr_idx + 1  # inclusive of curr_idx bar
    if scan_start >= scan_end:
        return True

    window_highs = df['high'].iloc[scan_start:scan_end]
    window_lows = df['low'].iloc[scan_start:scan_end]

    overlap = (np.minimum(window_highs, leg_out_high) - np.maximum(window_lows, leg_out_low)).clip(lower=0.0)
    cover_ratio = overlap / leg_out_range

    if (cover_ratio > (max_cover_pct / 100.0)).any():
        return False
    return True

# Scan Scheduling - Avoid Overload
SCAN_TRACKER: Dict[str, datetime] = {}

def should_scan_now(tf: str, force: bool = False) -> bool:
    """
    Zone Scan Scheduling to avoid overload:
    - Monthly, Weekly, Daily: एक बार करे
    - 6,4,2,1 hour, 75,30,15,10,5,3 min: Candle close होने के बाद करे
    """
    now = datetime.now()
    
    if force:
        return True
    
    # Monthly, Weekly, Daily - Once per period
    if tf == "Monthly":
        last = SCAN_TRACKER.get("Monthly")
        if last is None or (now - last).days >= 30:
            SCAN_TRACKER["Monthly"] = now
            return True
        return False
    elif tf == "Weekly":
        last = SCAN_TRACKER.get("Weekly")
        if last is None or (now - last).days >= 7:
            SCAN_TRACKER["Weekly"] = now
            return True
        return False
    elif tf == "Daily":
        last = SCAN_TRACKER.get("Daily")
        if last is None or (now - last).days >= 1:
            SCAN_TRACKER["Daily"] = now
            return True
        return False
    else:
        # Intraday: Scan after candle close - Always allow but with small delay check
        # For 3,5,10,15,30,75 min, 1,2,4,6H - scan after close
        last_key = f"Intraday_{tf}"
        last = SCAN_TRACKER.get(last_key)
        # Minimum interval based on TF to avoid overload
        min_interval_map = {
            "3M": 3, "5M": 5, "10M": 10, "15M": 15, "30M": 30, "75M": 75,
            "1H": 60, "2H": 120, "4H": 240, "6H": 360
        }
        min_minutes = min_interval_map.get(tf, 15)
        if last is None or (now - last).total_seconds() >= min_minutes * 60:
            SCAN_TRACKER[last_key] = now
            return True
        return False

# -----------------------------------------------------------------------------
# Zone engine - EOD Range + Candle Complete + New Rules 1-4
#              + Scoring params (scoring disabled, value = 0)
# -----------------------------------------------------------------------------
class ZoneEngine:
    def __init__(self, df: pd.DataFrame, **kwargs: Any):
        self.df = df.copy()
        if "volume" not in self.df.columns:
            self.df["volume"] = 0.0
        self.df["volume"] = self.df["volume"].fillna(0.0)
        for key, default in PINE_DEFAULTS.items():
            setattr(self, key, kwargs.get(key, default))
        self.accountCapital = _positive_float(self.accountCapital, "accountCapital")
        self.riskPct = float(self.riskPct)
        if not np.isfinite(self.riskPct) or self.riskPct < 0:
            raise ValueError("riskPct must be a finite non-negative number")
        hard_max_base_count = 3
        self.minBaseCount = max(1, min(self.minBaseCountInput, self.maxBaseCountInput))
        self.maxBaseCount = min(self.maxBaseCountInput, hard_max_base_count)
        self.open = self.df["open"].to_numpy(dtype=float)
        self.high = self.df["high"].to_numpy(dtype=float)
        self.low = self.df["low"].to_numpy(dtype=float)
        self.close = self.df["close"].to_numpy(dtype=float)
        self.volume = self.df["volume"].to_numpy(dtype=float)
        self.n = len(self.df)
        self.dayofweek = self.df.index.dayofweek.to_numpy()
        self.time_ms = self.df.index.astype(np.int64) // 10**6
        self.active_zones: List[Zone] = []
        self.live_zones: List[Zone] = []
        self._prepare_indicators()

    def _rma(self, series: np.ndarray, length: int) -> np.ndarray:
        n = len(series)
        result = np.full(n, np.nan)
        if n < length:
            return result
        result[length - 1] = np.mean(series[:length])
        for i in range(length, n):
            result[i] = (series[i] - result[i - 1]) / length + result[i - 1]
        return result

    def _prepare_indicators(self) -> None:
        if self.n > 0:
            previous_close = np.empty(self.n)
            previous_close[0] = self.close[0]
            previous_close[1:] = self.close[:-1]
            tr = np.maximum(self.high - self.low, np.maximum(np.abs(self.high - previous_close), np.abs(self.low - previous_close)))
            tr[0] = self.high[0] - self.low[0]
            self.current_tr = tr
        else:
            self.current_tr = np.empty(0)
        self.atr_val = self._rma(self.current_tr, self.atrPeriod)
        self.vol_sma = self.df["volume"].rolling(self.volSmaPeriod).mean().to_numpy()

        # ------------------------------------------------------------
        # PERFORMANCE FIX (behaviour unchanged): the original get_eod_range()
        # recomputed df.index.date (slow, converts the WHOLE index to python
        # date objects) and re-filtered the WHOLE dataframe on EVERY bar -
        # that is O(n) work repeated n times = O(n^2), which is what made
        # large-history scans (e.g. 1H over many months) extremely slow.
        # Precomputing the per-day High/Low ONCE (vectorized, O(n) total)
        # gives mathematically IDENTICAL results (same calendar-day grouping,
        # same max(high)/min(low)) - just computed once instead of per-bar.
        # ------------------------------------------------------------
        if self.n > 0:
            day_key = self.df.index.normalize()  # same calendar-day grouping as .date(), but vectorized/fast
            self.day_high = self.df["high"].groupby(day_key).transform("max").to_numpy()
            self.day_low = self.df["low"].groupby(day_key).transform("min").to_numpy()
        else:
            self.day_high = np.empty(0)
            self.day_low = np.empty(0)

    def _tr(self, i: int, idx: int) -> float:
        pos = i - idx
        return float(self.current_tr[pos]) if 0 <= pos < self.n else float("nan")

    def _is_bull(self, i: int, idx: int) -> bool:
        pos = i - idx
        return bool(self.close[pos] > self.open[pos])

    def _is_bear(self, i: int, idx: int) -> bool:
        pos = i - idx
        return bool(self.open[pos] > self.close[pos])

    def _body_high_low(self, i: int, idx: int) -> tuple[float, float]:
        pos = i - idx
        return max(self.open[pos], self.close[pos]), min(self.open[pos], self.close[pos])

    def _wick_pct(self, i: int, idx: int) -> float:
        pos = i - idx
        candle_range = self.high[pos] - self.low[pos]
        if candle_range == 0:
            return 0.0
        return (self.high[pos] - max(self.open[pos], self.close[pos]) + min(self.open[pos], self.close[pos]) - self.low[pos]) / candle_range

    def _body_pct(self, i: int, idx: int) -> float:
        pos = i - idx
        candle_range = self.high[pos] - self.low[pos]
        if candle_range == 0:
            return 0.0
        return abs(self.close[pos] - self.open[pos]) / candle_range

    def _is_overnight_gap(self, i: int) -> bool:
        if i == 0:
            return False
        return bool(self.dayofweek[i] != self.dayofweek[i - 1] or (self.time_ms[i] - self.time_ms[i - 1]) > 86400000)

    def _scan_bar(self, i: int) -> None:
        # NEW: EOD Range Check - Day Candle Close High+10% Low-10%
        # Changeable option: eodHighBufferPct, eodLowBufferPct
        # (uses the precomputed self.day_high/self.day_low - see _prepare_indicators
        #  perf-fix note; numerically identical to calling get_eod_range() per-bar)
        try:
            d_high = self.day_high[i]
            d_low = self.day_low[i]
            eod_high = d_high * (1 + self.eodHighBufferPct / 100.0)
            eod_low = d_low * (1 - self.eodLowBufferPct / 100.0)
        except Exception:
            eod_low, eod_high = -1e9, 1e9

        zone_found_on_this_bar = False
        for b_count in range(self.minBaseCount, self.maxBaseCount + 1):
            if zone_found_on_this_bar:
                break
            leg_out_idx = 0
            leg_in_idx = b_count + 1
            prev_idx = b_count + 2
            pos_leg_in = i - leg_in_idx
            if pos_leg_in < 0 or np.isnan(self.atr_val[pos_leg_in]):
                continue
            leg_in_tr = self._tr(i, leg_in_idx)
            leg_in_low = self.low[pos_leg_in]
            leg_in_high = self.high[pos_leg_in]
            leg_in_close = self.close[pos_leg_in]
            leg_in_vol = self.volume[pos_leg_in]
            leg_in_range = leg_in_high - leg_in_low
            leg_in_is_bull = self._is_bull(i, leg_in_idx)
            leg_in_is_bear = self._is_bear(i, leg_in_idx)
            if leg_in_range == 0 or self._body_pct(i, leg_in_idx) < self.legInMinBodyPct:
                continue

            # ------------------------------------------------------------
            # NEW RULE 1 (Leg-in Closing-Side Small Wick Guard): REMOVED.
            # Ye rule Pine script me hai hi nahi aur ye leg-in candle ki
            # baaki sharte (body% >= min, CLV >= minClvPct, TR hierarchy)
            # ke saath directly contradict karta tha. Ab leg-in ke liye
            # koi closing-side wick ki koi shart nahi hai.
            # ------------------------------------------------------------
            pos_prev = i - prev_idx
            if pos_prev < 0:
                continue
            if (leg_in_is_bull and self._is_bear(i, prev_idx)) or (leg_in_is_bear and self._is_bull(i, prev_idx)):
                prev_body_high, prev_body_low = self._body_high_low(i, prev_idx)
                overlap = max(0.0, min(prev_body_high, leg_in_high) - max(prev_body_low, leg_in_low))
                if overlap / leg_in_range >= self.rejectOppositeCoverPct:
                    continue
            bull_clv = (leg_in_close - leg_in_low) / leg_in_range
            bear_clv = (leg_in_high - leg_in_close) / leg_in_range
            all_base_valid = True
            max_base_tr = 0.0
            max_base_body = 0.0
            max_base_high = -1.0
            min_base_low = 1_000_000_000.0
            base_indecision_count = 0  # DISPLAY-ONLY (was: all_base_boring gate)
            base_doji_count = 0        # DISPLAY-ONLY tag
            base_colors: List[str] = []  # NEW RULE 3 tracking
            for b in range(1, b_count + 1):
                pos_b = i - b
                if pos_b < 0 or np.isnan(self.atr_val[pos_b]):
                    all_base_valid = False
                    break
                base_tr = self._tr(i, b)
                if base_tr > self.maxBaseAtrMult * self.atr_val[pos_b]:
                    all_base_valid = False
                    break
                base_body_size = abs(self.close[pos_b] - self.open[pos_b])
                # Small body = Doji / Indecision candle. Ab koi FILTER nahi -
                # sirf highlight tag ke liye count hota hai.
                base_body_pct = base_body_size / base_tr if base_tr > 0 else 0.0
                if base_body_pct <= self.baseBoringMaxBodyPct:
                    base_indecision_count += 1
                if base_body_size == 0:
                    base_doji_count += 1
                max_base_tr = max(max_base_tr, base_tr)
                max_base_body = max(max_base_body, base_body_size)
                max_base_high = max(max_base_high, self.high[pos_b])
                min_base_low = min(min_base_low, self.low[pos_b])
                # NEW RULE 3: track this base candle's colour
                if self.close[pos_b] > self.open[pos_b]:
                    base_colors.append("bull")
                elif self.close[pos_b] < self.open[pos_b]:
                    base_colors.append("bear")
                else:
                    base_colors.append("doji")
            if not all_base_valid or max_base_tr == 0:
                continue
            effective_base_size_mult = 1.5 if b_count == 1 else self.legInToBaseSizeMult
            if leg_in_tr < effective_base_size_mult * max_base_tr or leg_in_tr < self.legInMinAtrMult * self.atr_val[pos_leg_in]:
                continue
            pos_leg_out = i - leg_out_idx
            leg_out_tr = self._tr(i, leg_out_idx)
            leg_out_high = self.high[pos_leg_out]
            leg_out_low = self.low[pos_leg_out]
            leg_out_close = self.close[pos_leg_out]
            leg_out_open = self.open[pos_leg_out]
            leg_out_vol = self.volume[pos_leg_out]
            leg_in_body_size = abs(leg_in_close - self.open[pos_leg_in])
            leg_out_body_size = abs(leg_out_close - leg_out_open)
            is_demand_leg_out = self._is_bull(i, leg_out_idx)
            is_supply_leg_out = self._is_bear(i, leg_out_idx)
            if not (is_demand_leg_out or is_supply_leg_out):
                continue
            # NOTE: Pine jaisa sirf BODY-engulf (+ no genuine gap) reject -
            # full-range (wick-inclusive) engulf reject rule REMOVED.
            is_leg_out_explosive = leg_out_tr >= self.legOutTrMult * self.atr_val[pos_leg_out]
            is_leg_out_wick_valid = self._wick_pct(i, leg_out_idx) <= self.maxWickPct
            passes_tr_hierarchy = leg_out_tr >= self.legOutMinTrRatio * leg_in_tr and leg_in_tr > max_base_tr
            passes_strict_candle_hierarchy = max_base_tr < leg_in_tr < leg_out_tr
            passes_strict_body_hierarchy = max_base_body < leg_in_body_size and leg_out_body_size > self.legOutToLegInBodyMult * leg_in_body_size
            passes_leg_out_close_confirmation = leg_out_close > max_base_high if is_demand_leg_out else leg_out_close < min_base_low
            # Volume rule: legOutVol > legInVol. Pine me volume hamesha
            # maujood hota hai, isliye wahan ye rule hamesha lagta hai. Agar
            # data me volume column na ho (ya 0/NaN ho) to rule skip kar diya
            # jaata hai - zero zones na aayein, silently sab reject na ho.
            leg_out_volume_missing = not np.isfinite(leg_out_vol) or leg_out_vol <= 0
            passes_volume = leg_out_volume_missing or leg_out_vol > leg_in_vol
            is_overnight = self._is_overnight_gap(i)
            has_imbalance = True
            has_genuine_gap = False
            gap_size = 0.0
            if self.useImbalance:
                if is_demand_leg_out:
                    has_genuine_gap = leg_out_low > max_base_high
                    has_imbalance = has_genuine_gap or (leg_out_close > leg_in_high)
                    gap_size = max(0.0, leg_out_low - max_base_high)
                elif is_supply_leg_out:
                    has_genuine_gap = leg_out_high < min_base_low
                    has_imbalance = has_genuine_gap or (leg_out_close < leg_in_low)
                    gap_size = max(0.0, min_base_low - leg_out_high)
            leg_out_body_high = max(leg_out_open, leg_out_close)
            leg_out_body_low = min(leg_out_open, leg_out_close)
            if leg_out_body_low <= min_base_low and leg_out_body_high >= max_base_high and not has_genuine_gap:
                continue
            is_rbr = leg_in_is_bull and bull_clv >= self.minClvPct and is_demand_leg_out
            is_dbr = leg_in_is_bear and bear_clv >= self.minClvPct and is_demand_leg_out
            is_dbd = leg_in_is_bear and bear_clv >= self.minClvPct and is_supply_leg_out
            is_rbd = leg_in_is_bull and bull_clv >= self.minClvPct and is_supply_leg_out
            if not ((is_rbr or is_dbr or is_dbd or is_rbd) and is_leg_out_explosive and is_leg_out_wick_valid and passes_tr_hierarchy and passes_strict_candle_hierarchy and passes_strict_body_hierarchy and passes_leg_out_close_confirmation and passes_volume and has_imbalance):
                continue
            prox_val = max_base_high if is_demand_leg_out else min_base_low
            dist_val = min_base_low if is_demand_leg_out else max_base_high

            # NEW: EOD Range Filter - Only zones within Day High+10% Low-10% Range
            # Changeable option: eodHighBufferPct, eodLowBufferPct
            if not (eod_low <= prox_val <= eod_high):
                continue

            sl_val = dist_val - self.slBufferAtr * self.atr_val[i] if is_demand_leg_out else dist_val + self.slBufferAtr * self.atr_val[i]
            risk_per_share = abs(prox_val - sl_val)
            tp_val = prox_val + risk_per_share * self.targetRR if is_demand_leg_out else prox_val - risk_per_share * self.targetRR
            leg_out_mid_level = leg_out_high - self.testedLegOutRetracePct * (leg_out_high - leg_out_low) if is_demand_leg_out else leg_out_low + self.testedLegOutRetracePct * (leg_out_high - leg_out_low)
            zone_found_on_this_bar = True
            is_duplicate = False
            checked = 0
            for check_zone in reversed(self.live_zones):
                if check_zone.isDemand == is_demand_leg_out and abs(check_zone.proxVal - prox_val) < self.atr_val[i] * 0.25:
                    is_duplicate = True
                    break
                checked += 1
                if checked >= 11:
                    break
            if is_duplicate:
                continue
            box_border_color, box_fill_color = ("green", ("green", 0.15)) if is_demand_leg_out else ("red", ("red", 0.15))
            risk_pct_of_price = risk_per_share / prox_val * 100.0 if prox_val else float("nan")

            # ------------------------------------------------------------
            # NEW RULE 3: Boring-Colour High-Quality (HQ) Zone Flag
            # Demand Zone -> सारी base candles RED (bearish) हों
            # Supply Zone -> सारी base candles GREEN (bullish) हों
            # (सिर्फ़ flag/tag - कोई filtering या score10 पर असर नहीं)
            # ------------------------------------------------------------
            base_colour_ok = False
            hq_probability_pct = float("nan")
            hq_reason = ""
            if self.enableHQBaseColourCheck and base_colors:
                desired_colour = "bear" if is_demand_leg_out else "bull"
                base_colour_ok = all(c == desired_colour for c in base_colors)
                if base_colour_ok:
                    hq_probability_pct = self.hqBaseColourProbabilityPct
                    colour_label = "Red" if desired_colour == "bear" else "Green"
                    zone_label = "Demand" if is_demand_leg_out else "Supply"
                    hq_reason = f"{colour_label} Boring Base in {zone_label} Zone (~{self.hqBaseColourProbabilityPct:g}% probability)"

            new_zone = Zone(proxVal=prox_val, distVal=dist_val, slVal=sl_val, tpVal=tp_val, isDemand=is_demand_leg_out, densityScore=0, isHQ=base_colour_ok, patternType="RBR" if is_rbr else "DBR" if is_dbr else "DBD" if is_dbd else "RBD", zoneCategory="Continuation" if (is_rbr or is_dbd) else "Reversal", state="Fresh", touchCount=0, startBarIndex=i - b_count, createdBarIndex=i, baseCount=b_count, legOutHigh=leg_out_high, legOutLow=leg_out_low, legOutMidLevel=leg_out_mid_level, isOvernight=is_overnight, legInTR=leg_in_tr, legOutTR=leg_out_tr, zoneBox=Box(left=i - b_count - 1, top=prox_val, right=i + 15, bottom=dist_val, border_color=box_border_color, bgcolor=box_fill_color), timestamp=self.df.index[i], riskPct=risk_pct_of_price, score10=0.0, baseColourOK=base_colour_ok, legInVolX=leg_in_vol / self.vol_sma[pos_leg_in] if self.vol_sma[pos_leg_in] and not np.isnan(self.vol_sma[pos_leg_in]) else float("nan"), legOutVolX=leg_out_vol / self.vol_sma[pos_leg_out] if self.vol_sma[pos_leg_out] and not np.isnan(self.vol_sma[pos_leg_out]) else float("nan"), gapToLegIn=gap_size, hqProbabilityPct=hq_probability_pct, hqReason=hq_reason, baseIndecision=base_indecision_count > 0, baseDojiCount=base_doji_count)
            self.active_zones.append(new_zone)
            self.live_zones.append(new_zone)

    def _update_zone_states(self, i: int) -> None:
        if not self.live_zones:
            return
        lo_t, hi_t = self.low[i], self.high[i]
        for k in range(len(self.live_zones) - 1, -1, -1):
            zone = self.live_zones[k]
            if i <= zone.createdBarIndex:
                zone.zoneBox.set_right(i + 15)
                continue

            # ----------------------------------------------------------
            # NEW RULE 2: Leg-out Coverage Guard (checked incrementally,
            # bar-by-bar, while the zone is still Fresh i.e. before the
            # first genuine retest). Mathematically equivalent to running
            # check_leg_out_coverage() over the whole window up to bar i,
            # since earlier bars were already vetted on their own turn.
            # ----------------------------------------------------------
            covered_broken = False
            if zone.state == "Fresh" and self.enableLegOutCoverCheck:
                leg_out_range = zone.legOutHigh - zone.legOutLow
                if leg_out_range > 0:
                    overlap = max(0.0, min(hi_t, zone.legOutHigh) - max(lo_t, zone.legOutLow))
                    if (overlap / leg_out_range) > (self.legOutMaxCoverPct / 100.0):
                        zone.state = "Broken"
                        zone.breakReason = "LegOutCoveredGt90Pct"
                        covered_broken = True

            if not covered_broken:
                if zone.state == "Fresh":
                    if zone.isDemand:
                        if lo_t <= zone.distVal:
                            zone.state = "Broken"
                        elif lo_t <= zone.proxVal:
                            zone.state = "Tested"
                            zone.touchCount += 1
                    else:
                        if hi_t >= zone.distVal:
                            zone.state = "Broken"
                        elif hi_t >= zone.proxVal:
                            zone.state = "Tested"
                            zone.touchCount += 1

                    # --------------------------------------------------
                    # NEW RULE 4: White Area Validation - runs exactly
                    # once, at the very first Fresh -> Tested transition.
                    # Result is only tagged on the zone (whiteAreaOK);
                    # it does NOT change the Tested state either way.
                    # --------------------------------------------------
                    if zone.state == "Tested":
                        zone.entryBarIndex = i
                        zone.entryTimestamp = self.df.index[i]
                        if self.enableWhiteAreaCheck:
                            base_start_idx = zone.startBarIndex
                            base_end_idx = zone.createdBarIndex - 1
                            if base_end_idx >= base_start_idx:
                                zone.whiteAreaOK = check_white_area(self.df, base_start_idx, base_end_idx, zone.createdBarIndex, i)
                            else:
                                zone.whiteAreaOK = True

                elif zone.state == "Tested":
                    if zone.isDemand:
                        if lo_t <= zone.distVal:
                            zone.state = "Broken"
                        elif lo_t <= zone.proxVal:
                            zone.touchCount += 1
                    else:
                        if hi_t >= zone.distVal:
                            zone.state = "Broken"
                        elif hi_t >= zone.proxVal:
                            zone.touchCount += 1

            if zone.state == "Tested" and zone.touchCount > self.maxTestedCount:
                zone.state = "Broken"
            if zone.state == "Broken":
                zone.zoneBox.set_bgcolor(("gray", 0.05))
                zone.zoneBox.set_border_color(("gray", 0.20))
                self.live_zones.pop(k)
            else:
                zone.zoneBox.set_right(i + 15)

    def run(self) -> List[Zone]:
        min_bar = max(self.atrPeriod, self.maxBaseCount + 3, 11)
        for i in range(min_bar, self.n):
            # Zone Scan Candle Complete होने के बाद ही हो - Rules Unchanged + New Check
            # Do not create a zone on the last available candle (forming candle)
            if self.scanAfterCandleComplete:
                if i >= self.n - 1:
                    self._update_zone_states(i)
                    continue
            if i < self.n - 1 and not np.isnan(self.atr_val[i]):
                self._scan_bar(i)
            self._update_zone_states(i)
        return self.active_zones

# -----------------------------------------------------------------------------
# Public API - Rules Unchanged
# -----------------------------------------------------------------------------
def settings(accountCapital: Optional[float] = None, **overrides: Any) -> Dict[str, Any]:
    result = dict(PINE_DEFAULTS)
    if accountCapital is not None:
        overrides["accountCapital"] = accountCapital
    for key, value in overrides.items():
        if key in PINE_DEFAULTS:
            result[key] = value
    result["accountCapital"] = _positive_float(result["accountCapital"], "accountCapital")
    return result

def scan_zones(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None, accountCapital: Optional[float] = None, tf: Optional[str] = None) -> List[Zone]:
    """Scan zones - EOD Range Option + Candle Complete Check + Rules 1-4"""
    incoming = dict(params or {})
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    config = settings(**incoming)
    engine_config = {key: value for key, value in config.items() if key in PINE_DEFAULTS}
    return ZoneEngine(df, **engine_config).run()

def latest_active_zones(zones: List[Zone]) -> List[Zone]:
    return [z for z in zones if z.state in ("Fresh", "Tested")]

def high_quality_zones(zones: List[Zone]) -> List[Zone]:
    """NEW: Convenience helper - Rule 3 HQ (Boring-Colour) zones only.
    सिर्फ़ highlight/filter करने के लिए, core scan logic में कोई असर नहीं।"""
    return [z for z in zones if z.isHQ]
