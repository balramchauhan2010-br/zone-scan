"""
dhan_api_helper_v2.py - FAST Dhan implementation for real-time price, no delay
Fixes: Price delay, slow open, uses Dhan when connected for fast LTP
"""

import os
import time
import pandas as pd
import requests
import io
from typing import List, Dict, Optional
import streamlit as st

try:
    from dhanhq import dhanhq
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False

_DHAN_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
_MASTER_RETRY_AFTER_FAIL_SEC = 300  # download fail -> 5 min tak dobara network call nahi (har 5s par 20s block se bachao)
_master_backoff = {"until": 0.0}


@st.cache_data(show_spinner=False, ttl=24 * 3600)
def download_dhan_master_df() -> pd.DataFrame:
    """Dhan scrip master CSV - ek hi download, 24h cache.
    Fail hone par EXCEPTION uthta hai: st.cache_data exception ko cache nahi karta,
    isliye galat/khaali result 24 ghante ke liye nahi atakta."""
    if time.time() < _master_backoff["until"]:
        raise RuntimeError("Dhan master: recent download fail, backoff active")
    try:
        resp = requests.get(_DHAN_MASTER_URL, timeout=20)
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text), low_memory=False)
    except Exception:
        _master_backoff["until"] = time.time() + _MASTER_RETRY_AFTER_FAIL_SEC
        raise


def _fallback_master() -> dict:
    """Master na mile to hardcoded index IDs + RELIANCE (cache me nahi jata)."""
    return {
        "NIFTY": {"security_id": "13", "segment": "IDX_I"},
        "NIFTY 50": {"security_id": "13", "segment": "IDX_I"},
        "BANKNIFTY": {"security_id": "25", "segment": "IDX_I"},
        "BANK NIFTY": {"security_id": "25", "segment": "IDX_I"},
        "FINNIFTY": {"security_id": "27", "segment": "IDX_I"},
        "RELIANCE": {"security_id": "11536", "segment": "NSE_EQ"},
    }


@st.cache_data(show_spinner=False, ttl=24 * 3600)
def _build_master_mapping() -> dict:
    """NSE symbol -> security ID mapping (download fail par exception -> cache nahi)."""
    df = download_dhan_master_df()
    mapping = {}
    # For EQ
    try:
        nse_eq = df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_SEGMENT"] == "EQ")]
        for _, row in nse_eq.iterrows():
            sym = str(row["SEM_TRADING_SYMBOL"]).strip().upper()
            sec_id = str(row["SEM_SMST_SECURITY_ID"]).strip()
            mapping[sym] = {"security_id": sec_id, "segment": "NSE_EQ"}
    except Exception:
        pass
    # For IDX (NIFTY, BANKNIFTY)
    try:
        idx = df[df["SEM_SEGMENT"] == "IDX_I"]
        for _, row in idx.iterrows():
            sym = str(row["SEM_TRADING_SYMBOL"]).strip().upper()
            sec_id = str(row["SEM_SMST_SECURITY_ID"]).strip()
            mapping[sym] = {"security_id": sec_id, "segment": "IDX_I"}
            if "NIFTY 50" in sym or sym == "NIFTY":
                mapping["NIFTY 50"] = {"security_id": sec_id, "segment": "IDX_I"}
                mapping["NIFTY"] = {"security_id": sec_id, "segment": "IDX_I"}
            if "BANK" in sym and "NIFTY" in sym:
                mapping["BANK NIFTY"] = {"security_id": sec_id, "segment": "IDX_I"}
                mapping["BANKNIFTY"] = {"security_id": sec_id, "segment": "IDX_I"}
    except Exception:
        pass
    # NSE EQ rows ek bhi nahi mili -> exception (cache_data me galat/adhoora mapping 24h na atke)
    if not any(v.get("segment") == "NSE_EQ" for v in mapping.values()):
        raise RuntimeError("Dhan master: NSE EQ rows parse nahi hui")
    # Hardcode known indices for speed if master partly fails
    if "NIFTY" not in mapping:
        mapping["NIFTY"] = {"security_id": "13", "segment": "IDX_I"}
        mapping["NIFTY 50"] = {"security_id": "13", "segment": "IDX_I"}
    if "BANKNIFTY" not in mapping:
        mapping["BANKNIFTY"] = {"security_id": "25", "segment": "IDX_I"}
        mapping["BANK NIFTY"] = {"security_id": "25", "segment": "IDX_I"}
    if "FINNIFTY" not in mapping:
        mapping["FINNIFTY"] = {"security_id": "27", "segment": "IDX_I"}
    return mapping


def load_dhan_master_fast() -> dict:
    """Dhan master mapping. Success 24h cache; failure par fallback (uncached) + backoff."""
    try:
        return _build_master_mapping()
    except Exception as e:
        print(f"Dhan master fast load error: {e}")
        return _fallback_master()


def get_dhan_client(client_id: str, access_token: str):
    """SINGLETON dhanhq client (cache_resource) - har call par naya connection
    banane se latency hoti thi; ab ek hi client reuse hota hai."""
    try:
        return _get_dhan_client_cached(client_id, access_token)
    except Exception as e:
        print(f"Dhan singleton client error: {e}")
        return None


@st.cache_resource(show_spinner=False)
def _get_dhan_client_cached(client_id: str, access_token: str):
    try:
        from dhanhq import dhanhq
        return dhanhq(client_id, access_token)
    except Exception as e:
        print(f"Dhan client create error: {e}")
        return None


@st.cache_data(show_spinner=False, ttl=5)  # 5 sec cache - real-time feel (pehle 60s tha = purana price)
def get_dhan_ltp_fast(client_id: str, access_token: str, symbols: tuple):
    """
    FAST LTP from Dhan - no delay, real-time, batch request
    symbols: tuple of NSE symbols like ("RELIANCE", "TCS", "NIFTY 50")
    Returns: dict symbol -> {"ltp": float, "change": float, "change_pct": float}
    """
    if not DHAN_AVAILABLE:
        return {}
    try:
        dhan = get_dhan_client(client_id, access_token)
        if dhan is None:
            return {}
        master = load_dhan_master_fast()
        
        # Group by segment
        nse_eq_ids = []
        idx_ids = []
        symbol_to_id = {}
        
        for sym in symbols:
            sym_clean = sym.replace(".NS", "").strip().upper()
            # Try direct
            info = master.get(sym_clean)
            if not info:
                # Try with .NS removed and common variations
                info = master.get(sym_clean.split("-")[0])
            if info:
                sec_id = info["security_id"]
                seg = info["segment"]
                symbol_to_id[sym] = {"id": sec_id, "seg": seg, "clean": sym_clean}
                if seg == "NSE_EQ":
                    nse_eq_ids.append(sec_id)
                elif seg == "IDX_I":
                    idx_ids.append(sec_id)
        
        result = {}
        
        # Fetch NSE EQ LTP via quote_data (fastest)
        if nse_eq_ids:
            try:
                # Dhan expects { "NSE_EQ": [ids] }
                # Try quote_data first
                try:
                    resp = dhan.quote_data(securities={"NSE_EQ": [int(x) for x in nse_eq_ids[:100]]})  # Batch max 100
                    if isinstance(resp, dict) and "data" in resp:
                        data = resp["data"]
                        # data is dict like {"NSE_EQ": {security_id: {ltp, ...}}}
                        if isinstance(data, dict):
                            for seg, sec_dict in data.items():
                                if isinstance(sec_dict, dict):
                                    for sec_id, quote in sec_dict.items():
                                        # Find symbol for this sec_id
                                        for orig_sym, id_info in symbol_to_id.items():
                                            if id_info["id"] == str(sec_id):
                                                ltp = float(quote.get("last_price", quote.get("ltp", 0)))
                                                prev_close = float(quote.get("prev_close", quote.get("prev_close_price", ltp)))
                                                chg = ltp - prev_close if prev_close else 0
                                                chg_pct = (chg / prev_close * 100) if prev_close else 0
                                                result[orig_sym] = {"ltp": ltp, "change": chg, "change_pct": chg_pct, "prev_close": prev_close}
                except Exception as e:
                    print(f"Dhan quote_data error: {e}")
                    # Fallback to ticker_data
                    try:
                        resp = dhan.ticker_data(securities={"NSE_EQ": [int(x) for x in nse_eq_ids[:100]]})
                        # Similar parsing
                        if isinstance(resp, dict) and "data" in resp:
                            for seg, sec_dict in resp["data"].items():
                                for sec_id, quote in sec_dict.items():
                                    for orig_sym, id_info in symbol_to_id.items():
                                        if id_info["id"] == str(sec_id):
                                            ltp = float(quote.get("last_price", 0))
                                            result[orig_sym] = {"ltp": ltp, "change": 0, "change_pct": 0}
                    except Exception as e2:
                        print(f"Dhan ticker_data fallback error: {e2}")
            except Exception as e:
                print(f"Dhan NSE EQ batch error: {e}")
        
        # Fetch IDX LTP (NIFTY, BANKNIFTY)
        if idx_ids:
            try:
                resp = dhan.quote_data(securities={"IDX_I": [int(x) for x in idx_ids]})
                if isinstance(resp, dict) and "data" in resp:
                    for seg, sec_dict in resp["data"].items():
                        for sec_id, quote in sec_dict.items():
                            for orig_sym, id_info in symbol_to_id.items():
                                if id_info["id"] == str(sec_id):
                                    ltp = float(quote.get("last_price", quote.get("ltp", 0)))
                                    prev_close = float(quote.get("prev_close", ltp))
                                    chg = ltp - prev_close
                                    chg_pct = (chg / prev_close * 100) if prev_close else 0
                                    result[orig_sym] = {"ltp": ltp, "change": chg, "change_pct": chg_pct}
            except Exception as e:
                print(f"Dhan IDX error: {e}")
        
        return result
    except Exception as e:
        print(f"Dhan LTP fast error: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=60)
def get_dhan_market_watch_fast(client_id: str, access_token: str):
    """
    Market Watch fast from Dhan - GIFT NIFTY, NIFTY 50, BANK NIFTY, USD/INR etc
    When Dhan connected, use Dhan for NIFTY/BANKNIFTY, Yahoo for others (GIFT, XAU, CRUDE, TLT)
    Returns: dict yahoo_symbol -> (last, change_pct)
    """
    result = {}
    try:
        # NIFTY 50 and BANK NIFTY from Dhan (fast, no delay)
        dhan_prices = get_dhan_ltp_fast(client_id, access_token, ("NIFTY 50", "BANK NIFTY", "NIFTY", "BANKNIFTY"))
        # Map to yahoo symbols used in app
        # gi.MARKET_WATCH has yahoo symbols like "^NSEI", "^NSEBANK", etc.
        # We'll return with keys matching those yahoo symbols
        if "NIFTY 50" in dhan_prices or "NIFTY" in dhan_prices:
            nifty_data = dhan_prices.get("NIFTY 50") or dhan_prices.get("NIFTY")
            if nifty_data:
                # NIFTY 50 spot -> ^NSEI. GIFT NIFTY ka real feed nahi hai: use NIFTY spot ki PROXY value
                # (koi +0.2% adjustment NAHI - pehle comment galat tha). Display me "*" se proxy dikhta hai.
                result["^NSEI"] = (nifty_data["ltp"], nifty_data["change_pct"])
                result["GIFT_NIFTY"] = (nifty_data["ltp"], nifty_data["change_pct"])
        if "BANK NIFTY" in dhan_prices or "BANKNIFTY" in dhan_prices:
            bank_data = dhan_prices.get("BANK NIFTY") or dhan_prices.get("BANKNIFTY")
            if bank_data:
                result["^NSEBANK"] = (bank_data["ltp"], bank_data["change_pct"])
    except Exception as e:
        print(f"Dhan market watch fast error: {e}")
    
    return result

def is_dhan_fast_available():
    """Check if Dhan fast path can be used"""
    try:
        from secure_config import is_dhan_configured
        return is_dhan_configured() and DHAN_AVAILABLE
    except Exception:
        return False
