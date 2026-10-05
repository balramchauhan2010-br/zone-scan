"""
zone_core_validation.py
=======================

zone_core.py ka additive-validation version. Original zone scan ke inputs,
common leg-in/base/leg-out checks, scoring, EOD filter, duplicate detection,
SL/TP aur Fresh/Tested/Broken state logic ko preserve karta hai. Isme sirf
optional validation filters/tags add kiye gaye hain:

  * swingRangeAtrMult: leg-in aur leg-out candle ka minimum high-low range.
  * DBR/RBD reversal ke liye pehle se valid opposite-side reference zone ka
    engulf (default: distal line ke paar close).
  * Optional leg-out reward/risk filter (default OFF; threshold 2.0).
  * Optional pulse/trend tags; alignment filter default OFF.

Pulse/trend data ke saath scan karne ke liye scan_validated_zones() use karein.
scan_zones() original API ki tarah zone scanner chalata hai; pulse/trend tags
ke liye alag higher-timeframe data nahi leta.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Timeframe rule map: zone timeframe -> higher-timeframe pulse and trend rules.
RULE_TABLE_V2: Dict[str, Dict[str, str]] = {
    "10m": dict(pulse="SUPERTREND", pulse_tf="2W", trend="ST_20_4", trend_tf="3D"),
    "15m": dict(pulse="MACD_HIST", pulse_tf="2M", trend="ST_20_4", trend_tf="1W"),
    "30m": dict(pulse="MACD_HIST", pulse_tf="1M", trend="ST_20_4", trend_tf="3D"),
    "1H": dict(pulse="SUPERTREND", pulse_tf="6H", trend="DONCHIAN", trend_tf="1H"),
    "2H": dict(pulse="SMA200", pulse_tf="2H", trend="EMA_TRIPLE", trend_tf="2H"),
    "4H": dict(pulse="EMA_STACK", pulse_tf="3M", trend="ST_20_4", trend_tf="1W"),
    "6H": dict(pulse="EMA_STACK", pulse_tf="2M", trend="ST_10_3", trend_tf="3D"),
    "1D": dict(pulse="EMA_SLOPE", pulse_tf="3M", trend="ST_20_4", trend_tf="2W"),
    "1W": dict(pulse="MACD_HIST", pulse_tf="3M", trend="ST_20_4", trend_tf="2W"),
    "1M": dict(pulse="SUPERTREND", pulse_tf="3M", trend="ST_7_2", trend_tf="3M"),
}

PINE_DEFAULTS: Dict[str, Any] = {
    "accountCapital": 25000.0,
    "riskPct": 0.5,
    "targetRR": 5.0,
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

    # Pine parity inputs (kept for compatibility; still inert, as in zone_core.py)
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

    # Scanner-only EOD range inputs (same as zone_core.py)
    "eodHighBufferPct": 10.0,
    "eodLowBufferPct": 10.0,
    "useEodRange": True,

    # Added validation inputs
    "useLegOutRRFilter": False,
    "minLegOutRR": 2.0,
    "requireEngulfForReversal": True,
    "engulfLookbackBars": 25,
    "engulfAllowBrokenRef": True,
    "engulfMode": "distal_close",
    "engulfRefPosition": "high",
    "swingRangeAtrMult": 0.05,
    "usePulseTrend": True,
    "requirePulseTrendAligned": False,
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
    # Original Zone fields — kept in the same order for compatibility.
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

    # Added validation outputs. These do not replace the original fields.
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
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def get_eod_range(
    df: pd.DataFrame,
    idx: int,
    high_buffer_pct: float = 10.0,
    low_buffer_pct: float = 10.0,
) -> tuple[float, float]:
    try:
        day_value = df.index[idx].date()
        day = df[df.index.date == day_value]
        if day.empty:
            return float(df["low"].iloc[idx] * 0.9), float(df["high"].iloc[idx] * 1.1)
        return (
            float(day["low"].min() * (1 - low_buffer_pct / 100)),
            float(day["high"].max() * (1 + high_buffer_pct / 100)),
        )
    except Exception:
        return float(df["low"].iloc[idx] * 0.9), float(df["high"].iloc[idx] * 1.1)


def check_white_area(
    df: pd.DataFrame,
    base_start_idx: int,
    base_end_idx: int,
    leg_out_idx: int,
    curr_idx: int,
) -> bool:
    base_high = float(df["high"].iloc[base_start_idx : base_end_idx + 1].max())
    base_low = float(df["low"].iloc[base_start_idx : base_end_idx + 1].min())
    if leg_out_idx + 1 >= curr_idx:
        return True
    window = df.iloc[leg_out_idx + 1 : curr_idx]
    return not bool(((window["low"] <= base_high) & (window["high"] >= base_low)).any())


def check_leg_out_coverage(
    df: pd.DataFrame,
    leg_out_idx: int,
    curr_idx: int,
    max_cover_pct: float = 90.0,
) -> bool:
    high = float(df["high"].iloc[leg_out_idx])
    low = float(df["low"].iloc[leg_out_idx])
    candle_range = high - low
    if candle_range <= 0 or leg_out_idx + 1 > curr_idx:
        return True
    window = df.iloc[leg_out_idx + 1 : curr_idx + 1]
    overlap = (
        np.minimum(window["high"], high) - np.maximum(window["low"], low)
    ).clip(lower=0)
    return not bool(((overlap / candle_range) > max_cover_pct / 100).any())


SCAN_TRACKER: Dict[str, datetime] = {}


def should_scan_now(tf: str, force: bool = False) -> bool:
    now = datetime.now()
    if force:
        return True
    days = {"Monthly": 30, "Weekly": 7, "Daily": 1}
    key = tf if tf in days else f"Intraday_{tf}"
    last = SCAN_TRACKER.get(key)
    minutes = {
        "3M": 3,
        "5M": 5,
        "10M": 10,
        "15M": 15,
        "30M": 30,
        "75M": 75,
        "1H": 60,
        "2H": 120,
        "4H": 240,
        "6H": 360,
    }.get(tf, 15)
    wait_seconds = days[tf] * 86400 if tf in days else minutes * 60
    if last is None or (now - last).total_seconds() >= wait_seconds:
        SCAN_TRACKER[key] = now
        return True
    return False


def resolve_rules(zone_tf: str) -> Dict[str, str]:
    key = str(zone_tf).strip()
    aliases = {
        "D": "1D", "DAILY": "1D", "1DAY": "1D",
        "W": "1W", "WEEKLY": "1W",
        "M": "1M", "MONTHLY": "1M",
        "10M": "10m", "15M": "15m", "30M": "30m",
        "1H": "1H", "2H": "2H", "4H": "4H", "6H": "6H",
    }
    key = aliases.get(key.upper(), key)
    if key not in RULE_TABLE_V2:
        return dict(pulse="SUPERTREND", pulse_tf="2W", trend="ST_20_4", trend_tf="3D")
    return dict(RULE_TABLE_V2[key])


# ------------------------------- Pulse indicators -------------------------------
def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _wilder(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    previous_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr_series(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return _wilder(_true_range(df), length)


def _supertrend_dir(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=int, index=df.index)
    midpoint = (df["high"] + df["low"]) / 2.0
    atr = _atr_series(df, period)
    upper = (midpoint + multiplier * atr).to_numpy(float)
    lower = (midpoint - multiplier * atr).to_numpy(float)
    close = df["close"].to_numpy(float)
    count = len(df)
    final_upper = np.zeros(count, dtype=float)
    final_lower = np.zeros(count, dtype=float)
    supertrend = np.zeros(count, dtype=float)
    direction = np.zeros(count, dtype=int)

    final_upper[0] = upper[0]
    final_lower[0] = lower[0]
    supertrend[0] = upper[0]
    direction[0] = -1
    for i in range(1, count):
        final_upper[i] = (
            upper[i]
            if upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]
            else final_upper[i - 1]
        )
        final_lower[i] = (
            lower[i]
            if lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]
            else final_lower[i - 1]
        )
        if supertrend[i - 1] == final_upper[i - 1]:
            supertrend[i] = final_upper[i] if close[i] <= final_upper[i] else final_lower[i]
        else:
            supertrend[i] = final_lower[i] if close[i] >= final_lower[i] else final_upper[i]
        direction[i] = -1 if supertrend[i] == final_upper[i] else 1
    return pd.Series(direction, index=df.index)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = _ema(close, fast) - _ema(close, slow)
    return macd_line, _ema(macd_line, signal)


def _di(df: pd.DataFrame, length: int = 14):
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )
    atr = _atr_series(df, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * _wilder(plus_dm, length) / atr
        minus_di = 100 * _wilder(minus_dm, length) / atr
    return plus_di, minus_di


def p_ema2050(df: pd.DataFrame) -> pd.Series:
    close = df["close"]
    ema20, ema50 = _ema(close, 20), _ema(close, 50)
    values = np.where(
        (close > ema20) & (close > ema50),
        1,
        np.where((close < ema20) & (close < ema50), -1, 0),
    )
    return pd.Series(values, index=df.index)


def p_ema_stack(df: pd.DataFrame) -> pd.Series:
    ema20, ema50, ema100 = _ema(df["close"], 20), _ema(df["close"], 50), _ema(df["close"], 100)
    values = np.where(
        (ema20 > ema50) & (ema50 > ema100),
        1,
        np.where((ema20 < ema50) & (ema50 < ema100), -1, 0),
    )
    return pd.Series(values, index=df.index)


def p_ema_slope(df: pd.DataFrame) -> pd.Series:
    close = df["close"]
    ema20 = _ema(close, 20)
    slope = ema20.diff(5)
    values = np.where((slope > 0) & (close > ema20), 1, np.where((slope < 0) & (close < ema20), -1, 0))
    return pd.Series(values, index=df.index)


def p_sma200(df: pd.DataFrame) -> pd.Series:
    close = df["close"]
    sma200 = close.rolling(200).mean()
    values = np.where(close > sma200, 1, np.where(close < sma200, -1, 0))
    return pd.Series(values, index=df.index)


def p_macd_hist(df: pd.DataFrame) -> pd.Series:
    macd_line, signal_line = _macd(df["close"])
    histogram = macd_line - signal_line
    return pd.Series(np.where(histogram > 0, 1, np.where(histogram < 0, -1, 0)), index=df.index)


def p_supertrend(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 10, 3.0)


def t_st_10_3(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 10, 3.0)


def t_st_7_2(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 7, 2.0)


def t_st_20_4(df: pd.DataFrame) -> pd.Series:
    return _supertrend_dir(df, 20, 4.0)


def t_ema_triple(df: pd.DataFrame) -> pd.Series:
    close = df["close"]
    ema20, ema50 = _ema(close, 20), _ema(close, 50)
    values = np.where((close > ema20) & (ema20 > ema50), 1, np.where((close < ema20) & (ema20 < ema50), -1, 0))
    return pd.Series(values, index=df.index)


def t_donchian(df: pd.DataFrame, length: int = 20) -> pd.Series:
    close = df["close"]
    upper = df["high"].rolling(length).max().shift(1)
    lower = df["low"].rolling(length).min().shift(1)
    midpoint = (upper + lower) / 2
    values = np.where(close > midpoint, 1, np.where(close < midpoint, -1, 0))
    return pd.Series(values, index=df.index)


def t_di_cross(df: pd.DataFrame) -> pd.Series:
    plus_di, minus_di = _di(df, 14)
    return pd.Series(np.where(plus_di > minus_di, 1, np.where(minus_di > plus_di, -1, 0)), index=df.index)


PULSE_FUNCS = {
    "EMA20_50": p_ema2050,
    "EMA_STACK": p_ema_stack,
    "EMA_SLOPE": p_ema_slope,
    "SMA200": p_sma200,
    "MACD_HIST": p_macd_hist,
    "SUPERTREND": p_supertrend,
}
TREND_FUNCS = {
    "ST_10_3": t_st_10_3,
    "ST_7_2": t_st_7_2,
    "ST_20_4": t_st_20_4,
    "EMA_TRIPLE": t_ema_triple,
    "DONCHIAN": t_donchian,
    "DI_CROSS": t_di_cross,
}


def pulse_state(df: pd.DataFrame, rule: str) -> pd.Series:
    if rule not in PULSE_FUNCS:
        raise KeyError(f"unknown pulse rule {rule!r}; available: {sorted(PULSE_FUNCS)}")
    return PULSE_FUNCS[rule](df).astype(int)


def trend_state(df: pd.DataFrame, rule: str) -> pd.Series:
    if rule not in TREND_FUNCS:
        raise KeyError(f"unknown trend rule {rule!r}; available: {sorted(TREND_FUNCS)}")
    return TREND_FUNCS[rule](df).astype(int)


def map_completed(entry_index: pd.DatetimeIndex, htf_index: pd.DatetimeIndex) -> np.ndarray:
    """Map each entry timestamp to the most recent completed HTF bar, not its live bar."""
    entries = pd.DatetimeIndex(entry_index)
    higher = pd.DatetimeIndex(htf_index)
    if len(entries) == 0:
        return np.empty(0, dtype=int)
    if len(higher) == 0:
        return np.full(len(entries), -1, dtype=int)
    if not entries.is_monotonic_increasing or not higher.is_monotonic_increasing:
        raise ValueError("entry_index and htf_index must be sorted in ascending time order")
    htf_ns = higher.asi8
    entry_ns = entries.asi8
    int64_max = np.iinfo(np.int64).max
    next_htf_start = np.concatenate((htf_ns[1:], np.array([int64_max], dtype=np.int64)))
    return np.searchsorted(next_htf_start, entry_ns, side="right") - 1


def _timeframe_spec(tf: str):
    text = str(tf).strip()
    upper = text.upper()
    aliases = {"D": "1D", "DAILY": "1D", "W": "1W", "WEEKLY": "1W", "M": "1M", "MONTHLY": "1M"}
    upper = aliases.get(upper, upper)
    if upper in {"1D", "2D", "3D"}:
        return upper, pd.Timedelta(days=int(upper[:-1]))
    if upper in {"1W", "2W"}:
        count = int(upper[:-1])
        return f"{count}W-FRI", pd.Timedelta(days=7 * count)
    if upper in {"1M", "2M", "3M"}:
        count = int(upper[:-1])
        # MonthEnd offsets avoid pandas-version dependence on the 'ME' alias.
        return pd.offsets.MonthEnd(count), pd.Timedelta(days=30 * count)
    if upper in {"1H", "2H", "4H", "6H"}:
        count = int(upper[:-1])
        return f"{count}h", pd.Timedelta(hours=count)
    # In these custom strings, 10M/15M/30M mean minutes, not months.
    if upper in {"10M", "15M", "30M"}:
        count = int(upper[:-1])
        return f"{count}min", pd.Timedelta(minutes=count)
    raise ValueError(f"unsupported timeframe {tf!r}")


def resample_ohlc(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample OHLC data. Data must have a sorted DatetimeIndex."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("resample_ohlc requires a DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError("resample_ohlc requires rows sorted by timestamp")
    required = {"open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise KeyError(f"missing OHLC columns: {sorted(missing)}")
    rule, target_delta = _timeframe_spec(tf)
    if len(df.index) > 1:
        diffs = np.diff(df.index.asi8)
        diffs = diffs[diffs > 0]
        median_delta = int(np.median(diffs)) if len(diffs) else 0
        # If the source is already at the requested cadence (or coarser),
        # preserve its bars rather than fabricating finer data.
        if median_delta and median_delta >= int(target_delta.value * 0.90):
            if target_delta <= pd.Timedelta(days=1):
                return df.copy()
            # For calendar weeks/months, only return unchanged if the sampled
            # bar spacing is already approximately one target period.
            if median_delta >= int(target_delta.value * 0.90):
                source_days = median_delta / pd.Timedelta(days=1).value
                if target_delta >= pd.Timedelta(days=7) and source_days >= target_delta / pd.Timedelta(days=1) * 0.90:
                    return df.copy()
    aggregations = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        aggregations["volume"] = "sum"
    result = df.resample(rule, label="left", closed="left").agg(aggregations)
    return result.dropna(subset=["open", "high", "low", "close"])


# -------------------------------- Zone engine --------------------------------
class ZoneEngine:
    def __init__(self, df: pd.DataFrame, **kwargs: Any):
        self.df = df.copy()
        if "volume" not in self.df.columns:
            self.df["volume"] = 0.0
        self.df["volume"] = self.df["volume"].fillna(0.0)
        for key, default in PINE_DEFAULTS.items():
            setattr(self, key, kwargs.get(key, default))

        self.accountCapital = _positive_float(self.accountCapital, "accountCapital")
        # Keep the original zone_core.py base-count behavior.
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
        # Only fully accepted zones are added here, so rejected candidates
        # cannot later act as engulf references.
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
                np.maximum(
                    np.abs(self.h[1:] - previous_close),
                    np.abs(self.l[1:] - previous_close),
                ),
            )
        self.atr = self._rma(true_range, self.atrPeriod)
        self.vol_sma = self.df["volume"].rolling(self.volSmaPeriod).mean().to_numpy()
        day_key = self.df.index.normalize()
        self.day_high = self.df["high"].groupby(day_key).transform("max").to_numpy()
        self.day_low = self.df["low"].groupby(day_key).transform("min").to_numpy()

    def _tr(self, p: int) -> float:
        previous_close = self.c[p - 1]
        return max(
            self.h[p] - self.l[p],
            abs(self.h[p] - previous_close),
            abs(self.l[p] - previous_close),
        )

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
        """New filter: leg-in/leg-out candle high-low must exceed ATR fraction."""
        candle_range = self.h[p] - self.l[p]
        atr_value = self.atr[p]
        if not np.isfinite(atr_value) or atr_value <= 0:
            return False
        return candle_range >= self.swingRangeAtrMult * atr_value

    def _overnight(self, i: int) -> bool:
        if i == 0:
            return False
        return bool(
            self.dow[i] != self.dow[i - 1]
            or (self.time_ms[i] - self.time_ms[i - 1]) > 86400000
        )

    @staticmethod
    def _is_dbd_like(zone: Zone) -> bool:
        return (not zone.isDemand) and (
            zone.patternType == "DBD" or zone.zoneCategory == "Continuation"
        )

    @staticmethod
    def _is_rbr_like(zone: Zone) -> bool:
        return zone.isDemand and (
            zone.patternType == "RBR" or zone.zoneCategory == "Continuation"
        )

    def _find_engulf_ref(
        self,
        i: int,
        is_demand: bool,
        in_high: float,
        in_low: float,
        out_close: float,
        atr_now: float,
        max_prox: float,
        min_prox: float,
        out_high: float,
        out_low: float,
    ) -> Optional[Zone]:
        """Find a previous, accepted opposite-side zone engulfed by this leg-out."""
        best: Optional[Zone] = None
        minimum_zone_width = self.swingRangeAtrMult * atr_now
        ref_position = (self.engulfRefPosition or "high").lower()
        engulf_mode = (self.engulfMode or "distal_close").lower()
        use_proximal = engulf_mode.startswith("proximal")
        use_wick = engulf_mode.endswith("wick")
        probe = (out_high if is_demand else out_low) if use_wick else out_close

        for zone in reversed(self.pattern_registry):
            age = i - zone.createdBarIndex
            if age > self.engulfLookbackBars:
                break
            if zone.createdBarIndex >= i:
                continue
            if not self.engulfAllowBrokenRef and zone.state == "Broken":
                continue
            if abs(zone.proxVal - zone.distVal) < minimum_zone_width:
                continue

            if is_demand:
                # DBR: a prior supply/DBD-like zone must be above the leg-in.
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
                # RBD: a prior demand/RBR-like zone must be below the leg-in.
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

            # Added validation: both impulse candles need a minimum ATR range.
            if not (self._swing_ok(p_in) and self._swing_ok(p_out)):
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
                overlap = max(
                    0.0,
                    min(previous_body_high, in_high) - max(previous_body_low, in_low),
                )
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

            if (
                min(out_open, out_close) <= min_base_low
                and max(out_open, out_close) >= max_base_high
                and not has_gap
            ):
                continue

            is_rbr = in_bull and bull_clv >= self.minClvPct and is_demand
            is_dbr = in_bear and bear_clv >= self.minClvPct and is_demand
            is_dbd = in_bear and bear_clv >= self.minClvPct and is_supply
            is_rbd = in_bull and bull_clv >= self.minClvPct and is_supply
            if not (is_rbr or is_dbr or is_dbd or is_rbd):
                continue
            if not (explosive and wick_ok and tr_hierarchy_ok and volume_ok and has_imbalance):
                continue

            # Original density score logic.
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

            sl = (
                distal - self.slBufferAtr * atr_now
                if is_demand
                else distal + self.slBufferAtr * atr_now
            )
            risk = abs(proximal - sl)
            tp = (
                proximal + risk * self.targetRR
                if is_demand
                else proximal - risk * self.targetRR
            )
            if is_demand:
                mid = out_high - self.testedLegOutRetracePct * (out_high - out_low)
                leg_out_reward = out_high - proximal
            else:
                mid = out_low + self.testedLegOutRetracePct * (out_high - out_low)
                leg_out_reward = proximal - out_low
            leg_out_rr = leg_out_reward / risk if risk > 0 else float("nan")
            leg_out_passes_rr = bool(np.isfinite(leg_out_rr) and leg_out_rr >= self.minLegOutRR)

            # Optional 1:N filter; OFF by default as requested.
            if self.useLegOutRRFilter and not leg_out_passes_rr:
                continue

            pattern = "RBR" if is_rbr else ("DBR" if is_dbr else ("DBD" if is_dbd else "RBD"))
            category = "Continuation" if (is_rbr or is_dbd) else "Reversal"

            # Rule-3: DBR needs a prior DBD-like supply reference when enabled.
            # Rule-4: RBD needs a prior RBR-like demand reference when enabled.
            engulf_ref: Optional[Zone] = None
            rule1_ok = bool(is_rbr)
            rule2_ok = bool(is_dbd)
            rule3_ok = False
            rule4_ok = False
            if is_dbr:
                if self.requireEngulfForReversal:
                    engulf_ref = self._find_engulf_ref(
                        i, True, in_high, in_low, out_close, atr_now,
                        max_prox=proximal, min_prox=proximal,
                        out_high=out_high, out_low=out_low,
                    )
                    rule3_ok = engulf_ref is not None
                else:
                    rule3_ok = True
                if not rule3_ok:
                    continue
            elif is_rbd:
                if self.requireEngulfForReversal:
                    engulf_ref = self._find_engulf_ref(
                        i, False, in_high, in_low, out_close, atr_now,
                        max_prox=proximal, min_prox=proximal,
                        out_high=out_high, out_low=out_low,
                    )
                    rule4_ok = engulf_ref is not None
                else:
                    rule4_ok = True
                if not rule4_ok:
                    continue

            valid_demand = bool((is_rbr and rule1_ok) or (is_dbr and rule3_ok))
            valid_supply = bool((is_dbd and rule2_ok) or (is_rbd and rule4_ok))
            if is_demand and not valid_demand:
                continue
            if is_supply and not valid_supply:
                continue

            # Keep the original one-candidate-per-leg-out behavior.
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
                legOutRR=float(leg_out_rr),
                legOutPassesRR=leg_out_passes_rr,
                legInBarIndex=int(p_in),
                legInHigh=float(in_high),
                legInLow=float(in_low),
                legOutClose=float(out_close),
                engulfRefPattern=(engulf_ref.patternType if engulf_ref is not None else ""),
                engulfRefDist=(float(engulf_ref.distVal) if engulf_ref is not None else float("nan")),
                engulfRefBar=(int(engulf_ref.createdBarIndex) if engulf_ref is not None else None),
                engulfOK=engulf_ref is not None,
                rule1OK=rule1_ok,
                rule2OK=rule2_ok,
                rule3OK=rule3_ok,
                rule4OK=rule4_ok,
                validDemand=valid_demand,
                validSupply=valid_supply,
            )
            self.active_zones.append(zone)
            self.live_zones.append(zone)
            self.pattern_registry.append(zone)

    def _update_states(self, i: int) -> None:
        if not self.live_zones:
            return
        low, high = self.l[i], self.h[i]
        for k in range(len(self.live_zones) - 1, -1, -1):
            zone = self.live_zones[k]
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

            # Preserve zone_core.py rule: maxTestedCount does not auto-break zones.
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


def apply_pulse_trend(
    zones: List[Zone],
    df_pulse: Optional[pd.DataFrame],
    df_trend: Optional[pd.DataFrame],
    pulse_rule: str,
    trend_rule: str,
    pulse_tf: str = "",
    trend_tf: str = "",
) -> List[Zone]:
    if not zones or df_pulse is None or df_trend is None:
        return zones
    if df_pulse.empty or df_trend.empty:
        return zones
    pulse_values = pulse_state(df_pulse, pulse_rule).to_numpy(dtype=int)
    trend_values = trend_state(df_trend, trend_rule).to_numpy(dtype=int)
    zone_times = pd.DatetimeIndex([zone.timestamp for zone in zones])
    pulse_positions = map_completed(zone_times, pd.DatetimeIndex(df_pulse.index))
    trend_positions = map_completed(zone_times, pd.DatetimeIndex(df_trend.index))

    for idx, zone in enumerate(zones):
        p_pos = int(pulse_positions[idx])
        t_pos = int(trend_positions[idx])
        pulse_value = pulse_values[p_pos] if 0 <= p_pos < len(pulse_values) else 0
        trend_value = trend_values[t_pos] if 0 <= t_pos < len(trend_values) else 0
        zone.pulse = int(pulse_value)
        zone.trend = int(trend_value)
        zone.pulseRule = pulse_rule
        zone.trendRule = trend_rule
        zone.pulseTf = pulse_tf
        zone.trendTf = trend_tf
        if zone.isDemand:
            zone.biasAligned = bool(pulse_value == 1 and trend_value == 1)
        else:
            zone.biasAligned = bool(pulse_value == -1 and trend_value == -1)
    return zones


def scan_validated_zones(
    df_zone: pd.DataFrame,
    df_base: Optional[pd.DataFrame] = None,
    zone_tf: str = "1D",
    df_pulse: Optional[pd.DataFrame] = None,
    df_trend: Optional[pd.DataFrame] = None,
    pulse_rule: Optional[str] = None,
    pulse_tf: Optional[str] = None,
    trend_rule: Optional[str] = None,
    trend_tf: Optional[str] = None,
    require_aligned: bool = False,
    params: Optional[Dict[str, Any]] = None,
    accountCapital: Optional[float] = None,
) -> List[Zone]:
    incoming = dict(params or {})
    if accountCapital is not None:
        incoming["accountCapital"] = accountCapital
    config = settings(**incoming)
    zones = ZoneEngine(df_zone, **config).run()
    if not zones:
        return zones

    must_align = bool(require_aligned or config["requirePulseTrendAligned"])
    if not config["usePulseTrend"]:
        return [zone for zone in zones if zone.biasAligned] if must_align else zones

    rules = resolve_rules(zone_tf)
    pulse_rule = pulse_rule or rules["pulse"]
    pulse_tf = pulse_tf or rules["pulse_tf"]
    trend_rule = trend_rule or rules["trend"]
    trend_tf = trend_tf or rules["trend_tf"]

    # Use df_base when supplied; otherwise use zone bars as the resampling source.
    source = df_base if df_base is not None else df_zone
    if df_pulse is None:
        df_pulse = resample_ohlc(source, pulse_tf)
    if df_trend is None:
        df_trend = resample_ohlc(source, trend_tf)

    apply_pulse_trend(zones, df_pulse, df_trend, pulse_rule, trend_rule, pulse_tf, trend_tf)
    if must_align:
        zones = [zone for zone in zones if zone.biasAligned]
    return zones


def latest_active_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.state in ("Fresh", "Tested")]


def high_quality_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.isHQ]


def fresh_zones(zones: List[Zone]) -> List[Zone]:
    return [zone for zone in zones if zone.state == "Fresh" and zone.isFresh]


def tradable_zones(zones: List[Zone], require_aligned: bool = False) -> List[Zone]:
    result: List[Zone] = []
    for zone in zones:
        if zone.state not in ("Fresh", "Tested"):
            continue
        if not (zone.validDemand or zone.validSupply):
            continue
        if not zone.legOutPassesRR:
            continue
        if zone.entryBarIndex is None and zone.state != "Fresh":
            continue
        if require_aligned and not zone.biasAligned:
            continue
        result.append(zone)
    return result


def summarize_zones(zones: List[Zone]) -> pd.DataFrame:
    if not zones:
        return pd.DataFrame()
    rows = []
    for zone in zones:
        rows.append(
            {
                "timestamp": zone.timestamp,
                "pattern": zone.patternType,
                "category": zone.zoneCategory,
                "side": "Demand" if zone.isDemand else "Supply",
                "state": zone.state,
                "proximal": zone.proxVal,
                "distal": zone.distVal,
                "sl": zone.slVal,
                "tp": zone.tpVal,
                "risk_pct": zone.riskPct,
                "legOutRR": zone.legOutRR,
                "rr_ok": zone.legOutPassesRR,
                "engulf": zone.engulfOK,
                "engulf_ref": zone.engulfRefPattern,
                "rule1": zone.rule1OK,
                "rule2": zone.rule2OK,
                "rule3": zone.rule3OK,
                "rule4": zone.rule4OK,
                "score": zone.densityScore,
                "HQ": zone.isHQ,
                "pulse": zone.pulse,
                "trend": zone.trend,
                "aligned": zone.biasAligned,
                "entry_bar": zone.entryBarIndex,
                "entry_price": zone.entryPrice,
                "break_bar": zone.breakBarIndex,
            }
        )
    return pd.DataFrame(rows)
