"""Timeframe construction helpers.

Native intervals fetched from Yahoo Finance: 1d, 60m, 15m.
Everything else is built by resampling, grouped PER TRADING DAY starting
at the session's first bar (09:15 IST) - NOT naive calendar-clock
resampling - because NSE's 09:15-15:30 session does not divide evenly
into clean clock-aligned blocks and a plain pandas resample('2H') (etc.)
would incorrectly straddle the overnight/weekend gap between sessions.

  30m  = group of 2 consecutive 15m bars   (15m grid has 25 slots/day)
  75m  = group of 5 consecutive 15m bars
  2H   = group of 2 consecutive 60m bars   (60m grid has 7 slots/day)
  4H   = group of 4 consecutive 60m bars
  6H   = group of 6 consecutive 60m bars
  Weekly/Monthly = resampled from Daily bars.
"""
import pandas as pd


def resample_session_n(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Group every N consecutive intraday bars, per trading day."""
    if df.empty:
        return df.copy()
    work = df.copy()
    work["_day"] = work.index.date
    work["_posn"] = work.groupby("_day").cumcount()
    work["_bin"] = work["_posn"] // n
    work["_ts"] = work.index

    grouped = work.groupby(["_day", "_bin"], sort=True)
    out = grouped.agg(
        timestamp=("_ts", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    out = out.set_index("timestamp").sort_index()
    out.index.name = None
    return out[["open", "high", "low", "close", "volume"]]


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.resample("ME").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])
