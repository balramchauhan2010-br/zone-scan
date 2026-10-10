"""
live_oi.py - LIVE futures OI for NSE F&O stocks
==============================================

Source chain (sabse tez pehle):

  1. Dhan batch quote (jab Dhan key configured ho)
       dhan.quote_data({"NSE_FNO": [front-month FUTSTK security IDs]})  -> OI, LTP, volume
       Ek hi call me poore F&O universe (~210) ka live OI. Dhan quote limit ~1 req/sec.
       Security IDs Dhan ki scrip-master CSV se (front-month = sabse paas ki expiry).

  2. NSE derivative quote (keyless fallback, Dhan nahi hai ya fail ho)
       https://www.nseindia.com/api/quote-derivative?symbol=SYM
       Sirf PRIORITY stocks (zone + top OI movers) - ~30 se zyada nahi, aur 3 lagatar
       failure par turant ruk jaata hai (NSE aksar datacenter IP block karta hai).

  3. Kuch bhi nahi -> caller EOD bhavcopy OI dikhata hai (label ke saath).

Baseline: live OI ko PICHHLE SESSION KE CLOSE OI se compare karte hain
(EOD F&O bhavcopy ka fut_oi). Yani "aaj ab tak OI kitna badha/ghata".

IMPORTANT (unverified here): ye module us sandbox me likha gaya jahan Dhan aur NSE
dono reachable nahi the. Response field names (oi / last_price / openInterest etc.)
tolerant parsing se pakde jaate hain. Verify karne ke liye:
    python live_oi.py --probe
"""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from dateutil import parser as _dtparser

import candle_clock as cc

DHAN_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
DHAN_FNO_SEGMENT = "NSE_FNO"
DHAN_BATCH = 500           # ek quote call me max ids (safe side)
NSE_FALLBACK_MAX = 30      # NSE fallback par max stocks
NSE_SPACING = 0.35         # seconds between NSE calls (polite pacing)
NSE_FAIL_STOP = 3          # itni lagatar failures -> NSE blocked, ruk jao

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_FUT_SUFFIX = re.compile(r"-[A-Za-z]{3}\d{4}-FUT$", re.IGNORECASE)


# ----------------------------------------------------------------- helpers

def _num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, str):
            v = v.strip().replace(",", "")
            if v in ("", "-", "--", "NA", "null"):
                return None
        f = float(v)
        return f if f == f else None  # NaN guard
    except (TypeError, ValueError):
        return None


def _first_num(obj, keys: Iterable[str]) -> Optional[float]:
    """Dict (nested bhi) me keys ki priority order me pehla numeric value."""
    def dfs(o, k, d=0):
        if d > 6:
            return None
        if isinstance(o, dict):
            if k in o and _num(o[k]) is not None:
                return _num(o[k])
            for v in o.values():
                r = dfs(v, k, d + 1)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o[:20]:
                r = dfs(v, k, d + 1)
                if r is not None:
                    return r
        return None

    for k in keys:
        r = dfs(obj, k)
        if r is not None:
            return r
    return None


def pick_front_month(rows: Iterable[Tuple[str, dt.date, str]], today: dt.date) -> Dict[str, dict]:
    """(symbol, expiry, security_id) list -> har symbol ka sabse nazdeeki expiry (>= today)."""
    best: Dict[str, Tuple[dt.date, str]] = {}
    for sym, exp, sid in rows:
        if exp is None or exp < today or not sid:
            continue
        if sym not in best or exp < best[sym][0]:
            best[sym] = (exp, sid)
    return {s: {"security_id": sid, "expiry": exp.isoformat()} for s, (exp, sid) in best.items()}


# ----------------------------------------------------------------- Dhan

def load_dhan_futures_map(today_iso: str) -> Dict[str, dict]:
    """Dhan scrip-master se NSE stock-futures ke front-month security IDs.
    Fail -> {} (caller EOD/NSE fallback par chala jaata hai). {} kabhi cache nahi hota."""
    try:
        return _dhan_futures_map_cached(today_iso)
    except Exception as e:
        print(f"live_oi: Dhan master download failed: {e!r}"[:200])
        return {}


@st.cache_data(show_spinner=False, ttl=24 * 3600)
def _dhan_futures_map_cached(today_iso: str) -> Dict[str, dict]:
    """Download fail -> exception (cache nahi hota, agle call par retry/backoff)."""
    from dhan_api_helper import download_dhan_master_df
    df = download_dhan_master_df()
    need = {"SEM_EXM_EXCH_ID", "SEM_INSTRUMENT_NAME", "SEM_TRADING_SYMBOL",
            "SEM_SMST_SECURITY_ID", "SEM_EXPIRY_DATE"}
    if not need.issubset(df.columns):
        print(f"live_oi: Dhan master columns missing: {sorted(need - set(df.columns))}")
        return {}
    fut = df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_INSTRUMENT_NAME"] == "FUTSTK")]
    rows = []
    for _, r in fut.iterrows():
        sym = _FUT_SUFFIX.sub("", str(r["SEM_TRADING_SYMBOL"]).strip()).upper()
        try:
            exp = pd.to_datetime(r["SEM_EXPIRY_DATE"]).date()
            sid = str(int(float(r["SEM_SMST_SECURITY_ID"])))
        except (TypeError, ValueError):
            continue
        rows.append((sym, exp, sid))
    return pick_front_month(rows, dt.date.fromisoformat(today_iso))


def parse_dhan_quotes(resp: dict, id_to_sym: Dict[str, str]) -> Dict[str, dict]:
    """Dhan quote response -> {SYM: {oi, ltp, volume}}."""
    out: Dict[str, dict] = {}
    data = resp.get("data") if isinstance(resp, dict) else None
    seg = data.get(DHAN_FNO_SEGMENT) if isinstance(data, dict) else None
    if not isinstance(seg, dict):
        return out
    for sid, q in seg.items():
        sym = id_to_sym.get(str(sid))
        if not sym or not isinstance(q, dict):
            continue
        oi = _first_num(q, ("oi", "open_interest", "openInterest"))
        if oi is None:
            continue
        out[sym] = {
            "oi": oi,
            "ltp": _first_num(q, ("last_price", "ltp")),
            "volume": _first_num(q, ("volume", "total_volume")),
            "source": "Dhan",
        }
    return out


def dhan_live_oi(client, fut_map: Dict[str, dict], syms: Iterable[str]) -> Dict[str, dict]:
    wanted = set(syms)
    id_to_sym = {v["security_id"]: s for s, v in fut_map.items() if s in wanted}
    if not id_to_sym:
        return {}
    ids = [int(x) for x in id_to_sym]
    out: Dict[str, dict] = {}
    for i in range(0, len(ids), DHAN_BATCH):
        chunk = ids[i:i + DHAN_BATCH]
        try:
            resp = client.quote_data(securities={DHAN_FNO_SEGMENT: chunk})
        except Exception as e:
            print(f"live_oi: Dhan quote error: {e!r}"[:200])
            break
        out.update(parse_dhan_quotes(resp, {str(k): v for k, v in id_to_sym.items()}))
    return out


# ----------------------------------------------------------------- NSE fallback

def parse_nse_derivative(payload: dict, today: dt.date) -> Optional[dict]:
    """NSE quote-derivative payload -> nearest-expiry STOCK FUTURE ka {oi, ltp, volume, expiry}."""
    stocks = payload.get("stocks") if isinstance(payload, dict) else None
    best = None
    for item in stocks or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") or {}
        if "FUT" not in str(meta.get("instrumentType", "")).upper():
            continue
        try:
            exp = _dtparser.parse(str(meta.get("expiryDate")), dayfirst=True).date()
        except (ValueError, OverflowError, TypeError):
            continue
        if exp < today:
            continue
        if best is None or exp < best[0]:
            best = (exp, item)
    if best is None:
        return None
    exp, item = best
    oi = _first_num(item, ("openInterest", "openinterest", "OI"))
    if oi is None:
        return None
    return {
        "oi": oi,
        "ltp": _first_num(item, ("lastPrice", "last_price")),
        "volume": _first_num(item, ("totalTradedVolume", "tradedVolume", "volume")),
        "expiry": exp.isoformat(),
        "source": "NSE",
    }


def nse_live_oi(syms: Iterable[str], today: dt.date, max_n: int = NSE_FALLBACK_MAX,
                session=None) -> Dict[str, dict]:
    syms = list(dict.fromkeys(syms))[:max_n]
    out: Dict[str, dict] = {}
    if not syms:
        return out
    try:
        s = session or requests.Session()
        s.headers.update(_NSE_HEADERS)
        if session is None:
            s.get("https://www.nseindia.com/", timeout=8)  # cookie warm-up
            time.sleep(0.3)
    except Exception as e:
        print(f"live_oi: NSE session error: {e!r}"[:200])
        return out
    fails = 0
    for sym in syms:
        try:
            r = s.get(f"https://www.nseindia.com/api/quote-derivative?symbol={sym}",
                      headers={**_NSE_HEADERS,
                               "Referer": f"https://www.nseindia.com/get-quotes/derivatives?symbol={sym}"},
                      timeout=8)
            r.raise_for_status()
            p = parse_nse_derivative(r.json(), today)
            fails = 0
        except Exception as e:
            fails += 1
            print(f"live_oi: NSE {sym} error: {e!r}"[:160])
            if fails >= NSE_FAIL_STOP:
                print("live_oi: NSE blocked/unreachable - fallback band")
                break
            continue
        if p:
            out[sym] = p
        time.sleep(NSE_SPACING)
    return out


# ----------------------------------------------------------------- orchestrator

def _resolve_dhan_client():
    try:
        from secure_config import is_dhan_configured, get_dhan_creds
        if not is_dhan_configured():
            return None
        cid, tok = get_dhan_creds()
        from dhan_api_helper import get_dhan_client
        return get_dhan_client(cid, tok)
    except Exception as e:
        print(f"live_oi: Dhan client resolve error: {e!r}"[:160])
        return None


def get_live_fut_oi(fno: Iterable[str], priority: Iterable[str], today: Optional[dt.date] = None,
                    client=None, fut_map: Optional[Dict[str, dict]] = None,
                    nse_fetch=None) -> Tuple[Dict[str, dict], str]:
    """Live OI: {SYM: {oi, ltp, volume, source}} + status text.
    client/fut_map/nse_fetch test ke liye inject ho sakte hain; production me auto."""
    today = today or cc.now_ist().date()
    fno = list(dict.fromkeys(fno))
    fno_set = set(fno)
    out: Dict[str, dict] = {}
    notes: List[str] = []

    client = client if client is not None else _resolve_dhan_client()
    if client is not None:
        fm = fut_map if fut_map is not None else load_dhan_futures_map(today.isoformat())
        if fm:
            out.update(dhan_live_oi(client, fm, fno_set))
            notes.append(f"Dhan {len(out)}/{len(fno)}")
        else:
            notes.append("Dhan master nahi mila")

    missing = [s for s in priority if s in fno_set and s not in out]
    if missing:
        fetch = nse_fetch or (lambda syms: nse_live_oi(syms, today))
        got = fetch(missing)
        out.update(got)
        notes.append(f"NSE fallback {len(got)}/{len(missing)}")

    if not out:
        notes.append("live nahi mila, EOD dikh raha")
    status = " · ".join(notes) if notes else "live OI source nahi (sirf EOD)"
    return out, status


# ----------------------------------------------------------------- CLI probe

def _probe() -> None:
    today = cc.now_ist().date()
    client = _resolve_dhan_client()
    print("Dhan client:", "OK" if client else "not configured / unavailable")
    fm = load_dhan_futures_map(today.isoformat())
    print(f"Dhan front-month FUTSTK map: {len(fm)} symbols", list(fm.items())[:3])
    if client and fm:
        sample = list(fm.keys())[:5]
        print("Dhan quote sample:", dhan_live_oi(client, fm, sample))
    print("NSE fallback sample (RELIANCE):", nse_live_oi(["RELIANCE"], today, max_n=1))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "--probe":
        _probe()
    else:
        print("usage: python live_oi.py --probe")
