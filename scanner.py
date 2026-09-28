"""Builds per-timeframe OHLCV frames and runs zone_core over the whole
NSE F&O universe, returning a tidy table of currently LIVE zones."""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import zone_core as zc
from resample_utils import resample_session_n, resample_weekly, resample_monthly
from fno_universe import tradingview_url

TF_LIST = ["15m", "30m", "75m", "1H", "2H", "4H", "6H", "Daily", "Weekly", "Monthly"]
MIN_BARS = 25


def build_timeframe_frames(tf: str, raw15: Dict[str, pd.DataFrame], raw60: Dict[str, pd.DataFrame],
                            raw_daily: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    if tf == "15m":
        return raw15
    if tf == "30m":
        return {s: resample_session_n(df, 2) for s, df in raw15.items()}
    if tf == "75m":
        return {s: resample_session_n(df, 5) for s, df in raw15.items()}
    if tf == "1H":
        return raw60
    if tf == "2H":
        return {s: resample_session_n(df, 2) for s, df in raw60.items()}
    if tf == "4H":
        return {s: resample_session_n(df, 4) for s, df in raw60.items()}
    if tf == "6H":
        return {s: resample_session_n(df, 6) for s, df in raw60.items()}
    if tf == "Daily":
        return raw_daily
    if tf == "Weekly":
        return {s: resample_weekly(df) for s, df in raw_daily.items()}
    if tf == "Monthly":
        return {s: resample_monthly(df) for s, df in raw_daily.items()}
    raise ValueError(f"Unknown timeframe {tf}")


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
                "Symbol": tradingview_url(symbol.replace(".NS", "")),
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
                "Timeframe": tf,
            })
    if not rows:
        return pd.DataFrame(columns=[
            "Symbol", "Ticker", "Direction", "Pattern", "State", "Entry (Proximal)",
            "Stop Loss (Distal+Buffer)", "Target (RR set)", "Risk:Reward", "Current Price",
            "Distance from Entry", "Distance %", "Price Position", "HQ Zone (Rule3 Boring-Colour)",
            "White Area OK (Rule4)", "Base Count", "Touch Count", "Zone Created", "Last Bar Time",
            "Timeframe",
        ])
    out = pd.DataFrame(rows)
    out = out.sort_values("Distance %", key=lambda s: s.abs())
    return out.reset_index(drop=True)
