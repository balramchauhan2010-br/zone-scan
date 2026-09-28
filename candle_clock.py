"""NSE session-aware 'candle close' clock.

Purpose: give every timeframe a cache key that only changes exactly when
that timeframe's own candle actually closes - so Streamlit's caching can
skip re-downloading/re-scanning on every page interaction. This is what
keeps big timeframes (Daily/Weekly/Monthly) cheap: their bucket key only
changes once a day / once a week / once a month.

NSE cash session: Mon-Fri, 09:15 - 15:30 IST (holidays excluded below).
This is a reasonable approximation, not a certified exchange calendar -
update NSE_HOLIDAYS for future years as needed.
"""
from __future__ import annotations
import datetime as dt
from typing import Tuple

import pandas as pd

IST = "Asia/Kolkata"

MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)

# NSE trading holidays (weekday ones only matter here - weekend holidays
# are already non-trading days). Extend this list for future years.
NSE_HOLIDAYS = {
    # 2025
    dt.date(2025, 2, 26), dt.date(2025, 3, 14), dt.date(2025, 3, 31),
    dt.date(2025, 4, 10), dt.date(2025, 4, 14), dt.date(2025, 4, 18),
    dt.date(2025, 5, 1), dt.date(2025, 8, 15), dt.date(2025, 8, 27),
    dt.date(2025, 9, 5), dt.date(2025, 10, 2), dt.date(2025, 10, 21),
    dt.date(2025, 10, 22), dt.date(2025, 11, 5), dt.date(2025, 12, 25),
    # 2026 (weekday holidays only; a couple already fall on weekends)
    dt.date(2026, 1, 26), dt.date(2026, 3, 3), dt.date(2026, 3, 26),
    dt.date(2026, 3, 31), dt.date(2026, 4, 3), dt.date(2026, 4, 14),
    dt.date(2026, 5, 1), dt.date(2026, 5, 28), dt.date(2026, 6, 26),
    dt.date(2026, 9, 14), dt.date(2026, 10, 2), dt.date(2026, 10, 20),
    dt.date(2026, 11, 10), dt.date(2026, 11, 24), dt.date(2026, 12, 25),
}

# (base_minutes, slots_per_day, group_size) per timeframe.
# 15m-grid timeframes: 25 slots/day (09:15 .. 15:15).
# 60m-grid timeframes: 7 slots/day (09:15 .. 15:15, last slot only 15min wide).
TF_GRID = {
    "15m": (15, 25, 1),
    "30m": (15, 25, 2),
    "75m": (15, 25, 5),
    "1H": (60, 7, 1),
    "2H": (60, 7, 2),
    "4H": (60, 7, 4),
    "6H": (60, 7, 6),
}
INTRADAY_TFS = set(TF_GRID.keys())
DAILY_LIKE_TFS = {"Daily", "Weekly", "Monthly"}


def now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST)


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in NSE_HOLIDAYS


def previous_trading_day(d: dt.date) -> dt.date:
    d = d - dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def last_trading_day_on_or_before(d: dt.date) -> dt.date:
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def _open_close_dt(d: dt.date) -> Tuple[pd.Timestamp, pd.Timestamp]:
    o = pd.Timestamp.combine(d, MARKET_OPEN).tz_localize(IST)
    c = pd.Timestamp.combine(d, MARKET_CLOSE).tz_localize(IST)
    return o, c


def market_status(now: pd.Timestamp = None) -> dict:
    now = now or now_ist()
    today = now.date()
    if is_trading_day(today):
        o, c = _open_close_dt(today)
        if o <= now < c:
            return {"open": True, "session_date": today, "opens_at": o, "closes_at": c}
    return {"open": False, "session_date": today, "opens_at": None, "closes_at": None}


def last_closed_bucket(tf: str, now: pd.Timestamp = None) -> pd.Timestamp:
    """Timestamp (bar START, matching yfinance's own bar labelling) of the
    most recently FULLY CLOSED candle for this timeframe, right now."""
    now = now or now_ist()

    if tf == "Daily":
        d = today_or_prev_fully_closed(now)
        return pd.Timestamp(d)
    if tf == "Weekly":
        d = today_or_prev_fully_closed(now)
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if tf == "Monthly":
        d = today_or_prev_fully_closed(now)
        return pd.Timestamp(year=d.year, month=d.month, day=1)

    base, slots, group = TF_GRID[tf]
    today = now.date()
    closed_today = 0
    if is_trading_day(today):
        o, _ = _open_close_dt(today)
        if now >= o:
            elapsed_min = (now - o).total_seconds() / 60.0
            closed_today = min(slots, int(elapsed_min // base))

    grouped_closed_today = closed_today // group
    if grouped_closed_today > 0:
        bar_index = grouped_closed_today - 1
        bucket_date = today
    else:
        bucket_date = previous_trading_day(today) if is_trading_day(today) else last_trading_day_on_or_before(today - dt.timedelta(days=1))
        bar_index = (slots // group) - 1

    o, _ = _open_close_dt(bucket_date)
    return o + dt.timedelta(minutes=bar_index * group * base)


def today_or_prev_fully_closed(now: pd.Timestamp) -> dt.date:
    today = now.date()
    if is_trading_day(today):
        _, c = _open_close_dt(today)
        if now >= c:
            return today
    return previous_trading_day(today) if is_trading_day(today) else last_trading_day_on_or_before(today - dt.timedelta(days=1))


def next_close_eta(tf: str, now: pd.Timestamp = None) -> str:
    """Human-readable string describing when the NEXT candle close happens."""
    now = now or now_ist()
    status = market_status(now)
    if tf in DAILY_LIKE_TFS:
        if status["open"]:
            return f"Market band ke andar - is {tf} candle ka close market band hone par (~{MARKET_CLOSE.strftime('%H:%M')} IST) ya period end par hoga"
        return "Market band hai - agla open session shuru hone ka wait"
    if not status["open"]:
        return "Market band hai - agla candle NSE khulne ke baad banega"
    base, slots, group = TF_GRID[tf]
    o, _ = _open_close_dt(status["session_date"])
    elapsed_min = (now - o).total_seconds() / 60.0
    closed_today = min(slots, int(elapsed_min // base))
    next_group_boundary_slots = ((closed_today // group) + 1) * group
    next_group_boundary_slots = min(next_group_boundary_slots, slots)
    close_time = o + dt.timedelta(minutes=next_group_boundary_slots * base)
    return f"~{close_time.strftime('%H:%M')} IST par agla {tf} candle close hoga"
