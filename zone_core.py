"""
zone_core.py  -  Pine Script "Zone MTF" indicator ka Python scanner version.

INPUTS SYNC (is revision me):
    PINE_DEFAULTS ke saare inputs ab Pine Script ("Zone MTF") ke input.*()
    parameters se EXACT ek jaise hain - naam, default value aur order same.
    Pine ke display-only inputs (MTF lines / Shadows / Swings) bhi yahan
    config me rakhe gaye hain taaki dono taraf ka input-set ek ho; ye
    scanner ki zone validation me use nahi hote (Pine me bhi sirf display
    ke liye hain).

Scanner-only (Pine me nahi) - sirf ek:
    * useEodRange: EOD Range filter ON/OFF.
      Pine se bilkul same result chahiye to useEodRange=False kar dein.
      (Default True rakha gaya hai taaki purana scanner behaviour na badle.)

Baaki SAB kuch pehle jaisa: leg-in/base/leg-out rules, imbalance,
engulf check, classification, scoring (densityScore/minValidScore/HQ),
duplicate check, zone levels (SL/TP/legOutMidLevel).

*** STATE RULE (User Requirement - Tested zone सुधार) ***
    Fresh -> Tested tab hoga jab price PROXIMAL LINE (proxVal) ko chhuyega.
    Tested -> Broken sirf tab hoga jab DISTAL LINE (distVal) toot jayega.
    (maxTestedCount wala auto-break nahi hai - input maujood hai par inert.)

Note: Pine ke "PARITY INPUTS" (closing-wick, coverage, HQ-colour, white-area,
boring %, body mult, scan-once flags, scanAfterCandleComplete) Pine me bhi
logic se jude nahi hain, isliye yahan bhi sirf config me rakhe hain (inert).

Compatibility:
    Legacy Zone fields neutral defaults ke saath retained hain taaki purane
    scanner.py ke display-column accesses (z.whiteAreaOK etc.) chalte rahein.
    Timestamp conversion naive aur timezone-aware DatetimeIndex dono support karta hai.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PINE_DEFAULTS: Dict[str, Any] = {
    # ================= Pine: original indicator inputs =================
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
    "testedLegOutRetracePct": 1.00,     # "Tested Leg-Out Retrace %"
    "maxTestedCount": 1,                # "Max Tested Count" (state rule me inert)

    # ================= Pine: parity-only inputs (inert) =================
    "legOutToLegInBodyMult": 1.0,       # "Leg-Out to Leg-In Body Mult"
    "baseBoringMaxBodyPct": 0.55,       # "Base Small-Body (Indecision) %"
    "eodHighBufferPct": 10.0,           # "EOD High Buffer %"
    "eodLowBufferPct": 10.0,            # "EOD Low Buffer %"
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

    # ================= Pine: MTF / Shadow / Swing inputs =================
    # Ye Pine me sirf chart display ke liye hain; scanner validation me use nahi hote.
    "showMTF": True,                    # "Show other-TF proximal lines"
    "filterDistantMTF": True,           # "Hide distant MTF lines (display only)"
    "mtfNearPct": 8.0,                  # "Show lines within % of last price"
    "showShadow": True,                 # "Shadow when prior zone behind / broken / swing broken"
    "showFlags": True,                  # "Show BASE BREAK / SWING labels"
    "shadowAtr": 0.08,                  # "Shadow padding x ATR"
    "swingLeft": 3,                     # "Confirmed swing: bars on left"
    "swingRight": 3,                    # "Confirmed swing: bars on right"
    "maxStored": 220,                   # "Max chart zones (boxes <= 500)"

    # ================= SCANNER-ONLY (Pine me nahi) =================
    "useEodRange": True,                # EOD Range filter; Pine parity ke liye False karein
}

HARD_MAX_BASE_COUNT = 3


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


def _positive_float(value: Any, name: str) -> float:
    try:
        r = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(r) or r <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return r


def get_eod_range(df: pd.DataFrame, idx: int, high_buffer_pct: float = 10.0,
                  low_buffer_pct: float = 10.0) -> tuple[float, float]:
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
        self.time_ms = time_index.astype("datetime64[ns]").astype(np.int64) // 10**6
        self.active_zones: List[Zone] = []
        self.live_zones: List[Zone] = []
        self._prepare()

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

    def _scan_bar(self, i: int) -> None:
        atr_now = self.atr[i]
        found = False
        for bc in range(self.minBaseCount, self.maxBaseCount + 1):
            if found:
                break
            li = bc + 1
            pi = li + 1
            p_in, p_prev, p_out = i - li, i - pi, i
            if p_prev < 0 or np.isnan(self.atr[p_in]):
                continue

            leg_in_tr = self._tr(p_in)
            in_low, in_high, in_close = self.l[p_in], self.h[p_in], self.c[p_in]
            in_vol = self.v[p_in]
            in_rng = in_high - in_low
            in_bull, in_bear = self._bull(p_in), self._bear(p_in)
            if in_rng == 0 or self._body_pct(p_in) < self.legInMinBodyPct:
                continue

            if (in_bull and self._bear(p_prev)) or (in_bear and self._bull(p_prev)):
                pbh, pbl = max(self.o[p_prev], self.c[p_prev]), min(self.o[p_prev], self.c[p_prev])
                overlap = max(0.0, min(pbh, in_high) - max(pbl, in_low))
                if overlap / in_rng >= self.rejectOppositeCoverPct:
                    continue

            bull_clv = (in_close - in_low) / in_rng
            bear_clv = (in_high - in_close) / in_rng

            ok = True
            max_base_tr = 0.0
            max_base_high = -1.0
            min_base_low = 1_000_000_000.0
            for b in range(1, bc + 1):
                pb = i - b
                if np.isnan(self.atr[pb]):
                    ok = False
                    break
                btr = self._tr(pb)
                if btr > self.maxBaseAtrMult * self.atr[pb]:
                    ok = False
                    break
                max_base_tr = max(max_base_tr, btr)
                max_base_high = max(max_base_high, self.h[pb])
                min_base_low = min(min_base_low, self.l[pb])
            if not ok or max_base_tr == 0:
                continue

            eff_mult = 1.5 if bc == 1 else self.legInToBaseSizeMult
            if leg_in_tr < eff_mult * max_base_tr:
                continue
            if not (leg_in_tr >= self.legInMinAtrMult * self.atr[p_in]):
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

            if (min(out_open, out_close) <= min_base_low and max(out_open, out_close) >= max_base_high
                    and not has_gap):
                continue

            is_rbr = in_bull and bull_clv >= self.minClvPct and is_demand
            is_dbr = in_bear and bear_clv >= self.minClvPct and is_demand
            is_dbd = in_bear and bear_clv >= self.minClvPct and is_supply
            is_rbd = in_bull and bull_clv >= self.minClvPct and is_supply
            if not ((is_rbr or is_dbr or is_dbd or is_rbd) and explosive and wick_ok
                    and tr_hier and vol_ok and has_imb):
                continue

            score = 0
            if bc == 1:
                score += 15
            if leg_in_tr >= self.hqLegInAtrMult * self.atr[p_in]:
                score += 10
            if leg_out_tr >= self.hqLegOutTrMult * leg_in_tr:
                score += 15
            if leg_in_tr >= 2.0 * max_base_tr and leg_out_tr >= 2.0 * leg_in_tr:
                score += 15
            if out_vol > self.vol_sma[p_out]:
                score += 10
            out_rng = out_high - out_low
            if is_demand:
                pos = (out_close - out_low) / out_rng if out_rng > 0 else 0
                own_body = self._body_pct(p_out)
                if is_dbr:
                    if pos >= 0.80 or own_body >= self.legOutBodyHeavyPct:
                        score += 15
                elif pos >= 0.80:
                    score += 15
            else:
                pos = (out_high - out_close) / out_rng if out_rng > 0 else 0
                if pos >= 0.80:
                    score += 15

            opp_base = False
            for b in range(1, bc + 1):
                if (is_demand and self._bear(i - b)) or (is_supply and self._bull(i - b)):
                    opp_base = True
                    break
            if opp_base:
                score += 10
            score += 10
            if has_gap:
                score += self.genuineGapBonus
            if is_overnight and has_gap:
                score += self.overnightGapBonus

            if score < self.minValidScore:
                continue

            prox = max_base_high if is_demand else min_base_low
            dist = min_base_low if is_demand else max_base_high

            if self.useEodRange:
                eod_high = self.day_high[i] * (1 + self.eodHighBufferPct / 100.0)
                eod_low = self.day_low[i] * (1 - self.eodLowBufferPct / 100.0)
                if not (eod_low <= prox <= eod_high):
                    continue

            is_hq = score >= self.hqScoreThreshold
            found = True

            sl = dist - self.slBufferAtr * atr_now if is_demand else dist + self.slBufferAtr * atr_now
            risk = abs(prox - sl)
            tp = prox + risk * self.targetRR if is_demand else prox - risk * self.targetRR
            if is_demand:
                mid = out_high - self.testedLegOutRetracePct * (out_high - out_low)
            else:
                mid = out_low + self.testedLegOutRetracePct * (out_high - out_low)

            dup = False
            checked = 0
            for z in reversed(self.live_zones):
                if z.isDemand == is_demand and abs(z.proxVal - prox) < atr_now * 0.25:
                    dup = True
                    break
                checked += 1
                if checked >= 11:
                    break
            if dup:
                continue

            pattern = "RBR" if is_rbr else ("DBR" if is_dbr else ("DBD" if is_dbd else "RBD"))
            cat = "Continuation" if (is_rbr or is_dbd) else "Reversal"
            border = "green" if is_demand else "red"
            fill = ("green", 0.15) if is_demand else ("red", 0.15)
            vs_in, vs_out = self.vol_sma[p_in], self.vol_sma[p_out]
            z = Zone(
                proxVal=prox, distVal=dist, slVal=sl, tpVal=tp, isDemand=is_demand, isHQ=is_hq,
                densityScore=score, patternType=pattern, zoneCategory=cat, state="Fresh",
                touchCount=0, startBarIndex=i - bc, createdBarIndex=i, baseCount=bc,
                legOutHigh=out_high, legOutLow=out_low, legOutMidLevel=mid,
                isOvernight=is_overnight, legInTR=leg_in_tr, legOutTR=leg_out_tr,
                zoneBox=Box(i - bc - 1, prox, i + 15, dist, border, fill),
                timestamp=self.df.index[i],
                riskPct=risk / prox * 100.0 if prox else float("nan"),
                score10=round(score / 10.0, 1),
                hasGenuineGap=has_gap, gapToLegIn=gap_size,
                legInVolX=in_vol / vs_in if vs_in and not np.isnan(vs_in) else float("nan"),
                legOutVolX=out_vol / vs_out if vs_out and not np.isnan(vs_out) else float("nan"),
            )
            self.active_zones.append(z)
            self.live_zones.append(z)

    # ---------------- STATE TRACKING (User rule) ---------------------------
    # Fresh  -> Tested : price proximal line (proxVal) ko chhuye
    # Tested -> Broken : sirf distal line (distVal) toote
    # Fresh  -> Broken : distal seedha toot jaye (proximal touch ke bina)
    # -----------------------------------------------------------------------
    def _update_states(self, i: int) -> None:
        if not self.live_zones:
            return
        lo, hi = self.l[i], self.h[i]
        for k in range(len(self.live_zones) - 1, -1, -1):
            z = self.live_zones[k]

            if z.state == "Fresh":
                if z.isDemand:
                    if lo <= z.distVal:
                        z.state = "Broken"
                        z.breakReason = "distal_break_before_test"
                    elif lo <= z.proxVal:
                        z.state = "Tested"
                        z.touchCount += 1
                        if z.entryBarIndex is None:
                            z.entryBarIndex = i
                            z.entryTimestamp = self.df.index[i]
                else:
                    if hi >= z.distVal:
                        z.state = "Broken"
                        z.breakReason = "distal_break_before_test"
                    elif hi >= z.proxVal:
                        z.state = "Tested"
                        z.touchCount += 1
                        if z.entryBarIndex is None:
                            z.entryBarIndex = i
                            z.entryTimestamp = self.df.index[i]

            elif z.state == "Tested":
                if z.isDemand:
                    if lo <= z.distVal:
                        z.state = "Broken"
                        z.breakReason = "distal_break"
                    elif lo <= z.proxVal:
                        z.touchCount += 1
                else:
                    if hi >= z.distVal:
                        z.state = "Broken"
                        z.breakReason = "distal_break"
                    elif hi >= z.proxVal:
                        z.touchCount += 1

            # Purana maxTestedCount auto-break (requirement ke hisab se band):
            # if z.state == "Tested" and z.touchCount > self.maxTestedCount:
            #     z.state = "Broken"
            #     z.breakReason = "max_tested_count"

            if z.state == "Broken":
                z.breakBarIndex = i
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


def settings(accountCapital: Optional[float] = None, **overrides: Any) -> Dict[str, Any]:
    result = dict(PINE_DEFAULTS)
    if accountCapital is not None:
        overrides["accountCapital"] = accountCapital
    for k, v in overrides.items():
        if k in PINE_DEFAULTS:
            result[k] = v
    result["accountCapital"] = _positive_float(result["accountCapital"], "accountCapital")
    return result


def scan_zones(df: pd.DataFrame, params: Optional[Dict[str, Any]] = None,
               accountCapital: Optional[float] = None, tf: Optional[str] = None) -> List[Zone]:
    incoming = dict(params or {})
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    cfg = settings(**incoming)
    return ZoneEngine(df, **cfg).run()


def latest_active_zones(zones: List[Zone]) -> List[Zone]:
    return [z for z in zones if z.state in ("Fresh", "Tested")]


def high_quality_zones(zones: List[Zone]) -> List[Zone]:
    return [z for z in zones if z.isHQ]
