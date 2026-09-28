"""NSE F&O stock-universe list, with a live-fetch + bundled-fallback design.

NSE's website frequently blocks non-browser / datacenter IPs (which is
exactly what Streamlit Cloud runs on), so a live fetch will often fail
once deployed. In that case we silently fall back to the bundled JSON
snapshot (fno_stocks_fallback.json) - update it periodically by running
`python fno_universe.py --refresh` locally (from a normal home/office
connection) and committing the refreshed file to the repo.
"""
import json
import time
from pathlib import Path
from typing import List, Tuple

import requests

FALLBACK_PATH = Path(__file__).parent / "fno_stocks_fallback.json"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_live() -> List[str]:
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.get("https://www.nseindia.com/", timeout=8)
    time.sleep(0.5)
    resp = session.get(
        "https://www.nseindia.com/api/underlying-information",
        headers={**_HEADERS, "Accept": "application/json",
                 "Referer": "https://www.nseindia.com/market-data/equity-derivatives-watch"},
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    symbols = [x["symbol"] for x in data["data"]["UnderlyingList"]]
    if len(symbols) < 50:
        raise ValueError("Suspiciously small F&O list returned - rejecting")
    return sorted(symbols)


def load_fallback() -> List[str]:
    with open(FALLBACK_PATH) as f:
        return sorted(json.load(f))


def get_fno_symbols(try_live: bool = True) -> Tuple[List[str], str]:
    """Returns (symbols, source_label)."""
    if try_live:
        try:
            symbols = fetch_live()
            return symbols, "live (nseindia.com)"
        except Exception:
            pass
    return load_fallback(), f"bundled fallback ({FALLBACK_PATH.name})"


def to_yahoo_tickers(symbols: List[str]) -> List[str]:
    return [s + ".NS" for s in symbols]


# Maps our internal timeframe labels to TradingView's `interval` query-param
# values, so the chart link opens directly on the SAME timeframe as the
# scanned zone (instead of always opening on TradingView's default/last-used
# interval). 75m/6H aren't native TradingView presets but the numeric-minute
# form still works for most logged-in TradingView sessions; harmless if not.
TF_TO_TV_INTERVAL = {
    "15m": "15", "30m": "30", "75m": "75",
    "1H": "60", "2H": "120", "4H": "240", "6H": "360",
    "Daily": "D", "Weekly": "W", "Monthly": "M",
}


def tradingview_url(symbol: str, tf: str = None) -> str:
    tv_symbol = symbol.replace("&", "_").replace("-", "_")
    url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{tv_symbol}"
    interval = TF_TO_TV_INTERVAL.get(tf)
    if interval:
        url += f"&interval={interval}"
    if tf:
        # Harmless extra param (TradingView ignores unknown ones) - lets the
        # UI extract a clean display label for the "Timeframe" link column.
        url += f"&tf={tf}"
    return url


if __name__ == "__main__":
    import sys
    if "--refresh" in sys.argv:
        symbols = fetch_live()
        with open(FALLBACK_PATH, "w") as f:
            json.dump(symbols, f, indent=2)
        print(f"Refreshed fallback list with {len(symbols)} symbols -> {FALLBACK_PATH}")
    else:
        syms, src = get_fno_symbols()
        print(f"{len(syms)} symbols from {src}")
