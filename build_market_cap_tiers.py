"""Offline helper: fetch market cap for every NSE F&O stock (via yfinance)
and bundle a rank-based market-cap tier classification as JSON, so the live
Streamlit app can offer a fast "scan a lighter/heavier universe" filter
WITHOUT hitting any live API at runtime (NSE's website blocks datacenter
IPs unpredictably - this keeps the tiering reliable and instant).

Run this occasionally (e.g. monthly) from a normal connection and commit
the refreshed market_cap_tiers.json to the repo:

    python build_market_cap_tiers.py
"""
import json
import concurrent.futures as cf
from pathlib import Path

import yfinance as yf

from fno_universe import get_fno_symbols, to_yahoo_tickers

OUT_PATH = Path(__file__).parent / "market_cap_tiers.json"


def fetch_one(ticker: str):
    try:
        fi = yf.Ticker(ticker).fast_info
        cap = fi.get("marketCap")
        return ticker, float(cap) if cap else None
    except Exception:
        return ticker, None


def main():
    symbols, src = get_fno_symbols(try_live=True)
    tickers = to_yahoo_tickers(symbols)
    print(f"Universe: {len(tickers)} tickers (source: {src})")

    caps = {}
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for ticker, cap in ex.map(fetch_one, tickers):
            caps[ticker] = cap

    ok = {t: c for t, c in caps.items() if c}
    ranked = sorted(ok.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ranked)
    tiers = {}
    for rank, (ticker, cap) in enumerate(ranked, start=1):
        if rank <= 50:
            tier = "Large Cap (Top 50)"
        elif rank <= 100:
            tier = "Large-Mid Cap (51-100)"
        elif rank <= 200:
            tier = "Mid Cap (101-200)"
        else:
            tier = "Small Cap (200+)"
        tiers[ticker] = {"rank": rank, "market_cap": cap, "tier": tier}

    failed = sorted(set(tickers) - set(ok.keys()))
    for t in failed:
        tiers[t] = {"rank": None, "market_cap": None, "tier": "Unknown"}

    with open(OUT_PATH, "w") as f:
        json.dump(tiers, f, indent=2)
    print(f"Wrote {len(tiers)} entries ({len(failed)} unknown) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
