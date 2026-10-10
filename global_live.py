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


def pick_mcx_front_ids(master: pd.DataFrame, names: Iterable[str],
                       today: Optional[pd.Timestamp] = None) -> Dict[str, str]:
    """{commodity_name: security_id} - har name ke liye sabse nazdeek non-expired FUTCOM.

    names: e.g. ("COPPER", "ALUMINIUM", "ZINC", "NATURALGAS", "GOLD", "SILVER")
    """
    if master is None or master.empty or not all(c in master.columns for c in _REQUIRED_COLS):
        return {}
    want = {str(n).strip().upper() for n in names}
    df = master[(master["SEM_EXM_EXCH_ID"].astype(str).str.upper() == "MCX")
                & (master["SEM_INSTRUMENT_NAME"].astype(str).str.upper() == "FUTCOM")].copy()
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
