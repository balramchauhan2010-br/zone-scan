"""NSE F&O stock-universe list, with a live-fetch + bundled-fallback design.

NSE's website frequently blocks non-browser / datacenter IPs (which is
exactly what Streamlit Cloud runs on), so a live fetch will often fail
once deployed. In that case we silently fall back to the bundled JSON
snapshot (fno_stocks_fallback.json) - update it periodically by running
`python fno_universe.py --refresh` locally (from a normal home/office
connection) and committing the refreshed file to the repo.
"""
import json
import re
import time
from pathlib import Path
from typing import List, Tuple
from urllib.parse import quote

import requests

FALLBACK_PATH = Path(__file__).parent / "fno_stocks_fallback.json"

# ---- EMBEDDED 210-symbol snapshot (safety net) --------------------------
# Deploy par agar JSON file missing / unreadable ho, to universe 0 ho jata hai
# ("All (0)" + koi zone nahi). Ye embedded list wo kabhi hone nahi deti.
_EMBEDDED_FNO = (
    "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS",
    "ADANIPOWER", "ALKEM", "AMBER", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP",
    "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATHERENERG", "AUBANK", "AUROPHARMA",
    "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG", "BAJFINANCE", "BANDHANBNK",
    "BANKBARODA", "BANKINDIA", "BDL", "BEL", "BHARATFORG", "BHARTIARTL", "BHEL",
    "BIOCON", "BLUESTARCO", "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "CAMS", "CANBK",
    "CDSL", "CGPOWER", "CHOLAFIN", "CIPLA", "COALINDIA", "COCHINSHIP", "COFORGE",
    "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND", "DABUR", "DELHIVERY", "DIVISLAB",
    "DIXON", "DLF", "DMART", "DRREDDY", "EICHERMOT", "ETERNAL", "FEDERALBNK",
    "FORCEMOT", "FORTIS", "GAIL", "GLENMARK", "GMRAIRPORT", "GODFRYPHLP", "GODREJCP",
    "GODREJPROP", "GRASIM", "GVT&D", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDPETRO", "HINDUNILVR", "HINDZINC",
    "HYUNDAI", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX",
    "INDHOTEL", "INDIANB", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "INOXWIND",
    "IOC", "IREDA", "IRFC", "ITC", "JINDALSTEL", "JIOFIN", "JSWENERGY", "JSWSTEEL",
    "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI", "KFINTECH", "KOTAKBANK", "KPITTECH",
    "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LT", "LTF", "LTM", "LUPIN", "M&M",
    "MAHABANK", "MANAPPURAM", "MANKIND", "MARICO", "MARUTI", "MAXHEALTH", "MAZDOCK",
    "MCX", "MFSL", "MOTHERSON", "MOTILALOFS", "MPHASIS", "MUTHOOTFIN", "NAM-INDIA",
    "NATIONALUM", "NAUKRI", "NBCC", "NESTLEIND", "NHPC", "NMDC", "NTPC", "NYKAA",
    "OBEROIRLTY", "OFSS", "OIL", "ONGC", "PAGEIND", "PATANJALI", "PAYTM", "PERSISTENT",
    "PETRONET", "PFC", "PGEL", "PHOENIXLTD", "PIDILITIND", "PIIND", "PNB", "PNBHOUSING",
    "POLICYBZR", "POLYCAB", "POWERGRID", "POWERINDIA", "PREMIERENE", "PRESTIGE",
    "RADICO", "RBLBANK", "RECLTD", "RELIANCE", "RVNL", "SAGILITY", "SAIL", "SBICARD",
    "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SOLARINDS", "SONACOMS",
    "SRF", "SUNPHARMA", "SUPREMEIND", "SUZLON", "SWIGGY", "TATACONSUM", "TATAELXSI",
    "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TIINDIA", "TITAN", "TMPV", "TORNTPHARM",
    "TRENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UNITDSPR", "UNOMINDA", "UPL",
    "VBL", "VEDL", "VMM", "VOLTAS", "WAAREEENER", "WIPRO", "YESBANK", "ZYDUSLIFE"
)

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
    """Embedded list pehle, phir JSON file.  Kabhi empty nahi lautaate."""
    try:
        embedded = sorted({str(x).strip().upper() for x in _EMBEDDED_FNO if str(x).strip()})
        if embedded:
            return embedded
    except Exception:
        pass
    try:
        with open(FALLBACK_PATH) as f:
            return sorted(json.load(f))
    except Exception:
        return []


def get_fno_symbols(try_live: bool = True) -> Tuple[List[str], str]:
    """Returns (symbols, source_label)."""
    if try_live:
        try:
            symbols = fetch_live()
            if len(symbols) >= 50:
                return symbols, "live (nseindia.com)"
        except Exception:
            pass
    fb = load_fallback()
    if not fb:                       # aakhiri safety-net
        fb = sorted({str(x).strip().upper() for x in _EMBEDDED_FNO if str(x).strip()})
    return fb, f"bundled fallback ({len(fb)} symbols)"


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


_CUSTOM_TF_RE = re.compile(r"^(\d+)(m|H)$")


def _tv_interval_for(tf: str) -> str:
    """Works for both preset timeframes AND any custom user-typed one
    (e.g. '5m', '45m', '3H') so the chart link always opens on the exact
    same timeframe as the scanned zone."""
    if not tf:
        return None
    if tf in TF_TO_TV_INTERVAL:
        return TF_TO_TV_INTERVAL[tf]
    m = _CUSTOM_TF_RE.match(tf.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return str(n if unit == "m" else n * 60)


def tradingview_url(symbol: str, tf: str = None) -> str:
    tv_symbol = symbol.replace("&", "_").replace("-", "_")
    url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{tv_symbol}"
    interval = _tv_interval_for(tf)
    if interval:
        url += f"&interval={interval}"
    if tf:
        # Harmless extra param (TradingView ignores unknown ones) - lets the
        # UI extract a clean display label for the "Timeframe" link column.
        url += f"&tf={tf}"
    return url


def chart_url(ticker: str, tf: str = None) -> str:
    """Generalised chart-link builder: NSE F&O stocks get the usual
    NSE:<SYMBOL> link; any 'Global Instrument' ticker (added via the
    optional universe add-on) gets its own correct TradingView
    exchange:symbol instead (e.g. TVC:DXY, FX_IDC:USDINR, TVC:GOLD)."""
    try:
        import global_instruments as _gi
        meta = _gi.YAHOO_TO_META.get(ticker)
    except Exception:
        meta = None
    if meta:
        # keep '!' un-escaped (used by continuous-futures symbols like
        # NIFTY1!) so the LinkColumn's display-text regex shows it cleanly
        url = f"https://www.tradingview.com/chart/?symbol={quote(meta['tv'], safe='!')}"
    else:
        clean = ticker.replace(".NS", "").replace("&", "_").replace("-", "_")
        url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean}"
    interval = _tv_interval_for(tf)
    if interval:
        url += f"&interval={interval}"
    if tf:
        url += f"&tf={quote(str(tf), safe='')}"
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
