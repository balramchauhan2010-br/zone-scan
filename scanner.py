"""Builds per-timeframe OHLCV frames and runs zone_core over the whole
NSE F&O universe (+ optional global instruments), returning a tidy table
of currently LIVE zones.

Custom timeframes: any string beyond the 10 presets in TF_LIST is accepted
as long as it normalises to '<N>m' or '<N>H' (see normalize_tf) - built by
grouping native 1m/5m/15m/60m bars per trading day, the exact same
session-aware way the existing 30m/75m/2H/4H/6H presets already work
(see candle_clock.parse_custom_tf). zone_core.py itself is never touched.
"""
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import zone_core as zc
import candle_clock as cc
from resample_utils import resample_session_n, resample_weekly, resample_monthly
from fno_universe import chart_url

TF_LIST = ["15m", "30m", "75m", "1H", "2H", "4H", "6H", "Daily", "Weekly", "Monthly"]
MIN_BARS = 25

_CUSTOM_TF_RE = re.compile(r"^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$", re.IGNORECASE)


def normalize_tf(raw: str) -> Optional[str]:
    """Turns free-typed user input ('3 min', '8hr', '45M') into the
    canonical form ('3m', '8H', '45m') used everywhere else in the app.
    Returns None if it isn't a recognised preset, or if it doesn't
    parse, or if the requested bar would span MORE than a single
    trading day (~6h15m session) - which this per-day grouping model
    (same one the 30m/75m/2H/4H/6H presets already use) can't build
    sensibly; use Weekly/Monthly for multi-day bars instead."""
    if raw is None:
        return None
    tf = raw.strip()
    if tf in TF_LIST:
        return tf
    m = _CUSTOM_TF_RE.match(tf)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    candidate = f"{n}H" if unit.startswith("h") else f"{n}m"
    parsed = cc.parse_custom_tf(candidate)
    if not parsed or parsed["group"] > parsed["slots"]:
        return None
    return candidate


def base_dataset_for_tf(tf: str) -> str:
    """Which native Yahoo granularity a (possibly custom) timeframe is
    built from: '1m' / '5m' / '15m' / '60m' / 'daily'."""
    if tf in ("Daily", "Weekly", "Monthly"):
        return "daily"
    if tf in cc.TF_GRID:
        base = cc.TF_GRID[tf][0]
    else:
        parsed = cc.parse_custom_tf(tf)
        if not parsed:
            raise ValueError(f"Unrecognised timeframe: {tf}")
        base = parsed["base"]
    return {1: "1m", 5: "5m", 15: "15m", 60: "60m"}[base]


def group_size_for_tf(tf: str) -> int:
    if tf in cc.TF_GRID:
        return cc.TF_GRID[tf][2]
    parsed = cc.parse_custom_tf(tf)
    return parsed["group"] if parsed else 1


_PRESET_MINUTES = {"15m": 15, "30m": 30, "75m": 75, "1H": 60, "2H": 120, "4H": 240,
                    "6H": 360, "Daily": 1440, "Weekly": 10080, "Monthly": 43200}


def tf_minutes(tf: str) -> int:
    """Approximate duration in minutes - used only to sort timeframes
    (presets + any custom ones) into a sensible chronological order."""
    if tf in _PRESET_MINUTES:
        return _PRESET_MINUTES[tf]
    parsed = cc.parse_custom_tf(tf)
    if parsed:
        return parsed["base"] * parsed["group"]
    return 10 ** 9


def build_timeframe_frames(tf: str, raw_by_base: Dict[str, Dict[str, pd.DataFrame]]) -> Dict[str, pd.DataFrame]:
    """raw_by_base keys: '1m', '5m', '15m', '60m', 'daily' (only the ones
    actually needed are populated by the caller)."""
    if tf == "Daily":
        return raw_by_base.get("daily", {})
    if tf == "Weekly":
        return {s: resample_weekly(df) for s, df in raw_by_base.get("daily", {}).items()}
    if tf == "Monthly":
        return {s: resample_monthly(df) for s, df in raw_by_base.get("daily", {}).items()}

    base = base_dataset_for_tf(tf)
    group = group_size_for_tf(tf)
    raw = raw_by_base.get(base, {})
    if group <= 1:
        return raw
    return {s: resample_session_n(df, group) for s, df in raw.items()}


def scan_universe(tf: str, frames: Dict[str, pd.DataFrame], params: dict,
                   states: Optional[List[str]] = None) -> pd.DataFrame:
    states = states or ["Fresh", "Tested"]
    rows = []
    for symbol, df in frames.items():
        if df is None or len(df) < MIN_BARS:
            continue
        try:
            zones = zc.scan_zones(df, params=params)
        except Exception:
            continue
        active = [z for z in zones if z.state in states]
        if not active:
            continue
        current_price = float(df["close"].iloc[-1])
        last_bar_time = df.index[-1]
        for z in active:
            distance = current_price - z.proxVal
            distance_pct = (distance / current_price * 100.0) if current_price else np.nan
            risk = abs(z.proxVal - z.slVal)
            reward = abs(z.tpVal - z.proxVal)
            rr = reward / risk if risk else np.nan
            rows.append({
                # Interval is embedded in the link itself (and resolved
                # correctly for global instruments too), so opening the
                # chart from ANY row lands on the SAME timeframe as the zone.
                "Symbol": chart_url(symbol, tf=tf),
                "Timeframe": tf,
                "Ticker": symbol,
                "Direction": "DEMAND (Buy Zone)" if z.isDemand else "SUPPLY (Sell Zone)",
                "Pattern": z.patternType,
                "State": z.state,
                "Entry (Proximal)": round(z.proxVal, 2),
                "Stop Loss (Distal+Buffer)": round(z.slVal, 2),
                "Target (RR set)": round(z.tpVal, 2),
                "Risk:Reward": round(rr, 2) if np.isfinite(rr) else np.nan,
                "Current Price": round(current_price, 2),
                "Distance from Entry": round(distance, 2),
                "Distance %": round(distance_pct, 2),
                "Price Position": ("Above zone - price girne ka wait" if (z.isDemand and distance > 0)
                                     else "Below zone - price girna already ho chuka / broken risk" if (z.isDemand and distance < 0)
                                     else "Below zone - price uthne ka wait" if (not z.isDemand and distance < 0)
                                     else "Above zone - already up, breakout risk" if (not z.isDemand and distance > 0)
                                     else "Inside zone (at entry)"),
                "HQ Zone (Rule3 Boring-Colour)": z.isHQ,
                "White Area OK (Rule4)": z.whiteAreaOK,
                "Base Count": z.baseCount,
                "Touch Count": z.touchCount,
                "Zone Created": z.timestamp,
                "Last Bar Time": last_bar_time,
            })
    cols = [
        "Symbol", "Timeframe", "Ticker", "Direction", "Pattern", "State", "Entry (Proximal)",
        "Stop Loss (Distal+Buffer)", "Target (RR set)", "Risk:Reward", "Current Price",
        "Distance from Entry", "Distance %", "Price Position", "HQ Zone (Rule3 Boring-Colour)",
        "White Area OK (Rule4)", "Base Count", "Touch Count", "Zone Created", "Last Bar Time",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)[cols]
    out = out.sort_values("Distance %", key=lambda s: s.abs())
    return out.reset_index(drop=True)


def nearest_zone_for_symbol(df: pd.DataFrame, params: dict,
                             states: Optional[List[str]] = None) -> Optional[dict]:
    """Runs the SAME unchanged zone_core.scan_zones() on a single symbol's
    OHLC frame and returns just the ONE zone nearest to the current price -
    used for the small 'NIFTY50 nearest zone' badge."""
    states = states or ["Fresh", "Tested"]
    if df is None or len(df) < MIN_BARS:
        return None
    try:
        zones = zc.scan_zones(df, params=params)
    except Exception:
        return None
    active = [z for z in zones if z.state in states]
    if not active:
        return None
    current_price = float(df["close"].iloc[-1])
    nearest = min(active, key=lambda z: abs(current_price - z.proxVal))
    distance = current_price - nearest.proxVal
    distance_pct = (distance / current_price * 100.0) if current_price else 0.0
    return {
        "direction": "DEMAND" if nearest.isDemand else "SUPPLY",
        "entry": round(nearest.proxVal, 2),
        "current": round(current_price, 2),
        "distance_pct": round(distance_pct, 2),
        "state": nearest.state,
    }
