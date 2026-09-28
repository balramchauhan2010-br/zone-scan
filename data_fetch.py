"""Chunked Yahoo Finance OHLCV downloads (no Streamlit dependency here -
caching is applied at the call site in app.py via st.cache_data, keyed to
the current 'candle bucket' so we don't re-hit Yahoo on every rerun)."""
import time
import warnings
from typing import Dict, List

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

CHUNK_SIZE = 40


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def download_many(tickers: List[str], interval: str, start: str, end: str = None,
                   period: str = None) -> Dict[str, pd.DataFrame]:
    """Batch-download OHLCV for many tickers. Returns {ticker: df[open,high,low,close,volume]}."""
    out: Dict[str, pd.DataFrame] = {}
    for chunk in _chunked(tickers, CHUNK_SIZE):
        df = None
        for attempt in range(3):
            try:
                kwargs = dict(interval=interval, progress=False, auto_adjust=True,
                              group_by="ticker", threads=True)
                if period is not None:
                    df = yf.download(chunk, period=period, **kwargs)
                else:
                    df = yf.download(chunk, start=start, end=end, **kwargs)
                break
            except Exception:
                time.sleep(1.5)
                df = None
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


def fetch_15m(tickers: List[str], lookback_days: int = 59) -> Dict[str, pd.DataFrame]:
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "15m", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def fetch_60m(tickers: List[str], lookback_days: int = 350) -> Dict[str, pd.DataFrame]:
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "60m", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def fetch_daily(tickers: List[str], lookback_days: int = 1100) -> Dict[str, pd.DataFrame]:
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    return download_many(tickers, "1d", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
