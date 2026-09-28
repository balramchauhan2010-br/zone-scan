"""Chunked Yahoo Finance OHLCV downloads.

Hardened for cloud hosting (Streamlit Community Cloud etc.), where Yahoo
Finance is known to throttle/block requests from datacenter IP ranges much
more aggressively than a normal home connection:

  - Uses a curl_cffi session with Chrome TLS/browser impersonation (the
    documented fix for yfinance requests being silently blocked on cloud
    IPs) instead of yfinance's default requests session.
  - SHORT per-request timeout + only 1 retry with a short backoff, so a
    blocked/unreachable request FAILS FAST instead of hanging for minutes
    (the old code allowed up to ~3 x 20s x 3-retries per chunk, which could
    add up to many minutes of apparent "stuck" spinner on a bad network).
  - Optional progress_cb(done, total, label) callback so the UI can show
    real per-chunk progress instead of one frozen spinner.

None of this touches zone_core.py's rules/logic - purely a data-plumbing
robustness/speed fix.
"""
import time
import warnings
from typing import Callable, Dict, List, Optional

import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as cffi_requests
    _SESSION = cffi_requests.Session(impersonate="chrome")
except Exception:
    _SESSION = None  # falls back to yfinance's default session

warnings.filterwarnings("ignore")

CHUNK_SIZE = 40
REQUEST_TIMEOUT = 10       # seconds per attempt - fail fast, don't hang the UI
MAX_ATTEMPTS = 2           # 1 retry only
RETRY_BACKOFF = 0.7        # seconds


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def download_many(tickers: List[str], interval: str, start: str, end: str = None,
                   period: str = None, label: str = "",
                   progress_cb: Optional[Callable[[int, int, str], None]] = None
                   ) -> Dict[str, pd.DataFrame]:
    """Batch-download OHLCV for many tickers. Returns {ticker: df[open,high,low,close,volume]}."""
    out: Dict[str, pd.DataFrame] = {}
    chunks = list(_chunked(tickers, CHUNK_SIZE))
    total = len(chunks)

    for ci, chunk in enumerate(chunks):
        df = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                kwargs = dict(interval=interval, progress=False, auto_adjust=True,
                              group_by="ticker", threads=True, timeout=REQUEST_TIMEOUT)
                if _SESSION is not None:
                    kwargs["session"] = _SESSION
                if period is not None:
                    df = yf.download(chunk, period=period, **kwargs)
                else:
                    df = yf.download(chunk, start=start, end=end, **kwargs)
                if df is not None and not df.empty:
                    break
            except Exception:
                df = None
            time.sleep(RETRY_BACKOFF)

        if progress_cb is not None:
            progress_cb(ci + 1, total, label)

        if df is None or df.empty:
            continue
        top = set(df.columns.get_level_values(0))
        for t in chunk:
            if t not in top:
                continue
            sub = df[t].dropna(how="all")
            sub = sub.rename(columns=str.lower)
            sub = sub.dropna(subset=["open", "high", "low", "close"])
            if sub.empty:
                continue
            out[t] = sub[["open", "high", "low", "close", "volume"]]
    return out


def fetch_15m(tickers: List[str], lookback_days: int = 59, progress_cb=None) -> Dict[str, pd.DataFrame]:
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "15m", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                          label="15m", progress_cb=progress_cb)


def fetch_5m(tickers: List[str], lookback_days: int = 59, progress_cb=None) -> Dict[str, pd.DataFrame]:
    """Native 5-minute bars - Yahoo's hard limit is ~60 days, same as 15m."""
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "5m", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                          label="5m", progress_cb=progress_cb)


def fetch_1m(tickers: List[str], lookback_days: int = 6, progress_cb=None) -> Dict[str, pd.DataFrame]:
    """Native 1-minute bars - Yahoo's hard limit is ~7 days, so only used
    when a user explicitly types a custom timeframe that needs 1m granularity
    (e.g. '3m'). Short lookback is a Yahoo limitation, not a bug."""
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "1m", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                          label="1m", progress_cb=progress_cb)


def fetch_60m(tickers: List[str], lookback_days: int = 350, progress_cb=None) -> Dict[str, pd.DataFrame]:
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "60m", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                          label="1H", progress_cb=progress_cb)


def fetch_daily(tickers: List[str], lookback_days: int = 1100, progress_cb=None) -> Dict[str, pd.DataFrame]:
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "1d", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                          label="Daily", progress_cb=progress_cb)


def fetch_market_watch_quotes(yahoo_tickers: List[str]) -> Dict[str, tuple]:
    """Lightweight live-price + %-change fetch for the top ticker-tape
    (last 2 daily closes -> works uniformly across stocks/indices/forex/
    commodities without needing per-asset-class special casing)."""
    uniq = list(dict.fromkeys(yahoo_tickers))
    data = download_many(uniq, "1d", None, None, period="5d", label="watch")
    out = {}
    for t, df in data.items():
        if df is None or df.empty or len(df) < 2:
            continue
        try:
            last = float(df["close"].iloc[-1])
            prev = float(df["close"].iloc[-2])
            chg = (last - prev) / prev * 100.0 if prev else 0.0
            out[t] = (last, chg)
        except Exception:
            continue
    return out

