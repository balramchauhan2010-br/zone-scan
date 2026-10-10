"""
fast_live_price.py - RESTORED: hybrid live-price engine (Dhan > Yahoo)

BUG-FIX (latency ka asli karan): pehle is file me galti se
powerful_news_fetcher.py ki poori copy aa gayi thi, jisse
`get_live_price_hybrid_ultra_fast` / `get_gift_nifty_real` functions exist
hi nahi karte the -> har import fail -> app HAMESHA slow fallback par
chalti thi (Dhan API connected hone par bhi!). Ab asli module wapas hai.

Priority (fastest source first):
1. Dhan API (jab key configured hai) - real-time batch quotes, 5s cache
2. Yahoo Finance batch quotes (curl_cffi session) - 20s cache
3. NSE MCP live quotes (keyless, persistent session, 10s cache) - sirf NSE
   stocks jo 1 aur 2 se nahi mile; circuit breaker ke saath
4. Koi bhi source fail ho to quiet fallback - app kabhi nahi rukti

IMPORTANT: zone scan ke inputs/parameters/rules/logic se iska koi lena-dena
nahi hai - ye sirf DISPLAY (top tape + table ka LTP column) ke live prices
refresh karta hai, scan engine untouched hai.
"""

import re
from typing import Dict, List, Optional, Tuple

import streamlit as st

# NSE indices ke Dhan security IDs (master CSV fail ho to bhi kaam chale)
INDEX_DHAN_IDS = {
    "NIFTY 50": "13",
    "NIFTY": "13",
    "NIFTY50": "13",
    "BANK NIFTY": "25",
    "BANKNIFTY": "25",
    "FINNIFTY": "27",
    "FIN NIFTY": "27",
    "MIDCPNIFTY": "288",
    "MIDCAP NIFTY": "288",
    "NIFTY NEXT 50": "38",
    "NIFTYNXT50": "38",
}

# Ye labels app me GIFT NIFTY ke proxy (NIFTY 50 spot) ke roop me dikhte hain
_PROXY_LABELS = {"GIFT NIFTY"}

_SYM_RE = re.compile(r"^[A-Z0-9&\-_]{1,25}$")

# Plain dikhte hain par Yahoo-only (US ETFs) - NSE_EQ me mat jao
_YAHOO_PLAIN = {"TLT", "SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO", "UVXY", "VIX"}


def _classify(symbols: Tuple[str, ...]):
    """Symbols ko Dhan-INDEX / Dhan-EQ / Yahoo buckets me baant do."""
    idx_ids: List[str] = []
    eq_syms: List[str] = []
    yahoo_syms: List[str] = []
    plan = {}  # orig_sym -> ("idx"|"eq"|"yahoo", dhan_id_or_yahoo_key)
    for sym in symbols:
        s = str(sym).strip()
        up = s.upper()
        clean = up.replace(".NS", "")
        if up in _PROXY_LABELS:
            # GIFT NIFTY ka koi free real feed nahi -> NIFTY 50 spot proxy
            plan[s] = ("idx", INDEX_DHAN_IDS["NIFTY 50"])
            if INDEX_DHAN_IDS["NIFTY 50"] not in idx_ids:
                idx_ids.append(INDEX_DHAN_IDS["NIFTY 50"])
        elif clean in INDEX_DHAN_IDS:
            plan[s] = ("idx", INDEX_DHAN_IDS[clean])
            if INDEX_DHAN_IDS[clean] not in idx_ids:
                idx_ids.append(INDEX_DHAN_IDS[clean])
        elif any(m in s for m in ("^", "=X", "=F", ".NS", ".BO", "/", "!")):
            plan[s] = ("yahoo", s)
            yahoo_syms.append(s)
        elif clean in _YAHOO_PLAIN:
            plan[s] = ("yahoo", s)
            yahoo_syms.append(s)
        elif _SYM_RE.match(clean):
            plan[s] = ("eq", clean)
            eq_syms.append(clean)
        else:
            plan[s] = ("yahoo", s)
            yahoo_syms.append(s)
    return idx_ids, eq_syms, yahoo_syms, plan


def _f(quote: dict, *keys, default=0.0) -> float:
    """Dhan quote dict se pehla valid number nikalo."""
    for k in keys:
        try:
            v = quote.get(k)
            if v is not None and str(v).strip() != "":
                return float(v)
        except Exception:
            continue
    return default


@st.cache_resource(show_spinner=False)
def _dhan_client(client_id: str, access_token: str):
    """Ek hi dhanhq client baar-baar reuse (naya connection har call par nahi)."""
    try:
        from dhanhq import dhanhq
        return dhanhq(client_id, access_token)
    except Exception as e:
        print(f"Dhan client create error: {e}")
        return None


@st.cache_data(show_spinner=False, ttl=5)  # 5s - Dhan real-time fast path
def _dhan_quote_batch(client_id: str, access_token: str, idx_ids: tuple, eq_syms: tuple) -> dict:
    """Dhan batch quote.
    Returns: index ID(str) -> quote  +  EQ symbol(str) -> quote
    (EQ symbols yahan master CSV se security-ID me resolve hote hain.)"""
    out: Dict[str, dict] = {}
    if not (client_id and access_token):
        return out
    client = _dhan_client(client_id, access_token)
    if client is None:
        return out
    securities: Dict[str, List[int]] = {}
    key_for_sid: Dict[str, str] = {}  # security_id -> return key (idx id ya eq symbol)
    if idx_ids:
        securities["IDX_I"] = [int(x) for x in idx_ids]
        for i in idx_ids:
            key_for_sid[str(i)] = str(i)
    if eq_syms:
        try:
            # BUG-FIX: ye function is file me import hi nahi tha -> NameError -> master={} ->
            # Dhan se NSE stocks kabhi resolve nahi hote the (sab Yahoo par jaata tha).
            from dhan_api_helper import load_dhan_master_fast
            master = load_dhan_master_fast()
        except Exception as e:
            print(f"Dhan master load error: {e}")
            master = {}
        eq_id_list: List[int] = []
        for s in eq_syms:
            info = master.get(s) or master.get(s.split("-")[0])
            if not info:
                continue
            sid = str(info.get("security_id", "")).strip()
            if not sid or not sid.isdigit():
                continue
            eq_id_list.append(int(sid))
            key_for_sid[sid] = s
        if eq_id_list:
            securities["NSE_EQ"] = eq_id_list
    if not securities:
        return out
    try:
        resp = client.quote_data(securities=securities)
        data = resp.get("data") if isinstance(resp, dict) else None
        if isinstance(data, dict):
            for seg, sec_dict in data.items():
                if not isinstance(sec_dict, dict):
                    continue
                for sec_id, quote in sec_dict.items():
                    q = quote if isinstance(quote, dict) else {}
                    ltp = _f(q, "last_price", "ltp", "average_price")
                    key = key_for_sid.get(str(sec_id))
                    if not ltp or not key:
                        continue
                    prev = _f(q, "prev_close", "prev_close_price", "previous_close", "close_price")
                    if prev:
                        chg = ltp - prev
                        chg_pct = (chg / prev * 100.0) if prev else 0.0
                    else:
                        chg = _f(q, "net_change", "change", "day_change", "updown")
                        chg_pct = _f(q, "percentage_change", "updown_percent")
                    out[key] = {"ltp": ltp, "change": chg, "change_pct": chg_pct, "source": "Dhan"}
    except Exception as e:
        print(f"Dhan quote batch error: {e}")
    return out


@st.cache_data(show_spinner=False, ttl=20)  # 20s - Yahoo ko throttle na kare
def _yahoo_quote_batch(yahoo_syms: tuple) -> dict:
    """Yahoo batch: {yahoo_symbol: {"ltp","change","change_pct"}}"""
    out: Dict[str, dict] = {}
    if not yahoo_syms:
        return out
    try:
        import data_fetch
        quotes = data_fetch.fetch_market_watch_quotes(list(yahoo_syms))  # {t: (last, chg_pct)}
        for t, (last, chg_pct) in (quotes or {}).items():
            out[t] = {"ltp": float(last), "change": 0.0, "change_pct": float(chg_pct), "source": "Yahoo"}
    except Exception as e:
        print(f"Yahoo quote batch error: {e}")
    return out


def get_live_price_hybrid_ultra_fast(symbols, client_id: str = None, access_token: str = None) -> dict:
    """
    FAST hybrid live prices - Dhan (5s cache) > Yahoo (20s cache).

    symbols: koi bhi mix - "RELIANCE", "M&M", "NIFTY 50", "GIFT NIFTY",
             "^NSEI", "USDINR=X", "GC=F", "TLT", "TCS.NS" ...
    Returns: {original_symbol: {"ltp","change","change_pct","source"}}
    """
    syms = tuple(symbols) if symbols else ()
    if not syms:
        return {}
    idx_ids, eq_syms, yahoo_syms, plan = _classify(syms)

    result: Dict[str, dict] = {}

    # 1) Dhan fast path (sirf tab jab key diye gaye ho)
    if client_id and access_token and (idx_ids or eq_syms):
        try:
            q = _dhan_quote_batch(client_id, access_token, tuple(idx_ids), tuple(eq_syms))
            for orig, (kind, key) in plan.items():
                if kind in ("idx", "eq") and key in q:
                    result[orig] = q[key]
        except Exception as e:
            print(f"Dhan hybrid path error: {e}")

    # 2) Yahoo fallback for whatever Dhan missed (ya jahan Dhan hai hi nahi)
    need_yahoo = {}
    for orig, (kind, key) in plan.items():
        if orig in result:
            continue
        yk = key if kind == "yahoo" else (orig.replace(".NS", "") + ".NS" if kind == "eq" else orig)
        need_yahoo[orig] = yk
    if need_yahoo:
        try:
            yq = _yahoo_quote_batch(tuple(sorted(set(need_yahoo.values()))))
            for orig, yk in need_yahoo.items():
                if yk in yq:
                    result[orig] = yq[yk]
        except Exception as e:
            print(f"Yahoo hybrid fallback error: {e}")

    # 3) NSE MCP (official, keyless) - Dhan + Yahoo dono jo miss karein sirf NSE stocks ke
    #    liye aakhri fallback. Yahoo ke baad isliye: NSE live data 1-3 min delay ka hai,
    #    to jab Dhan/Yahoo chal rahe hon to latency kabhi nahi badhti.
    nse_need: Dict[str, str] = {}
    for orig, (kind, key) in plan.items():
        if orig in result:
            continue
        if kind == "eq":
            nse_need[orig] = key
        elif kind == "yahoo" and orig.upper().endswith(".NS"):
            nse_need[orig] = orig[:-3].upper()
    if nse_need:
        try:
            import nse_mcp_client as nmc
            nq = nmc.get_client().live_quotes(list(nse_need.values()))
            for orig, sym in nse_need.items():
                if sym in nq:
                    result[orig] = nq[sym]
        except Exception as e:
            print(f"NSE MCP fallback error: {e}")

    return result


def get_gift_nifty_real() -> dict:
    """
    GIFT NIFTY (NSE IX, GIFT City) ka genuine continuous feed kisi FREE source
    (Yahoo/Dhan) par available nahi hai - isliye {} return karte hain, taaki UI
    galat price ko "Real" bolkar na dikhaye (proxy NIFTY 50 tape par already hai).
    Jab future me koi bharosemand free endpoint mile, wahi yahan jud jayega.
    """
    return {}


def is_dhan_fast_available() -> bool:
    """Dhan fast path use ho sakta hai? (key configured + library installed)"""
    try:
        from secure_config import is_dhan_configured
        try:
            from dhanhq import dhanhq  # noqa: F401
        except ImportError:
            return False
        return bool(is_dhan_configured())
    except Exception:
        return False
