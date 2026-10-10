"""
global_live.py - MCX front-month futures ke liye helpers (DISPLAY only).

Zone scan ke inputs / parameters / rules / logic se iska koi lena-dena nahi.
Ye sirf top ticker-tape ke "MCX <commodity>" chips ke liye Dhan ka MCX_COMM
live quote resolve karta hai.

Pipeline (app.py me cache ke saath use hota hai):
1. Dhan scrip master CSV -> MCX FUTCOM rows me se har commodity ka nearest
   non-expired contract -> security id   (pick_mcx_front_ids)
2. Dhan quote_data(securities={"MCX_COMM": [ids]}) -> LTP + % change
   (parse_mcx_quote)
Koi bhi step fail ho to empty dict -> UI me "--" dikhta hai, app nahi rukti.
"""

from typing import Dict, Iterable, Optional

import pandas as pd

MCX_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

_REQUIRED_COLS = ("SEM_EXM_EXCH_ID", "SEM_INSTRUMENT_NAME", "SM_SYMBOL_NAME",
                  "SEM_SMST_SECURITY_ID", "SEM_EXPIRY_DATE")


def pick_front_ids(master: pd.DataFrame, names: Iterable[str], exch: str, instrument: str,
                   today: Optional[pd.Timestamp] = None) -> Dict[str, str]:
    """{SM_SYMBOL_NAME: security_id} - har name ke liye sabse nazdeek non-expired contract.

    exch: "MCX" (commodity) ya "NSE" (currency futures); instrument: "FUTCOM" / "FUTCUR".
    """
    if master is None or master.empty or not all(c in master.columns for c in _REQUIRED_COLS):
        return {}
    want = {str(n).strip().upper() for n in names}
    df = master[(master["SEM_EXM_EXCH_ID"].astype(str).str.upper() == exch.upper())
                & (master["SEM_INSTRUMENT_NAME"].astype(str).str.upper() == instrument.upper())].copy()
    df["_sym"] = df["SM_SYMBOL_NAME"].astype(str).str.strip().str.upper()
    df = df[df["_sym"].isin(want)]
    if df.empty:
        return {}
    df["_exp"] = pd.to_datetime(df["SEM_EXPIRY_DATE"], errors="coerce")
    now = today if today is not None else pd.Timestamp.now().normalize()
    df = df[df["_exp"].notna() & (df["_exp"] >= now)]
    out: Dict[str, str] = {}
    for sym, grp in df.groupby("_sym"):
        row = grp.sort_values("_exp").iloc[0]
        sid = str(row["SEM_SMST_SECURITY_ID"]).strip()
        if sid.endswith(".0"):
            sid = sid[:-2]
        if sid.isdigit():
            out[sym] = sid
    return out


def pick_mcx_front_ids(master: pd.DataFrame, names: Iterable[str],
                       today: Optional[pd.Timestamp] = None) -> Dict[str, str]:
    """MCX commodity futures (FUTCOM) ke front-month security IDs."""
    return pick_front_ids(master, names, "MCX", "FUTCOM", today)


def pick_inr_currency_front_ids(master: pd.DataFrame, names: Iterable[str],
                                today: Optional[pd.Timestamp] = None) -> Dict[str, str]:
    """NSE currency futures (FUTCUR, segment NSE_CURRENCY) ke front-month IDs - e.g. USDINR, JPYINR, GBPINR."""
    return pick_front_ids(master, names, "NSE", "FUTCUR", today)


# ---------------------------------------------------------------- Twelve Data (optional, free key)

# Yahoo symbol -> Twelve Data symbol (sirf woh jo confirm hain: forex, crypto, XAU/XAG)
TWELVE_SYMBOL = {
    "GC=F": "XAU/USD", "SI=F": "XAG/USD",
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "JPY=X": "USD/JPY",
    "USDINR=X": "USD/INR", "GBPINR=X": "GBP/INR", "JPYINR=X": "JPY/INR",
    "BTC-USD": "BTC/USD",
}


def twelve_request_symbols(yahoo_syms: Iterable[str]) -> Dict[str, str]:
    """{yahoo: twelve} - sirf mapped symbols."""
    return {y: TWELVE_SYMBOL[y] for y in yahoo_syms if y in TWELVE_SYMBOL}


def parse_twelve_quotes(payload, yahoo_by_twelve: Dict[str, str]) -> Dict[str, tuple]:
    """Twelve Data /quote response -> {yahoo: (close, percent_change)}.
    Batch (comma list) me response {SYMBOL: {...}} hota hai; single symbol me seedha object.
    Error payload (status=error / code) -> {}."""
    if not isinstance(payload, dict) or payload.get("status") == "error":
        return {}
    out: Dict[str, tuple] = {}

    def _one(q, yahoo):
        try:
            last = float(q["close"])
            chg = float(q.get("percent_change") or 0.0)
        except (KeyError, TypeError, ValueError):
            return
        out[yahoo] = (last, chg)

    if len(yahoo_by_twelve) == 1:
        (yahoo, _tw), = yahoo_by_twelve.items()
        if isinstance(payload.get("close"), (str, float, int)):
            _one(payload, yahoo)
            return out
    for yahoo, tw in yahoo_by_twelve.items():
        q = payload.get(tw)
        if isinstance(q, dict) and q.get("status") != "error":
            _one(q, yahoo)
    return out


def parse_mcx_quote(quote: dict) -> Optional[dict]:
    """Dhan quote dict -> {"ltp","change_pct","source"}; LTP nahi to None."""
    if not isinstance(quote, dict):
        return None

    def _num(v):
        try:
            return float(v) if v is not None and str(v).strip() != "" else None
        except Exception:
            return None

    ltp = _num(quote.get("last_price"))
    if not ltp:
        return None
    prev = _num((quote.get("ohlc") or {}).get("close")) or _num(quote.get("prev_close"))
    if prev:
        chg_pct = (ltp - prev) / prev * 100.0
    else:
        chg_pct = _num(quote.get("percentage_change")) or 0.0
    return {"ltp": ltp, "change_pct": chg_pct, "source": "Dhan MCX"}
