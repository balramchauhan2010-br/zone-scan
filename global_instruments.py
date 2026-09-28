"""Optional 'Top Global Instruments' + a small live 'Market Watch' ticker-tape.

These are NOT part of the NSE F&O universe. They are purely additive:
- GLOBAL_INSTRUMENTS: an opt-in list a user can ADD on top of the normal
  market-cap NSE stock universe, so the SAME unchanged zone_core.py engine
  can also flag supply/demand zones on major global benchmarks that F&O
  traders track for context (Dollar Index, Crude, Gold, world indices,
  GIFT Nifty, etc).
- MARKET_WATCH: a fixed set of 6 instruments always shown as a small live
  price/%-change ticker-tape at the top of the app (GIFT Nifty, Nifty 50,
  Bank Nifty, USD/INR, Gold, Crude).

Yahoo Finance data quality/availability varies a lot across asset classes -
some of these (index-futures/GIFT-Nifty proxies) may have thin or missing
intraday history; the scanner silently skips anything with too few bars
(exact same graceful behaviour as any NSE stock with insufficient data) -
this is NOT a zone_core.py logic change, just how missing data is handled.

NOTE on GIFT NIFTY: a genuine continuous GIFT Nifty (NSE IX) feed is not
available through Yahoo Finance, so it is shown here as a PROXY using the
regular NSE Nifty 50 spot index (^NSEI) - clearly labelled below and in the
UI/README so it isn't mistaken for the real GIFT Nifty futures price.
"""
from typing import Dict, List, Optional

GLOBAL_INSTRUMENTS = [
    {"label": "DXY - US Dollar Index", "yahoo": "DX-Y.NYB", "tv": "TVC:DXY"},
    {"label": "USDINR - USD/INR", "yahoo": "USDINR=X", "tv": "FX_IDC:USDINR"},
    {"label": "TLT - iShares 20+Y US Treasury Bond ETF", "yahoo": "TLT", "tv": "NASDAQ:TLT"},
    {"label": "US10Y - US 10-Year Treasury Yield", "yahoo": "^TNX", "tv": "TVC:US10Y"},
    {"label": "XAUUSD - Gold / US Dollar", "yahoo": "GC=F", "tv": "TVC:GOLD"},
    {"label": "XAGUSD - Silver / US Dollar", "yahoo": "SI=F", "tv": "TVC:SILVER"},
    {"label": "SPOTCRUDE - WTI Crude Oil", "yahoo": "CL=F", "tv": "TVC:USOIL"},
    {"label": "US30 - Dow Jones Industrial Average", "yahoo": "^DJI", "tv": "TVC:DJI"},
    {"label": "US500 - S&P 500", "yahoo": "^GSPC", "tv": "TVC:SPX"},
    {"label": "000001 - SSE Composite (Shanghai)", "yahoo": "000001.SS", "tv": "SSE:000001"},
    {"label": "XIN9 - FTSE China A50 Index", "yahoo": "XIN9.FGI", "tv": "TVC:XIN9"},
    {"label": "JP225 - Nikkei 225", "yahoo": "^N225", "tv": "TVC:NI225"},
    {"label": "NIFTY1! - Nifty 50 / GIFT NIFTY Futures (proxy: Nifty 50 spot)",
     "yahoo": "^NSEI", "tv": "NSE:NIFTY1!"},
    {"label": "FTSE100 - UK FTSE 100", "yahoo": "^FTSE", "tv": "TVC:UKX"},
    {"label": "DAX - Germany DAX Index", "yahoo": "^GDAXI", "tv": "XETR:DAX"},
]

# Fixed 6-instrument live ticker-tape shown at the top of the app.
MARKET_WATCH = [
    {"label": "GIFT NIFTY", "yahoo": "^NSEI", "tv": "NSE:NIFTY1!"},
    {"label": "NIFTY 50", "yahoo": "^NSEI", "tv": "NSE:NIFTY"},
    {"label": "BANK NIFTY", "yahoo": "^NSEBANK", "tv": "NSE:BANKNIFTY"},
    {"label": "USD/INR", "yahoo": "USDINR=X", "tv": "FX_IDC:USDINR"},
    {"label": "XAUUSD", "yahoo": "GC=F", "tv": "TVC:GOLD"},
    {"label": "SPOTCRUDE", "yahoo": "CL=F", "tv": "TVC:USOIL"},
]

YAHOO_TO_META: Dict[str, dict] = {item["yahoo"]: item for item in GLOBAL_INSTRUMENTS}


def labels() -> List[str]:
    return [item["label"] for item in GLOBAL_INSTRUMENTS]


def label_to_yahoo(label: str) -> Optional[str]:
    for item in GLOBAL_INSTRUMENTS:
        if item["label"] == label:
            return item["yahoo"]
    return None
