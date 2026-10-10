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

NOTE on GIFT NIFTY: TradingView link = NSEIX:NIFTY1! (NSE IX GIFT Nifty futures).
A genuine continuous GIFT Nifty price feed is not available through Yahoo Finance
or Dhan, so the price is a PROXY (NIFTY 50 spot, ^NSEI) and is labelled as such.
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
    {"label": "GIFT NIFTY - NSE IX GIFT Nifty Futures (proxy: Nifty 50 spot)",
     "yahoo": "^NSEI", "tv": "NSEIX:NIFTY1!"},
    {"label": "FTSE100 - UK FTSE 100", "yahoo": "^FTSE", "tv": "TVC:UKX"},
    {"label": "DAX - Germany DAX Index", "yahoo": "^GDAXI", "tv": "XETR:DAX"},
    # Commodities / currencies / crypto (Top Global row se) - scanner universe me bhi
    {"label": "COPPER - COMEX Copper Futures", "yahoo": "HG=F", "tv": "COMEX:HG1!"},
    {"label": "ALUMINIUM - COMEX Aluminium Futures", "yahoo": "ALI=F", "tv": "COMEX:ALI1!"},
    {"label": "ZINC - LME Special High Grade Zinc Futures", "yahoo": "ZNC=F", "tv": "LME:ZS1!"},
    {"label": "NATURAL GAS - NYMEX Natural Gas Futures", "yahoo": "NG=F", "tv": "NYMEX:NG1!"},
    {"label": "GBPUSD - GBP / USD", "yahoo": "GBPUSD=X", "tv": "FX:GBPUSD"},
    {"label": "EURUSD - EUR / USD", "yahoo": "EURUSD=X", "tv": "FX:EURUSD"},
    {"label": "USDJPY - USD / JPY", "yahoo": "JPY=X", "tv": "FX:USDJPY"},
    {"label": "JPYINR - JPY / INR", "yahoo": "JPYINR=X", "tv": "FX_IDC:JPYINR"},
    {"label": "GBPINR - GBP / INR", "yahoo": "GBPINR=X", "tv": "FX_IDC:GBPINR"},
    {"label": "BTCUSD - Bitcoin / USD", "yahoo": "BTC-USD", "tv": "BITSTAMP:BTCUSD"},
]

# Top ticker-tape (index + crude). USD/INR aur XAUUSD ab TOP_GLOBAL row me hain
# (duplicate na dikhe). Har chip TradingView chart se linked hai.
MARKET_WATCH = [
    {"label": "GIFT NIFTY", "yahoo": "^NSEI", "tv": "NSEIX:NIFTY1!",
     "note": "GIFT Nifty (NSE IX) chart; price = NIFTY 50 spot proxy (real GIFT feed nahi mil raha)"},
    {"label": "NIFTY 50", "yahoo": "^NSEI", "tv": "NSE:NIFTY"},
    {"label": "BANK NIFTY", "yahoo": "^NSEBANK", "tv": "NSE:BANKNIFTY"},
    {"label": "SPOTCRUDE", "yahoo": "CL=F", "tv": "TVC:USOIL"},
]

# Top global instruments - spot (Yahoo/global) + MCX futures (Dhan MCX_COMM) as SEPARATE rows.
# "mcx" = MCX commodity name (Dhan master SM_SYMBOL_NAME); "tv_mcx" = TradingView MCX symbol.
TOP_GLOBAL = [
    {"label": "COPPER", "yahoo": "HG=F", "tv": "COMEX:HG1!", "mcx": "COPPER", "tv_mcx": "MCX:COPPER1!"},
    {"label": "ALUMINIUM", "yahoo": "ALI=F", "tv": "COMEX:ALI1!", "mcx": "ALUMINIUM", "tv_mcx": "MCX:ALUMINIUM1!"},
    {"label": "ZINC", "yahoo": "ZNC=F", "tv": "LME:ZS1!", "mcx": "ZINC", "tv_mcx": "MCX:ZINC1!"},
    {"label": "NATURAL GAS", "yahoo": "NG=F", "tv": "NYMEX:NG1!", "mcx": "NATURALGAS", "tv_mcx": "MCX:NATURALGAS1!"},
    {"label": "GBP/USD", "yahoo": "GBPUSD=X", "tv": "FX:GBPUSD"},
    {"label": "EUR/USD", "yahoo": "EURUSD=X", "tv": "FX:EURUSD"},
    {"label": "USD/JPY", "yahoo": "JPY=X", "tv": "FX:USDJPY"},
    {"label": "JPY/INR", "yahoo": "JPYINR=X", "tv": "FX_IDC:JPYINR"},
    {"label": "GBP/INR", "yahoo": "GBPINR=X", "tv": "FX_IDC:GBPINR"},
    {"label": "USD/INR", "yahoo": "USDINR=X", "tv": "FX_IDC:USDINR", "mcx": None},
    {"label": "BITCOIN/USD", "yahoo": "BTC-USD", "tv": "BITSTAMP:BTCUSD"},
    {"label": "XAU/USD", "yahoo": "GC=F", "tv": "TVC:GOLD", "mcx": "GOLD", "tv_mcx": "MCX:GOLD1!"},
    {"label": "XAG/USD", "yahoo": "SI=F", "tv": "TVC:SILVER", "mcx": "SILVER", "tv_mcx": "MCX:SILVER1!"},
]


def top_global_yahoo() -> List[str]:
    return list(dict.fromkeys(item["yahoo"] for item in TOP_GLOBAL))


def all_watch_items() -> List[dict]:
    """Tape + Top Global items (live quote fetch ke liye, label/yahoo wali list)."""
    return list(MARKET_WATCH) + list(TOP_GLOBAL)


YAHOO_TO_META: Dict[str, dict] = {item["yahoo"]: item for item in GLOBAL_INSTRUMENTS}


def labels() -> List[str]:
    return [item["label"] for item in GLOBAL_INSTRUMENTS]


def label_to_yahoo(label: str) -> Optional[str]:
    for item in GLOBAL_INSTRUMENTS:
        if item["label"] == label:
            return item["yahoo"]
    return None
