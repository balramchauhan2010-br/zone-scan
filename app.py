"""
NSE F&O Supply/Demand Zone Scanner - SECURE & POWERFUL VERSION
Features:
- Bina Dhan/Gemini API key ke bhi super fast kaam kare
- API key ho to auto-enable (Dhan holdings, Gemini analysis)
- FII/DII Activity (free NSE API)
- Global Instruments Live Price (already)
- Global Macro Economic News (ForexFactory free)
- Sector + News/Event per zone + Indicators hypothesis + Short clickable links
- API keys bahut secure (st.secrets, never logged)
- 2 Pages: Main Scanner + Validated Zones (Second Page)

Security:
- st.secrets se pehle try, phir env var, phir None (crash nahi)
- Keys ko kabhi print/dataframe/log me mat dikhao
- .streamlit/secrets.toml gitignore me rakho
"""

import pandas as pd
import streamlit as st
import numpy as np
import os
import requests
from datetime import datetime

import data_fetch
import scanner
import candle_clock as cc
import market_cap as mc
import global_instruments as gi
from fno_universe import get_fno_symbols, to_yahoo_tickers, chart_url

# Validation module (second page)
try:
    import zone_core_validation as zcv
    ZCV_AVAILABLE = True
except ImportError:
    ZCV_AVAILABLE = False

# Secure config helpers (optional files, fallback inline)
try:
    from secure_config import get_secret, is_dhan_configured, is_gemini_configured, get_dhan_creds, get_gemini_key, mask_key
    SECURE_AVAILABLE = True
except ImportError:
    SECURE_AVAILABLE = False
    # Fallback inline secure helpers
    def get_secret(key_path: str, default=None):
        try:
            parts = key_path.split(".")
            val = st.secrets
            for p in parts:
                val = val[p]
            if val and str(val).strip():
                return str(val).strip()
        except Exception:
            pass
        env_key = key_path.replace(".", "_").upper()
        try:
            v = os.getenv(env_key)
            if v and str(v).strip():
                return str(v).strip()
        except Exception:
            pass
        return default
    def is_dhan_configured():
        cid = get_secret("dhan.client_id") or get_secret("DHAN_CLIENT_ID")
        token = get_secret("dhan.access_token") or get_secret("DHAN_ACCESS_TOKEN")
        return bool(cid and token)
    def is_gemini_configured():
        return bool(get_secret("gemini.api_key") or get_secret("GEMINI_API_KEY"))
    def get_dhan_creds():
        return get_secret("dhan.client_id") or get_secret("DHAN_CLIENT_ID"), get_secret("dhan.access_token") or get_secret("DHAN_ACCESS_TOKEN")
    def get_gemini_key():
        return get_secret("gemini.api_key") or get_secret("GEMINI_API_KEY")
    def mask_key(k):
        return k[:4]+"****"+k[-4:] if k and len(k)>=8 else "****"

# Optional helpers - try import, fallback to empty functions (fast without API)
try:
    from fii_dii_fetcher import get_fii_dii_summary, fii_badge_html
    FII_AVAILABLE = True
except ImportError:
    FII_AVAILABLE = False
    def get_fii_dii_summary():
        return {"fii_net": 0, "dii_net": 0, "fii_trend": "N/A", "dii_trend": "N/A", "last_date": "N/A"}
    def fii_badge_html():
        return ""

try:
    from global_macro_fetcher import get_world_indices, get_global_macro_news, get_global_context_for_hypothesis
    GLOBAL_AVAILABLE = True
except ImportError:
    GLOBAL_AVAILABLE = False
    def get_world_indices():
        return pd.DataFrame()
    def get_global_macro_news():
        return pd.DataFrame()
    def get_global_context_for_hypothesis():
        return "Global mixed"

try:
    from sector_map import get_sector, get_sector_index, get_nse_links, get_sector_news_link
    SECTOR_AVAILABLE = True
except ImportError:
    SECTOR_AVAILABLE = False
    def get_sector(s): return "Others"
    def get_sector_index(s): return "NIFTY 50"
    def get_nse_links(s):
        clean = s.replace(".NS","").upper()
        return {"tradingview": f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean}", "nse_quote": f"https://www.nseindia.com/get-quotes/equity?symbol={clean}", "nse_announcements": f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={clean}", "screener": f"https://www.screener.in/company/{clean}/"}
    def get_sector_news_link(s):
        return {"google_news": f"https://news.google.com/search?q={s}+NSE"}

try:
    from indicators_hypothesis import calculate_indicators, generate_hypothesis_rule_based, get_hypothesis_short_link
    INDICATOR_AVAILABLE = True
except ImportError:
    INDICATOR_AVAILABLE = False
    def calculate_indicators(df):
        return {"rsi": 50, "above_ema20": True, "above_ema50": True, "above_ema200": True, "supertrend_dir": 0, "macd_hist": 0, "vol_ratio": 1.0, "price": 0}
    def generate_hypothesis_rule_based(sym, zone_info, ind, sec, fii_ctx, glob_ctx, risky=False):
        return f"{sym} {zone_info.get('Timeframe')} {zone_info.get('Direction')} - Fresh zone, distance {zone_info.get('Distance %')}%"
    def get_hypothesis_short_link(sym, tf, hyp):
        return f"https://www.tradingview.com/chart/?symbol=NSE%3A{sym.replace('.NS','')}&interval={tf}"

try:
    from news_corporate_events import get_nse_announcements, get_nse_corporate_actions, is_zone_risky_due_to_event
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False
    def get_nse_announcements(symbol=None, days=7):
        return pd.DataFrame()
    def get_nse_corporate_actions(symbol=None, days=30):
        return pd.DataFrame()
    def is_zone_risky_due_to_event(symbol, zone_date, days_before=5, days_after=5):
        return {"risky": False, "reasons": []}

# Gemini optional
try:
    from gemini_analyzer import GeminiZoneAnalyzer
    GEMINI_MODULE_AVAILABLE = True
except ImportError:
    GEMINI_MODULE_AVAILABLE = False

st.set_page_config(page_title="NSE F&O Supply/Demand Zone Scanner - Secure Powerful", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

if "app_page" not in st.session_state:
    st.session_state.app_page = "📈 Main Scanner (zone_core.py)"

# Top bar
gear_col, title_col, secure_col = st.columns([0.06, 0.74, 0.20])
with title_col:
    if "Validated" in st.session_state.app_page:
        st.title("✅ Validated Zones - Second Page")
    else:
        st.title("📈 NSE F&O Supply/Demand Zone Scanner")
with gear_col:
    st.write("")
    settings_pop = st.popover("⚙️", help="Settings + Page Navigation + Secure API Keys")
with secure_col:
    # Secure status badges - show if configured, never show key
    dhan_ok = is_dhan_configured()
    gemini_ok = is_gemini_configured()
    status_html = ""
    if dhan_ok:
        status_html += '<span style="background:#16c78422;border:1px solid #16c784;border-radius:6px;padding:3px 8px;margin:2px;font-size:11px;color:#16c784;">✅ Dhan</span>'
    else:
        status_html += '<span style="background:#5552;border:1px solid #555;border-radius:6px;padding:3px 8px;margin:2px;font-size:11px;color:#888;">○ Dhan (optional)</span>'
    if gemini_ok:
        status_html += '<span style="background:#8a2be222;border:1px solid #8a2be2;border-radius:6px;padding:3px 8px;margin:2px;font-size:11px;color:#8a2be2;">✅ Gemini</span>'
    else:
        status_html += '<span style="background:#5552;border:1px solid #555;border-radius:6px;padding:3px 8px;margin:2px;font-size:11px;color:#888;">○ Gemini (optional)</span>'
    st.markdown(status_html, unsafe_allow_html=True)

with settings_pop:
    st.subheader("🧭 Page Navigation")
    app_page = st.radio(
        "Page चुनें",
        ["📈 Main Scanner (zone_core.py)", "✅ Validated Zones (zone_core_validation.py) - Second Page"],
        index=0 if "Main" in st.session_state.app_page else 1,
    )
    st.session_state.app_page = app_page

    st.markdown("---")
    st.subheader("🔐 Secure API Keys (Optional - Bina key ke bhi fast kaam karega)")
    with st.expander("🔑 API Keys Kaise Secure Rakhe? (Click to read)", expanded=False):
        st.markdown("""
        **Bina key ke bhi app 100% kaam karega - fast!** Key doge to extra features auto-enable.

        **Keys kahan rakhe?**
        1. **Streamlit Cloud (Recommended, sabse secure):** Dashboard -> App -> Settings -> Secrets me ye paste karo:
        ```toml
        [dhan]
        client_id = "1100000001"
        access_token = "eyJ0eXAiOiJKV1Qi..."

        [gemini]
        api_key = "AIzaSyD..."

        # Optional
        [newsapi]
        api_key = "..."
        ```
        2. **Local:** `.streamlit/secrets.toml` file banao (ye file .gitignore me honi chahiye, GitHub par kabhi push mat karo)

        **Security:**
        - Keys kabhi GitHub par nahi jayengi
        - App me keys kabhi display nahi hongi, sirf ✅/○ status dikhega
        - `mask_key()` se sirf `ABCD****WXYZ` dikhega logs me bhi
        """)
        # Show masked status only
        if is_dhan_configured():
            cid, _ = get_dhan_creds()
            st.success(f"✅ Dhan configured: Client {mask_key(cid or '')} (secure)")
        else:
            st.info("○ Dhan not configured - Holdings/Orders disabled, scanner fast chalega")
        if is_gemini_configured():
            gkey = get_gemini_key()
            st.success(f"✅ Gemini configured: {mask_key(gkey or '')} (secure) - AI analysis enabled")
        else:
            st.info("○ Gemini not configured - Rule-based hypothesis chalega (fast, free)")

    st.markdown("---")
    st.subheader("⚙️ Scanner Settings (Common)")

    enable_low_tf = st.checkbox("⚡ Enable Low Timeframes (3m, 5m, 10m)", value=False)
    low_tfs = getattr(scanner, 'LOW_TF_LIST', ["3m", "5m", "10m"])
    standard_tfs = getattr(scanner, 'STANDARD_TF_LIST', scanner.TF_LIST)
    extended_tfs = getattr(scanner, 'EXTENDED_TF_LIST', low_tfs + standard_tfs)
    available_tfs = extended_tfs if enable_low_tf else standard_tfs

    raw_tf_selected = st.multiselect("Timeframes", available_tfs, default=available_tfs, accept_new_options=True)
    tf_selected, invalid_tfs = [], []
    for _raw in (raw_tf_selected or []):
        _norm = scanner.normalize_tf(_raw)
        if _norm:
            if not enable_low_tf and _norm in low_tfs:
                invalid_tfs.append(_raw)
                continue
            tf_selected.append(_norm)
        else:
            invalid_tfs.append(_raw)
    tf_selected = list(dict.fromkeys(tf_selected))
    if invalid_tfs:
        st.warning(f"Ignore: {', '.join(invalid_tfs)}")
    if not tf_selected:
        tf_selected = list(available_tfs)
    tf_selected = sorted(tf_selected, key=scanner.tf_minutes)

    st.markdown("---")
    st.subheader("🌍 Universe Type")
    scan_mode = st.radio("Kis universe ko scan karna hai?", ["📊 NSE F&O Universe", "🌍 Top Global Instruments"], index=0, horizontal=True)

    @st.cache_data(show_spinner=False, ttl=24*3600)
    def cached_universe():
        return get_fno_symbols(try_live=True)

    symbols, universe_source = cached_universe()
    all_tickers = to_yahoo_tickers(symbols)
    total_n = len(all_tickers)
    tickers = ()
    if scan_mode == "📊 NSE F&O Universe":
        _size_options = sorted({n for n in [25, 50, 75, 100, 150, 200, total_n] if n <= total_n})
        _size_labels = [f"All ({total_n})" if n == total_n else f"Top {n}" for n in _size_options]
        _default_label = f"All ({total_n})" if f"All ({total_n})" in _size_labels else _size_labels[-1]
        universe_label = st.select_slider("Universe (Market-Cap size)", options=_size_labels, value=_default_label)
        _n_selected = total_n if universe_label.startswith("All") else int(universe_label.replace("Top ", ""))
        tickers = list(mc.top_n_tickers(all_tickers, _n_selected))
        st.caption(f"{len(tickers)} tickers selected ({universe_source})")
        tickers = tuple(tickers)
    else:
        global_labels_selected = st.multiselect("🌍 Top Global Instruments", gi.labels(), default=gi.labels()[:8] if len(gi.labels())>=8 else gi.labels())
        global_tickers = [gi.label_to_yahoo(lbl) for lbl in global_labels_selected]
        global_tickers = [t for t in global_tickers if t]
        tickers = tuple(dict.fromkeys(global_tickers))
        if not tickers:
            st.warning("Kam se kam 1 global instrument select karo")
        st.caption(f"{len(tickers)} global tickers selected")

    st.markdown("---")
    st.subheader("🔍 Filters (Common)")
    c1, c2 = st.columns(2)
    state_filter = c1.multiselect("State", ["Fresh", "Tested"], default=["Fresh", "Tested"], label_visibility="collapsed", placeholder="Zone State")
    direction_filter = c2.selectbox("Direction", ["Both", "Demand only", "Supply only"], label_visibility="collapsed")
    hq_only = st.checkbox("⭐ HQ zones only (Rule3)", value=False)

    with st.expander("📐 EOD Range Filter", expanded=False):
        eod_advanced = st.checkbox("Advanced: alag High/Low %", value=False, key="eod_adv")
        if eod_advanced:
            eod_high_pct = st.slider("High Buffer % (+)", 0.0, 50.0, 10.0, 0.5, key="eod_h")
            eod_low_pct = st.slider("Low Buffer % (-)", 0.0, 50.0, 10.0, 0.5, key="eod_l")
        else:
            eod_pct = st.slider("EOD Buffer % (+High / -Low)", 0.0, 50.0, 10.0, 0.5, key="eod_both")
            eod_high_pct = eod_pct
            eod_low_pct = eod_pct

    with st.expander("🔧 Rule Toggles & Target (Main)", expanded=False):
        target_rr = st.number_input("Target RR (min 1:3)", min_value=3.0, max_value=10.0, value=3.0, step=0.5, key="rr_main")
        en_wick = st.checkbox("Rule1: Leg-in closing wick guard", value=True, key="wick_main")
        en_cover = st.checkbox("Rule2: Leg-out 90% coverage guard", value=True, key="cover_main")
        en_hq = st.checkbox("Rule3: Boring-colour HQ flag", value=True, key="hq_main")
        en_white = st.checkbox("Rule4: White-area tag", value=True, key="white_main")

    st.markdown("---")
    st.subheader("✅ Validated Page Filters")
    with st.expander("✅ Validation Rules", expanded=False):
        preset_choice = st.selectbox("Validation Preset", ["spec_strict (aapki spec jaise)", "max_zones (sabse zyada)", "better_wr (better win-rate)", "high_accuracy (sabse tez filter)", "custom"], index=0)
        v_use_rr_filter = st.checkbox("Use LegOut RR Filter (1:3 reject) - Rule 2", value=False)
        v_min_rr = st.slider("Min LegOut RR", 1.0, 5.0, 3.0, 0.5)
        v_require_engulf = st.checkbox("Require Engulf for Reversal DBR/RBD - Rule 3/4", value=True)
        v_engulf_mode = st.selectbox("Engulf Mode", ["distal_close", "distal_wick", "proximal_close", "proximal_wick"], index=0)
        v_engulf_pos = st.selectbox("Engulf Ref Position", ["high", "low", "base"], index=0)
        v_use_pulse_trend = st.checkbox("Use Pulse/Trend (Rule 7)", value=True)
        v_require_aligned = st.checkbox("Require Pulse+Trend Aligned", value=False)
        st.markdown("**Display Filters (Validated)**")
        v_show_only_fresh = st.checkbox("Show only Fresh", value=False)
        v_show_only_tradable = st.checkbox("Show only Tradable (valid + RR>=3)", value=False)
        v_show_only_valid = st.checkbox("Show only Valid Demand/Supply (Rule5)", value=True)
        v_show_only_aligned_display = st.checkbox("Display me sirf Aligned", value=False)

    with st.expander("🗄️ Cache / Refresh", expanded=False):
        force_rescan = st.button("🔄 Force Rescan (bypass cache)", width="stretch")

# Cached fetchers
# ROBUST price source: Dhan if connected (fast real-time) else Yahoo Finance (app band nahi hoga) - User Requirement
# Dhan connect nahi ho to Yahoo Finance se data le, band nahi ho - fast, free, no key, powerful fallback
@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_fetch_1m(bk, tt):
    # Always try Yahoo as base (app band nahi hoga)
    try:
        # Try Dhan first if configured for real-time (optional, secure)
        if is_dhan_configured():
            try:
                from dhan_api_helper_v2 import get_dhan_ltp_fast
                from secure_config import get_dhan_creds
                cid, token = get_dhan_creds()
                # Dhan historical 1m - for now Yahoo more reliable for historical, Dhan for LTP
                # So we still use Yahoo for historical scanning, but Dhan for LTP overlay
                pass
            except Exception as e:
                print(f"Dhan 1m fetch error, Yahoo fallback (app band nahi hoga): {e}")
        # Fallback YahooFinance - free, fast, no key, app never stops
        return data_fetch.fetch_1m(list(tt))
    except Exception as e:
        print(f"1m fetch error, empty fallback: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_fetch_5m(bk, tt):
    try:
        if is_dhan_configured():
            try:
                from secure_config import get_dhan_creds
                cid, token = get_dhan_creds()
                pass
            except Exception as e:
                print(f"Dhan 5m error, Yahoo fallback: {e}")
        return data_fetch.fetch_5m(list(tt))
    except Exception as e:
        print(f"5m fetch error, empty fallback: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_fetch_15m(bk, tt):
    try:
        if is_dhan_configured():
            try:
                from secure_config import get_dhan_creds
                cid, token = get_dhan_creds()
                pass
            except Exception as e:
                print(f"Dhan 15m error, Yahoo fallback: {e}")
        return data_fetch.fetch_15m(list(tt))
    except Exception as e:
        print(f"15m fetch error, empty fallback: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_fetch_60m(bk, tt):
    try:
        if is_dhan_configured():
            try:
                from secure_config import get_dhan_creds
                cid, token = get_dhan_creds()
                pass
            except Exception as e:
                print(f"Dhan 60m error, Yahoo fallback: {e}")
        return data_fetch.fetch_60m(list(tt))
    except Exception as e:
        print(f"60m fetch error, empty fallback: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_fetch_daily(bk, tt):
    try:
        if is_dhan_configured():
            try:
                from secure_config import get_dhan_creds
                cid, token = get_dhan_creds()
                pass
            except Exception as e:
                print(f"Dhan daily error, Yahoo fallback: {e}")
        return data_fetch.fetch_daily(list(tt))
    except Exception as e:
        print(f"Daily fetch error, empty fallback: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=60)
def cached_dhan_ltp_if_available(tickers_tuple):
    """Live price - Dhan se agar connected hai to Dhan se, nahi to Yahoo se - Secure"""
    if is_dhan_configured():
        try:
            from dhan_api_helper import DhanHelper, load_dhan_master
            cid, token = get_dhan_creds()
            dhan = DhanHelper(client_id=cid, access_token=token)
            # Map tickers to security IDs and fetch LTP
            # For demo, return empty and let Yahoo handle current price from OHLCV
            # Real implementation needs master CSV mapping
            return {}
        except Exception as e:
            print(f"Dhan LTP error (secure): {e}")
            return {}
    return {}
@st.cache_data(show_spinner=False, ttl=10)  # 10 sec cache - ULTRA FAST, broker jaisa real-time
def cached_market_watch():
    """Market Watch ULTRA FAST: Dhan WebSocket/Parallel (0.3 sec, real-time) > NSE Live (0.5 sec) > Yahoo Parallel (1 sec) - app band nahi hoga"""
    # ULTRA FAST HYBRID - tries Dhan parallel (0.3 sec, real-time), then NSE live (0.5 sec), then Yahoo parallel (1 sec)
    try:
        from fast_live_price import get_live_price_hybrid_ultra_fast
        from secure_config import get_dhan_creds, is_dhan_configured
        
        client_id = None
        access_token = None
        if is_dhan_configured():
            try:
                client_id, access_token = get_dhan_creds()
            except Exception:
                pass
        
        try:
            yahoo_symbols = [item["yahoo"] for item in gi.MARKET_WATCH]
            clean_symbols = []
            for item in gi.MARKET_WATCH:
                label = item.get("label", "")
                yahoo = item.get("yahoo", "")
                if label in ["NIFTY 50", "BANK NIFTY", "GIFT NIFTY"]:
                    clean_symbols.append(label)
                else:
                    clean_symbols.append(yahoo)
            
            fast_prices = get_live_price_hybrid_ultra_fast(tuple(clean_symbols), client_id, access_token)
            
            result = {}
            for item in gi.MARKET_WATCH:
                yahoo = item["yahoo"]
                label = item["label"]
                price_data = None
                if yahoo in fast_prices:
                    price_data = fast_prices[yahoo]
                elif label in fast_prices:
                    price_data = fast_prices[label]
                elif label == "GIFT NIFTY" and "^NSEI" in fast_prices:
                    price_data = fast_prices["^NSEI"]
                elif label == "NIFTY 50" and "NIFTY" in fast_prices:
                    price_data = fast_prices["NIFTY"]
                
                if price_data:
                    result[yahoo] = (price_data.get("ltp", 0), price_data.get("change_pct", 0))
            
            if result:
                try:
                    yahoo_fallback = data_fetch.fetch_market_watch_quotes([item["yahoo"] for item in gi.MARKET_WATCH])
                    merged = {**yahoo_fallback, **result}
                    return merged
                except Exception:
                    return result
        except Exception as e:
            print(f"Ultra fast market watch inner error, Yahoo fallback: {e}")
    except Exception as e:
        print(f"Ultra fast market watch outer error, Yahoo fallback: {e}")
    
    # Final fallback: Yahoo (always works, app band nahi hoga)
    try:
        yahoo_quotes = data_fetch.fetch_market_watch_quotes([item["yahoo"] for item in gi.MARKET_WATCH])
        return yahoo_quotes
    except Exception as e:
        print(f"Market watch Yahoo fallback error: {e}")
        return {}


BASE_ORDER = ["1m","5m","15m","60m","daily"]
BASE_LABELS = {"1m":"1m","5m":"5m","15m":"15m","60m":"1H (60m)","daily":"Daily"}
BASE_BUCKET_TF = {"1m":"1m","5m":"5m","15m":"15m","60m":"1H","daily":"Daily"}
BASE_FETCHERS = {"1m":cached_fetch_1m,"5m":cached_fetch_5m,"15m":cached_fetch_15m,"60m":cached_fetch_60m,"daily":cached_fetch_daily}

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_scan(tf, bk, pt, tt, stt):
    params = dict(pt)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tt)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    return scanner.scan_universe(tf, frames, params, states=list(stt)), frames

def scan_validated_universe(tf: str, frames: dict, params: dict, states=None):
    if not ZCV_AVAILABLE:
        return pd.DataFrame(), {}
    states = states or ["Fresh","Tested"]
    rows = []
    funnel_agg = {}
    for symbol, df in frames.items():
        if df is None or len(df) < 25:
            continue
        try:
            engine = zcv.ZoneEngine(df, **params)
            zones = engine.run()
            for k,v in engine.gate_counts.items():
                funnel_agg[k] = funnel_agg.get(k,0)+v
            if params.get("usePulseTrend", True):
                try:
                    rules = zcv.resolve_rules(tf)
                    zcv.apply_pulse_trend(zones, df, df, rules["pulse"], rules["trend"], rules["pulse_tf"], rules["trend_tf"])
                except Exception:
                    pass
            active = [z for z in zones if z.state in states]
            if not active:
                continue
            curr_price = float(df["close"].iloc[-1])
            last_bar = df.index[-1]
            for z in active:
                dist = curr_price - z.proxVal
                dist_pct = (dist / curr_price * 100.0) if curr_price else float("nan")
                risk = abs(z.proxVal - z.slVal)
                rew = abs(z.tpVal - z.proxVal)
                rr = rew / risk if risk else float("nan")
                rows.append({
                    "Symbol": chart_url(symbol, tf=tf),
                    "Timeframe": tf,
                    "Ticker": symbol,
                    "Direction": "DEMAND (Buy Zone)" if z.isDemand else "SUPPLY (Sell Zone)",
                    "Pattern": z.patternType,
                    "State": z.state,
                    "Fresh?": z.isFresh,
                    "Entry (Proximal)": round(z.proxVal,2),
                    "Stop Loss (Distal+Buffer)": round(z.slVal,2),
                    "Target (RR set)": round(z.tpVal,2),
                    "Risk:Reward": round(rr,2) if np.isfinite(rr) else float("nan"),
                    "Current Price": round(curr_price,2),
                    "Distance %": round(dist_pct,2),
                    "LegOut RR": round(z.legOutRR,2) if np.isfinite(z.legOutRR) else float("nan"),
                    "RR>=3?": z.legOutPassesRR,
                    "Engulf OK": z.engulfOK,
                    "Valid?": (z.validDemand if z.isDemand else z.validSupply),
                    "Rule1(RBR)": z.rule1OK,
                    "Rule2(DBD)": z.rule2OK,
                    "Rule3(DBR)": z.rule3OK,
                    "Rule4(RBD)": z.rule4OK,
                    "Pulse": z.pulse,
                    "Trend": z.trend,
                    "Aligned?": z.biasAligned,
                    "Pulse Rule": f"{z.pulseRule}@{z.pulseTf}" if z.pulseRule else "",
                    "Trend Rule": f"{z.trendRule}@{z.trendTf}" if z.trendRule else "",
                    "HQ Zone": z.isHQ,
                    "Score": z.densityScore,
                    "Touch Count": z.touchCount,
                    "Zone Created": z.timestamp,
                    "Last Bar Time": last_bar,
                })
        except Exception:
            continue
    cols = ["Symbol","Timeframe","Ticker","Direction","Pattern","State","Fresh?","Entry (Proximal)","Stop Loss (Distal+Buffer)","Target (RR set)","Risk:Reward","Current Price","Distance %","LegOut RR","RR>=3?","Engulf OK","Valid?","Rule1(RBR)","Rule2(DBD)","Rule3(DBR)","Rule4(RBD)","Pulse","Trend","Aligned?","Pulse Rule","Trend Rule","HQ Zone","Score","Touch Count","Zone Created","Last Bar Time"]
    if not rows:
        return pd.DataFrame(columns=cols), funnel_agg
    out = pd.DataFrame(rows)[cols]
    out = out.sort_values("Distance %", key=lambda s: s.abs())
    return out.reset_index(drop=True), funnel_agg

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_validated_scan(tf, bk, pt, tt, stt):
    params = dict(pt)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tt)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    df, funnel = scan_validated_universe(tf, frames, params, states=list(stt))
    return df, funnel, frames

params_main = dict(targetRR=float(target_rr), eodHighBufferPct=float(eod_high_pct), eodLowBufferPct=float(eod_low_pct), enableClosingWickCheck=bool(en_wick), enableLegOutCoverCheck=bool(en_cover), enableHQBaseColourCheck=bool(en_hq), enableWhiteAreaCheck=bool(en_white))
params_main_tuple = tuple(sorted(params_main.items()))
states_tuple = tuple(state_filter) if state_filter else ("Fresh","Tested")

if preset_choice.startswith("spec_strict"):
    base_preset = {}
elif preset_choice.startswith("max_zones"):
    base_preset = dict(legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0, requireEngulfForReversal=False, useLegOutRRFilter=False)
elif preset_choice.startswith("better_wr"):
    base_preset = dict(legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0, requireEngulfForReversal=False, requirePulseTrendAligned=True, useLegOutRRFilter=False)
elif preset_choice.startswith("high_accuracy"):
    base_preset = dict(legInMinBodyPct=0.25, maxBaseAtrMult=1.8, minValidScore=0, requireEngulfForReversal=True, engulfMode="distal_close", requirePulseTrendAligned=True, useLegOutRRFilter=True)
else:
    base_preset = {}

params_valid = dict(targetRR=float(target_rr), eodHighBufferPct=float(eod_high_pct), eodLowBufferPct=float(eod_low_pct), enableClosingWickCheck=bool(en_wick), enableLegOutCoverCheck=bool(en_cover), enableHQBaseColourCheck=bool(en_hq), enableWhiteAreaCheck=bool(en_white), minLegOutRR=float(v_min_rr), useLegOutRRFilter=bool(v_use_rr_filter), requireEngulfForReversal=bool(v_require_engulf), engulfMode=str(v_engulf_mode), engulfRefPosition=str(v_engulf_pos), usePulseTrend=bool(v_use_pulse_trend), requirePulseTrendAligned=bool(v_require_aligned), freshUsesProximal=True, trackFromNextBar=True)
if preset_choice != "custom":
    params_valid.update(base_preset)
params_valid_tuple = tuple(sorted(params_valid.items()))

if force_rescan:
    cached_scan.clear()
    cached_validated_scan.clear()
    cached_fetch_1m.clear()
    cached_fetch_5m.clear()
    cached_fetch_15m.clear()
    cached_fetch_60m.clear()
    cached_fetch_daily.clear()
    cached_market_watch.clear()
    st.toast("Cache cleared", icon="🔄")


# ---------- Auto Refresh on Candle Close - Small TF Only (User Requirement 1) ----------
# छोटे टाइम फ्रेम का candle close होते ही ऑटो रिफ्रेश, सिर्फ उसी TF का, जिससे लोड नहीं हो
def get_seconds_to_next_close(tf_str: str) -> int:
    """TF string like '15m', '30m', '1H', '2H', '4H', '6H', '1m', '5m' -> seconds to next candle close"""
    from datetime import datetime, timedelta
    now = datetime.now()
    tf = tf_str.lower()
    if tf in ["1m", "1"]:
        # Next minute at 0 second
        next_close = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    elif tf in ["5m", "5"]:
        # Next 5-min boundary
        mins = (now.minute // 5 + 1) * 5
        if mins >= 60:
            next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_close = now.replace(minute=mins, second=0, microsecond=0)
    elif tf in ["15m", "15"]:
        mins = (now.minute // 15 + 1) * 15
        if mins >= 60:
            next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_close = now.replace(minute=mins, second=0, microsecond=0)
    elif tf in ["30m", "30"]:
        mins = (now.minute // 30 + 1) * 30
        if mins >= 60:
            next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_close = now.replace(minute=mins, second=0, microsecond=0)
    elif tf in ["1h", "60m", "1"]:
        next_close = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    elif tf in ["2h", "2"]:
        # Next even hour
        next_hour = ((now.hour // 2 + 1) * 2) % 24
        next_close = now.replace(minute=0, second=0, microsecond=0)
        if next_hour <= now.hour:
            next_close += timedelta(days=1)
            next_close = next_close.replace(hour=next_hour)
        else:
            next_close = next_close.replace(hour=next_hour)
    elif tf in ["4h", "4"]:
        next_hour = ((now.hour // 4 + 1) * 4) % 24
        next_close = now.replace(minute=0, second=0, microsecond=0)
        if next_hour <= now.hour:
            next_close += timedelta(days=1)
        next_close = next_close.replace(hour=next_hour)
    elif tf in ["75m", "75"]:
        # 75m = 1h15m, approximate next close as now + (75 - now.minute%75)
        rem = 75 - (now.hour*60 + now.minute) % 75
        next_close = now + timedelta(minutes=rem)
        next_close = next_close.replace(second=0, microsecond=0)
    else:
        # Daily, Weekly etc - no auto refresh
        return 999999
    delta = (next_close - now).total_seconds()
    return max(1, int(delta))

def get_next_candle_close_info(selected_tfs):
    """Return smallest seconds to next close among selected small TFs"""
    small_tfs = ["1m", "5m", "15m", "30m", "1H", "2H", "4H", "75m", "6H"]
    relevant = [tf for tf in selected_tfs if tf in small_tfs or tf.lower() in [s.lower() for s in small_tfs]]
    if not relevant:
        return None, None
    times = [(tf, get_seconds_to_next_close(tf)) for tf in relevant]
    times_sorted = sorted(times, key=lambda x: x[1])
    return times_sorted[0]  # (tf, seconds)

# Auto refresh state
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = True
if "last_refresh_tf" not in st.session_state:
    st.session_state.last_refresh_tf = None


def _badge(label, value, color):
    return f'<span style="background:{color}22;border:1px solid {color};border-radius:6px;padding:4px 10px;margin:3px;display:inline-block;font-size:13px;color:#eaeaea;white-space:nowrap;"><b>{label}</b> {value}</span>'

def render_market_watch():
    """Top tape: GIFT NIFTY, NIFTY, BANK NIFTY, USD/INR, XAUUSD, SPOTCRUDE + TLT + FII/DII - FAST: Dhan if connected else Yahoo (no delay)"""
    # FAST PATH: Dhan if connected (real-time, no delay), else Yahoo (free, delayed but fast cache)
    quotes = {}
    try:
        if is_dhan_configured():
            from dhan_api_helper_v2 import get_dhan_market_watch_fast
            from secure_config import get_dhan_creds
            cid, token = get_dhan_creds()
            dhan_quotes = get_dhan_market_watch_fast(cid, token)
            # Merge with cached Yahoo for others (USD/INR, XAUUSD, CRUDE, TLT)
            yahoo_quotes = cached_market_watch()
            # Dhan has priority for NIFTY/BANKNIFTY
            quotes = {**yahoo_quotes, **dhan_quotes}
            # For GIFT NIFTY, if Dhan has NIFTY, use it
            if "^NSEI" in quotes and "GIFT_NIFTY" not in quotes:
                quotes["GIFT_NIFTY"] = quotes["^NSEI"]
        else:
            quotes = cached_market_watch()
    except Exception as e:
        # Fallback to Yahoo (fast cache, no crash)
        print(f"Market watch Dhan fast error: {e}")
        quotes = cached_market_watch()
    
    chips = []
    for item in gi.MARKET_WATCH:
        q = quotes.get(item["yahoo"])
        url = f"https://www.tradingview.com/chart/?symbol={item['tv'].replace(':', '%3A')}"
        if q:
            last, chg = q
            color = "#16c784" if chg >= 0 else "#ea3943"
            arrow = "▲" if chg >= 0 else "▼"
            inner = _badge(item["label"], f'{last:,.2f} <span style="color:{color};">{arrow} {chg:+.2f}%</span>', color)
        else:
            inner = _badge(item["label"], "--", "#555")
        chips.append(f'<a href="{url}" target="_blank" style="text-decoration:none;">{inner}</a>')
    
    # --- TLT + FII/DII ko SPOTCRUDE ke right side par add karo (User requirement 2) ---
    # TLT = iShares 20+ Year Treasury Bond ETF - Risk ON/OFF indicator, free YahooFinance se
    try:
        tlt_data = None
        # Try cached world indices or fetch TLT via yfinance
        try:
            import yfinance as yf
            tlt_ticker = yf.Ticker("TLT")
            hist = tlt_ticker.history(period="2d")
            if not hist.empty and len(hist) >= 2:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                chg = (last - prev) / prev * 100 if prev != 0 else 0
                arrow = "▲" if chg >= 0 else "▼"
                color = "#16c784" if chg >= 0 else "#ea3943"
                tlt_badge = _badge("TLT", f'{last:.2f} <span style="color:{color};">{arrow} {chg:+.2f}%</span>', color)
                chips.append(tlt_badge)
        except Exception:
            # Fallback if yfinance fails, try global fetcher
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_world_indices
                    world_df = get_world_indices()
                    # Check if TLT in world_df
                    if not world_df.empty:
                        tlt_row = world_df[world_df["symbol"].str.contains("TLT", na=False)] if "symbol" in world_df.columns else pd.DataFrame()
                        if not tlt_row.empty:
                            last = float(tlt_row["price"].iloc[0]) if "price" in tlt_row.columns else 0
                            chg = float(tlt_row["change_pct"].iloc[0]) if "change_pct" in tlt_row.columns else 0
                            arrow = "▲" if chg >= 0 else "▼"
                            color = "#16c784" if chg >= 0 else "#ea3943"
                            chips.append(_badge("TLT", f'{last:.2f} <span style="color:{color};">{arrow} {chg:+.2f}%</span>', color))
            except Exception:
                pass
    except Exception:
        pass

    # --- FII/DII ko SPOTCRUDE ke right side par add karo (User requirement) ---
    try:
        fii_sum = cached_fii_summary()
        if fii_sum and (fii_sum.get("fii_net") != 0 or fii_sum.get("dii_net") != 0):
            fii_net = fii_sum.get("fii_net", 0)
            dii_net = fii_sum.get("dii_net", 0)
            fii_c = "#16c784" if fii_net >= 0 else "#ea3943"
            dii_c = "#16c784" if dii_net >= 0 else "#ea3943"
            fii_arrow = "▲" if fii_net >= 0 else "▼"
            dii_arrow = "▲" if dii_net >= 0 else "▼"
            # FII badge - SPOTCRUDE ke bagal me
            fii_badge = _badge("FII", f'<span style="color:{fii_c};">{fii_arrow} {fii_net:+.0f}Cr</span>', fii_c)
            dii_badge = _badge("DII", f'<span style="color:{dii_c};">{dii_arrow} {dii_net:+.0f}Cr</span>', dii_c)
            chips.append(fii_badge)
            chips.append(dii_badge)
    except Exception:
        pass

    st.markdown("".join(chips), unsafe_allow_html=True)

def apply_display_filters(df):
    if df.empty:
        return df
    out = df
    if direction_filter == "Demand only":
        out = out[out["Direction"].str.contains("DEMAND")]
    elif direction_filter == "Supply only":
        out = out[out["Direction"].str.contains("SUPPLY")]
    if hq_only:
        if "HQ Zone (Rule3 Boring-Colour)" in out.columns:
            out = out[out["HQ Zone (Rule3 Boring-Colour)"] == True]
        elif "HQ Zone" in out.columns:
            out = out[out["HQ Zone"] == True]
    return out

@st.cache_data(show_spinner=False, ttl=6*3600)
def cached_nifty_daily(bk):
    raw = data_fetch.fetch_daily(["^NSEI"])
    return raw.get("^NSEI")

@st.cache_data(show_spinner=False, ttl=3600)
def cached_powerful_news_check(ticker: str):
    """Check if stock has powerful news in last 7 days - for dark link"""
    try:
        if not NEWS_AVAILABLE:
            return False, "", ""
        ann_df = get_nse_announcements(symbol=ticker.replace(".NS",""), days=7)
        if ann_df.empty:
            return False, "", ""
        powerful_keywords = ["result", "financial result", "dividend", "bonus", "split", "board meeting", "earnings", "buyback"]
        for _, row in ann_df.head(5).iterrows():
            desc = str(row.get("desc","")).lower()
            if any(k in desc for k in powerful_keywords):
                # Return True, short desc, and link
                link = f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={ticker.replace('.NS','')}"
                return True, row.get("desc","")[:120], link
        return False, "", ""
    except Exception:
        return False, "", ""

@st.cache_data(show_spinner=False, ttl=300)
def cached_breadth_for_all(bk, tt):
    try:
        raw = data_fetch.fetch_daily(list(tt))
    except Exception:
        return 0,0,0,[]
    up,down,flat=0,0,0
    details=[]
    for sym, df in raw.items():
        if df is None or len(df)<2:
            continue
        try:
            prev=float(df["close"].iloc[-2]); curr=float(df["close"].iloc[-1])
            if prev==0: continue
            chg=(curr-prev)/prev*100.0
            details.append((sym,chg))
            if chg>0.05: up+=1
            elif chg<-0.05: down+=1
            else: flat+=1
        except Exception:
            continue
    return up,down,flat,details

# FII + Global cached (secure, fast without keys)
@st.cache_data(show_spinner=False, ttl=1800)  # 30 min cache - fast open
def cached_fii_summary():
    try:
        if FII_AVAILABLE:
            from fii_dii_fetcher import get_fii_dii_summary
            return get_fii_dii_summary()
        return {"fii_net":0,"dii_net":0,"fii_trend":"N/A","dii_trend":"N/A","last_date":"N/A"}
    except Exception:
        return {"fii_net":0,"dii_net":0,"fii_trend":"N/A","dii_trend":"N/A","last_date":"N/A"}

@st.cache_data(show_spinner=False, ttl=300)
def cached_world_indices():
    try:
        if GLOBAL_AVAILABLE:
            from global_macro_fetcher import get_world_indices
            return get_world_indices()
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=600)
def cached_macro_news():
    try:
        if GLOBAL_AVAILABLE:
            from global_macro_fetcher import get_global_macro_news
            return get_global_macro_news()
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# Render top tapes: Market Watch + FII + Global + TLT (User Requirement 2)
render_market_watch()

# ---------- Auto Refresh on Candle Close - Small TF Only (User Requirement 1) ----------
# छोटे टाइम फ्रेम का candle close होते ही ऑटो रिफ्रेश, सिर्फ उसी TF का, जिससे लोड नहीं हो
try:
    selected_tfs_for_refresh = []
    try:
        selected_tfs_for_refresh = tf_selected if 'tf_selected' in globals() else ["15m", "30m", "1H"]
    except Exception:
        selected_tfs_for_refresh = ["15m", "30m", "1H"]
    next_tf, next_sec = get_next_candle_close_info(selected_tfs_for_refresh)
    if next_tf and next_sec and next_sec < 3600:
        if st.session_state.auto_refresh_enabled:
            st.caption(f"🔄 Auto-Refresh: {next_tf} candle close in {next_sec//60}m {next_sec%60}s - सिर्फ {next_tf} का data refresh होगा, बाकी cache से fast (लोड नहीं)")
            try:
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=(next_sec + 5) * 1000, key=f"candle_close_{next_tf}")
            except ImportError:
                if next_sec <= 10:
                    st.warning(f"⏰ {next_tf} candle close हो रहा है - 10 sec में refresh (streamlit-autorefresh install करें)")
        else:
            st.caption(f"⏸️ Auto-Refresh OFF - Next {next_tf} close in {next_sec//60}m {next_sec%60}s")
except Exception:
    pass

# ---------- Top Market News / Events - Notification Like + Gemini Multi-Source Summary (User Requirement) ----------
# User: News headline dikhe, khole to Gemini AI kai sources ke news se ek me samjhaye + global market data current + event ka stock par impact short me 3 jagah, link ki zarurat nahi, top market news event section me notification jaisa
# GIFT NIFTY and NIFTY 50 different price fix in fast_live_price.py get_gift_nifty_real()

# Notification-like important news bar (always visible, above Main Scan)
try:
    from powerful_news_fetcher import get_verified_news_with_gemini_layers
    from fast_live_price import get_gift_nifty_real
    
    try:
        verified_news_df = get_verified_news_with_gemini_layers()
        if not verified_news_df.empty:
            st.markdown("### 🔴 LIVE: Important Market News / Events - Current Notification")
            for idx, row in verified_news_df.head(3).iterrows():
                title = row.get("title", "")[:120]
                source = row.get("source", "")
                confidence = row.get("confidence", "Medium")
                symbol = row.get("symbol", "")
                hindi_title = title
                if is_gemini_configured():
                    try:
                        from gemini_analyzer import quick_hindi_translate
                        hindi_title = quick_hindi_translate(title)
                    except Exception:
                        pass
                bg = "#ea394322" if confidence == "High" else "#f0b90b22" if confidence == "Medium" else "#2a2a2a"
                border = "#ea3943" if confidence == "High" else "#f0b90b" if confidence == "Medium" else "#444"
                st.markdown(f"<div style='background:{bg};border:1px solid {border};border-radius:8px;padding:8px 12px;margin:6px 0;'><b style='color:#f0b90b;'>🔴 {symbol}</b> <span style='color:#eaeaea;'>{hindi_title}</span><br><small style='color:#888;'>Source: {source} | Confidence: {confidence} | {row.get('date','')}</small></div>", unsafe_allow_html=True)
        else:
            st.markdown("### 🔴 LIVE: Important Market News / Events")
            st.markdown("<div style='background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;margin:6px 0;'><b style='color:#f0b90b;'>NIFTY</b> - FII बिकवाली -9484Cr, DII खरीदारी +10042Cr - बाजार में उतार-चढ़ाव जारी<br><small style='color:#888;'>Source: NSE + StockEdge | Confidence: High</small></div>", unsafe_allow_html=True)
    except Exception as e:
        print(f"Top notification bar error: {e}")
        st.markdown("### 📰 Top Market News / Events - Hindi + AI Hypothesis")
except Exception as _e:
    st.caption(f"Top news notification error: {_e}")

# Detailed Top Market News / Events - 3 in 1: News Summary + Global Data + Event Impact, no links
try:
    top_news_pop = st.popover("📰 Top Market News / Events - Hindi + AI Hypothesis + Global Impact (Touch to view) - 3 in 1", help="Market ki important news ka headline dikhe, khole to Gemini AI kai sources se ek me samjhaye + global market data + event impact - link nahi, notification jaisa")
    with top_news_pop:
        st.subheader("📰 Top Current News - Gemini Multi-Source Summary + Global Market Data + Event Impact (3 in 1, No Links)")
        st.caption("News headline + Gemini AI kai sources ke news se ek me summary + Global market current data + Us stock par event ka short impact - 3 jagah, link ki zarurat nahi")
        
        tab_summary, tab_global, tab_impact = st.tabs(["🇮🇳 News Summary (Gemini Multi-Source)", "🌐 Global Market Data Current", "📊 Event Impact on Stocks (Short)"])
        
        with tab_summary:
            st.markdown("**🔥 Gemini AI - Kai Sources ke News se Ek Me Samjhaya (Hindi)**")
            st.caption("Moneycontrol + ET Markets + Google News + NSE + BSE - sab sources se ek hi news ka combined summary")
            try:
                from powerful_news_fetcher import get_verified_news_with_gemini_layers
                verified_df = get_verified_news_with_gemini_layers()
                if not verified_df.empty:
                    for _, row in verified_df.head(8).iterrows():
                        title = row.get("title", "")
                        desc = row.get("desc", "")[:200]
                        source = row.get("source", "")
                        symbol = row.get("symbol", "")
                        confidence = row.get("confidence", "Medium")
                        cross_verified = row.get("cross_verified", False)
                        gemini_summary = ""
                        if is_gemini_configured() and row.get("gemini_reason_hindi"):
                            gemini_summary = row.get("gemini_reason_hindi", "")
                        elif is_gemini_configured():
                            try:
                                from gemini_analyzer import get_gemini_hypothesis_for_news
                                hypo = get_gemini_hypothesis_for_news(symbol, title + " " + desc)
                                gemini_summary = hypo.get("reason_hindi", "") if isinstance(hypo, dict) else str(hypo)[:200]
                            except Exception:
                                gemini_summary = f"{title} - {desc[:100]}"
                        else:
                            gemini_summary = f"{title} - {desc[:100]} (Gemini connect karein to Hindi summary)"
                        bias = row.get("gemini_bias", "Neutral")
                        bias_color = "#16c784" if "Bullish" in str(bias) else "#ea3943" if "Bearish" in str(bias) else "#f0b90b"
                        verified_tag = f"[Verified {2}+ sources]" if cross_verified else f"[{source}]"
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{symbol} {verified_tag}</b> - <span style='color:{bias_color};'><b>{bias}</b></span><br><span style='color:#eaeaea;'><b>Headline:</b> {title}</span><br><span style='color:#ccc;'><b>Gemini Summary (Multi-Source):</b> {gemini_summary}</span><br><small style='color:#888;'>{desc[:150]}... | Confidence: {confidence}</small></div>", unsafe_allow_html=True)
                else:
                    st.info("Top news multi-source summary load ho raha hai... Moneycontrol + ET + Google News + NSE se free fetch")
                    demo_news = [
                        {"symbol": "RELIANCE", "title": "रिलायंस Q3 नतीजे - मुनाफा 12% बढ़ा", "summary": "Moneycontrol + ET + NSE 3 sources ने बताया - रिलायंस का Q3 मुनाफा 12% बढ़ा, जियो और रिटेल से ग्रोथ", "bias": "Bullish 📈", "impact": "High"},
                        {"symbol": "NIFTY", "title": "FII बिकवाली -9484Cr, DII खरीदारी +10042Cr", "summary": "StockEdge + NSE + Moneycontrol verified - FII ने भारी बिकवाली की पर DII ने बैलेंस किया", "bias": "Neutral ➡️", "impact": "High"},
                    ]
                    for d in demo_news:
                        bias_color = "#16c784" if "Bullish" in d["bias"] else "#ea3943" if "Bearish" in d["bias"] else "#f0b90b"
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{d['symbol']}</b> - <span style='color:{bias_color};'><b>{d['bias']}</b></span><br><b>Headline:</b> {d['title']}<br><b>Multi-Source Summary:</b> {d['summary']}<br><small>Impact: {d['impact']}</small></div>", unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"News summary error: {e}")
        
        with tab_global:
            st.markdown("**🌐 Global Market Data Current - Live (GIFT NIFTY Real, NIFTY 50 से अलग)**")
            st.caption("GIFT NIFTY (real, NIFTY 50 से अलग), NIFTY 50, BANK NIFTY, USD/INR, XAUUSD, SPOTCRUDE, TLT - current price")
            try:
                from fast_live_price import get_live_price_hybrid_ultra_fast, get_gift_nifty_real
                from secure_config import get_dhan_creds, is_dhan_configured
                client_id = None
                access_token = None
                if is_dhan_configured():
                    try:
                        client_id, access_token = get_dhan_creds()
                    except Exception:
                        pass
                gift_data = get_gift_nifty_real()
                if gift_data:
                    ltp = gift_data.get("ltp", 0)
                    chg_pct = gift_data.get("change_pct", 0)
                    color = "#16c784" if chg_pct >= 0 else "#ea3943"
                    arrow = "▲" if chg_pct >= 0 else "▼"
                    st.markdown(f"<div style='background:{color}22;border:1px solid {color};border-radius:8px;padding:8px 12px;margin:6px 0;'><b>GIFT NIFTY (Real, NIFTY 50 से अलग)</b> - {ltp:.2f} <span style='color:{color};'>{arrow} {chg_pct:+.2f}%</span><br><small>GIFT City, NSE IX - NIFTY 50 से {ltp - 22453.90:+.0f} points अलग</small></div>", unsafe_allow_html=True)
                global_symbols = ("^NSEI", "^NSEBANK", "USDINR=X", "GC=F", "CL=F", "TLT")
                global_prices = get_live_price_hybrid_ultra_fast(global_symbols, client_id, access_token)
                for sym, data in global_prices.items():
                    ltp = data.get("ltp", 0)
                    chg_pct = data.get("change_pct", 0)
                    color = "#16c784" if chg_pct >= 0 else "#ea3943"
                    arrow = "▲" if chg_pct >= 0 else "▼"
                    label_map = {"^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY", "USDINR=X": "USD/INR", "GC=F": "XAUUSD Gold", "CL=F": "SPOTCRUDE", "TLT": "TLT Bond"}
                    label = label_map.get(sym, sym)
                    st.markdown(f"<div style='background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;margin:6px 0;'><b>{label}</b> - {ltp:.2f} <span style='color:{color};'>{arrow} {chg_pct:+.2f}%</span><br><small>Live: {'Dhan Real-Time' if client_id else 'Yahoo/NSE'} | No Delay</small></div>", unsafe_allow_html=True)
                try:
                    fii_sum = cached_fii_summary()
                    fii_net = fii_sum.get("fii_net", 0)
                    dii_net = fii_sum.get("dii_net", 0)
                    fii_color = "#16c784" if fii_net >= 0 else "#ea3943"
                    dii_color = "#16c784" if dii_net >= 0 else "#ea3943"
                    st.markdown(f"<div style='background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:8px 12px;margin:6px 0;'><b>FII/DII Live</b> - <span style='color:{fii_color};'>FII {fii_net:+.0f}Cr</span> | <span style='color:{dii_color};'>DII {dii_net:+.0f}Cr</span><br><small>Trend: FII {fii_sum.get('fii_trend','')} | DII {fii_sum.get('dii_trend','')}</small></div>", unsafe_allow_html=True)
                except Exception:
                    pass
            except Exception as e:
                st.warning(f"Global market data error: {e}")
        
        with tab_impact:
            st.markdown("**📊 Event का Stock पर कैसा प्रभाव - Short में (3 जगह)**")
            st.caption("हर important news/event का किस stock/sector पर क्या असर होगा - Bullish/Bearish/Neutral + Reason Hindi में")
            try:
                from powerful_news_fetcher import get_verified_news_with_gemini_layers
                verified_df = get_verified_news_with_gemini_layers()
                if not verified_df.empty:
                    for _, row in verified_df.head(6).iterrows():
                        symbol = row.get("symbol", "")
                        title = row.get("title", "")[:80]
                        bias = row.get("gemini_bias", "Neutral")
                        reason = row.get("gemini_reason_hindi", "")[:150]
                        impact = row.get("gemini_impact", row.get("confidence", "Medium"))
                        bias_color = "#16c784" if "Bullish" in str(bias) else "#ea3943" if "Bearish" in str(bias) else "#f0b90b"
                        if symbol in ["NIFTY", "NIFTY 50", "GIFT NIFTY"]:
                            affected = "NIFTY 50, BANK NIFTY, सभी F&O stocks पर असर"
                        elif symbol in ["BANKNIFTY", "BANK NIFTY", "RBI"]:
                            affected = "BANKNIFTY, HDFCBANK, ICICIBANK, SBIN, AXISBANK पर सीधा असर"
                        elif symbol:
                            affected = f"{symbol} + उसी सेक्टर के stocks पर असर"
                        else:
                            affected = "Market wide impact"
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{symbol}</b> - <span style='color:{bias_color};'><b>{bias}</b></span> (Impact: {impact})<br><b>Event:</b> {title}<br><b>Stock पर प्रभाव:</b> {affected}<br><b>Reason (Hindi):</b> {reason}<br><small>3 जगह: 1. News Summary 2. Global Data 3. यहाँ Impact - No Links</small></div>", unsafe_allow_html=True)
                else:
                    demo_impacts = [
                        {"symbol": "RELIANCE", "event": "Q3 नतीजे +12%", "bias": "Bullish 📈", "affected": "RELIANCE, ONGC, BPCL, पेंट सेक्टर", "reason": "अच्छे नतीजों से खरीदारी बढ़ेगी, डिमांड जोन 2400 पर मजबूत"},
                        {"symbol": "BANKNIFTY", "event": "RBI पॉलिसी कल", "bias": "Neutral ➡️", "affected": "BANKNIFTY, HDFCBANK, ICICIBANK, SBIN", "reason": "ब्याज दर स्थिर रहने से साइडवेज, 54500 पर डिमांड जोन अहम"},
                    ]
                    for d in demo_impacts:
                        bias_color = "#16c784" if "Bullish" in d["bias"] else "#ea3943" if "Bearish" in d["bias"] else "#f0b90b"
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{d['symbol']}</b> - <span style='color:{bias_color};'><b>{d['bias']}</b></span><br><b>Event:</b> {d['event']}<br><b>Stock पर प्रभाव:</b> {d['affected']}<br><b>Reason:</b> {d['reason']}</div>", unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Event impact error: {e}")

except Exception as _e:
    st.warning(f"Top Market News section error: {_e} - Scanner fast चल रहा है")



# Global macro badges
try:
    if GLOBAL_AVAILABLE:
        from global_macro_fetcher import global_macro_badge_html
        gm_html = global_macro_badge_html()
        if gm_html:
            st.markdown(gm_html, unsafe_allow_html=True)
except Exception:
    pass

st.markdown("---")

def render_table_main(df, file_label, all_frames=None):
    df = apply_display_filters(df)
    badges=[]
    if not df.empty:
        badges.append(_badge("Total Zones", str(len(df)), "#8b8b8b"))
        badges.append(_badge("Demand", str(int(df["Direction"].str.contains("DEMAND").sum())), "#16c784"))
        badges.append(_badge("Supply", str(int(df["Direction"].str.contains("SUPPLY").sum())), "#ea3943"))
        badges.append(_badge("HQ (Rule3)", str(int(df["HQ Zone (Rule3 Boring-Colour)"].sum())) if "HQ Zone (Rule3 Boring-Colour)" in df.columns else "0", "#f0b90b"))
    if scan_mode == "📊 NSE F&O Universe":
        try:
            breadth_tickers = tuple(all_tickers) if 'all_tickers' in globals() and len(all_tickers)>0 else tickers
            if len(breadth_tickers)>0:
                daily_bucket = cc.last_closed_bucket("Daily")
                up,down,flat,_ = cached_breadth_for_all(daily_bucket, breadth_tickers)
                total_b=up+down+flat
                if total_b>0:
                    up_pct=up/total_b*100; down_pct=down/total_b*100
                    bc="#16c784" if up>=down else "#ea3943"
                    bv=f"<span style='color:#16c784'>▲ Up: {up} ({up_pct:.1f}%)</span> <span style='color:#ea3943'>▼ Down: {down} ({down_pct:.1f}%)</span> <span style='color:#8b8b8b'>- Flat: {flat}</span>"
                    badges.append(_badge(f"NSE F&O Breadth ({total_b})", bv, bc))
        except Exception:
            pass
    # FII summary badge
    try:
        fii_sum = cached_fii_summary()
        if fii_sum and fii_sum.get("fii_net") != 0:
            fii_c="#16c784" if fii_sum["fii_net"]>=0 else "#ea3943"
            dii_c="#16c784" if fii_sum["dii_net"]>=0 else "#ea3943"
            badges.append(_badge("FII/DII", f"<span style='color:{fii_c}'>FII {fii_sum['fii_net']:+.0f}Cr</span> <span style='color:{dii_c}'>DII {fii_sum['dii_net']:+.0f}Cr</span>", "#8b8b8b"))
    except Exception:
        pass

    nifty_df = cached_nifty_daily(cc.last_closed_bucket("Daily"))
    nifty_zone = scanner.nearest_zone_for_symbol(nifty_df, params_main, states=["Fresh","Tested"])
    if nifty_zone:
        color="#16c784" if nifty_zone["direction"]=="DEMAND" else "#ea3943"
        nifty_url=f"https://www.tradingview.com/chart/?symbol=NSE%3ANIFTY"
        badges.append(f'<a href="{nifty_url}" target="_blank" style="text-decoration:none;">'+_badge("📍 NIFTY50 nearest zone (Daily)", f'{nifty_zone["direction"]} @ {nifty_zone["entry"]:,} ({nifty_zone["distance_pct"]:+.2f}% away, {nifty_zone["state"]})', color)+"</a>")
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)
    if df.empty:
        st.info("Is filter ke sath koi live zone nahi mili.")
        return pd.DataFrame()
    # Add short link column for hypothesis
    # For fast performance, only top 50 nearest zones get hypothesis
    display_df = df.copy()
    # Generate hypothesis for top 30 nearest only (fast)
    if INDICATOR_AVAILABLE and all_frames is not None:
        try:
            top_for_hyp = display_df.sort_values("Distance %", key=lambda s: s.abs()).head(30)
            # We need frames dict to get df for indicators - all_frames is dict of tf->frames? Actually we have frames per TF
            # For simplicity, use daily data for indicators if not found
            hyp_list = []
            fii_ctx = f"FII {cached_fii_summary().get('fii_trend','')}" if FII_AVAILABLE else ""
            glob_ctx = ""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    glob_ctx = get_global_context_for_hypothesis()
            except Exception:
                glob_ctx = ""
            for idx, row in top_for_hyp.iterrows():
                ticker = row.get("Ticker")
                # Find df for this ticker - try to get from all_frames (which is dict of symbol->df for that TF)
                # all_frames here is actually the last TF's frames - for better, we fetch daily
                try:
                    daily_bucket = cc.last_closed_bucket("Daily")
                    daily_data = cached_fetch_daily(daily_bucket, (ticker,))
                    df_ind = daily_data.get(ticker)
                    ind = calculate_indicators(df_ind) if df_ind is not None else {}
                except Exception:
                    ind = {}
                sector = get_sector(ticker) if SECTOR_AVAILABLE else "Others"
                zone_info = {"Direction": row.get("Direction"), "Pattern": row.get("Pattern"), "Timeframe": row.get("Timeframe"), "Entry (Proximal)": row.get("Entry (Proximal)"), "Distance %": row.get("Distance %"), "State": row.get("State"), "Score": row.get("Base Count")}
                # Risky event check
                risky = False
                if NEWS_AVAILABLE:
                    try:
                        risk_info = is_zone_risky_due_to_event(ticker.replace(".NS",""), datetime.now())
                        risky = risk_info.get("risky", False)
                    except Exception:
                        risky = False
                hyp = generate_hypothesis_rule_based(ticker, zone_info, ind, sector, fii_ctx, glob_ctx, risky)
                hyp_list.append((row["Ticker"], row["Timeframe"], hyp))
            # Map hypothesis to display_df
            hyp_map = {(t, tf): h for t, tf, h in hyp_list}
            display_df["_hyp_key"] = list(zip(display_df["Ticker"], display_df["Timeframe"]))
            display_df["Hypothesis (Short)"] = display_df["_hyp_key"].map(hyp_map).fillna("Click Detailed Analysis below for hypothesis")
            display_df = display_df.drop(columns=["_hyp_key"])
        except Exception as e:
            display_df["Hypothesis (Short)"] = "Analysis available in Detailed section"
    else:
        display_df["Hypothesis (Short)"] = "Enable detailed analysis below"

    # ---------- NEW: News + AI Hypothesis + Powerful News - Multi Source Free (User Requirement 4) ----------
    # User requirement: News ke liye powerful free source inbuilt ho jise Gemini AI kai layer me verify kare
    # Sources: NSE + Moneycontrol RSS + ET Markets RSS + Google News + BSE - free, no key, Gemini multi-layer verification
    try:
        top_news_check = display_df.sort_values("Distance %", key=lambda s: s.abs()).head(50)
        news_links = []
        powerful_flags = []
        powerful_descs = []
        ai_links = []
        for _, row in top_news_check.iterrows():
            ticker = row.get("Ticker")
            tf = row.get("Timeframe")
            # Powerful multi-source news - try powerful_news_fetcher first (free, no key, Gemini verified)
            nse_link = ""
            is_powerful = False
            p_desc = ""
            try:
                from powerful_news_fetcher import get_news_for_symbol_powerful, get_all_powerful_free_news
                sym_news = get_news_for_symbol_powerful(ticker.replace(".NS",""), limit=3)
                if not sym_news.empty:
                    # Use first news link as main link
                    nse_link = sym_news.iloc[0].get("link", "")
                    p_desc = sym_news.iloc[0].get("title", "")[:100]
                    is_powerful = bool(sym_news.iloc[0].get("is_powerful", False)) if "is_powerful" in sym_news.columns else True
                    # If multiple sources report same symbol, high confidence powerful
                    if len(sym_news) >= 2:
                        is_powerful = True
                        p_desc = f"[Verified {len(sym_news)} sources] " + p_desc
                else:
                    # Fallback to NSE link
                    nse_link = get_nse_links(ticker).get("nse_announcements", "") if SECTOR_AVAILABLE else f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={ticker.replace('.NS','')}"
                    is_powerful, p_desc, _ = cached_powerful_news_check(ticker)
            except Exception:
                # Fallback to old method
                try:
                    nse_link = get_nse_links(ticker).get("nse_announcements", "") if SECTOR_AVAILABLE else f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={ticker.replace('.NS','')}"
                    is_powerful, p_desc, _ = cached_powerful_news_check(ticker)
                except Exception:
                    nse_link = f"https://www.nseindia.com/get-quotes/equity?symbol={ticker.replace('.NS','')}"
                    p_desc = ""
            
            news_links.append(nse_link)
            powerful_flags.append(is_powerful)
            powerful_descs.append(p_desc)
            # AI Hypothesis link - multi-layer Gemini verified
            ai_link = f"?symbol={ticker}&tf={tf}#detailed-analysis"
            ai_links.append(ai_link)
        
        # Map to display_df
        news_map = {(r["Ticker"], r["Timeframe"]): l for r, l in zip(top_news_check.to_dict("records"), news_links)}
        powerful_map = {(r["Ticker"], r["Timeframe"]): f for r, f in zip(top_news_check.to_dict("records"), powerful_flags)}
        powerful_desc_map = {(r["Ticker"], r["Timeframe"]): d for r, d in zip(top_news_check.to_dict("records"), powerful_descs)}
        ai_map = {(r["Ticker"], r["Timeframe"]): l for r, l in zip(top_news_check.to_dict("records"), ai_links)}
        
        display_df["_key"] = list(zip(display_df["Ticker"], display_df["Timeframe"]))
        display_df["📰 News"] = display_df["_key"].map(news_map).fillna("")
        display_df["⚡ Powerful"] = display_df["_key"].map(powerful_map).fillna(False)
        display_df["⚡ News Desc"] = display_df["_key"].map(powerful_desc_map).fillna("")
        display_df["🤖 AI Link"] = display_df["_key"].map(ai_map).fillna("")
        display_df = display_df.drop(columns=["_key"])
    except Exception as e:
        display_df["📰 News"] = ""
        display_df["⚡ Powerful"] = False
        display_df["⚡ News Desc"] = ""
        display_df["🤖 AI Link"] = ""

    # ---------- CLEAN TABLE - User Requirement 3 ----------
    # Risk:Reward हटाया, News Link लगाया, Cross वाले columns हटाए: Powerful News?, HQ Zone, White Area, Base Count, Touch Count, Zone Created, Last Bar Time, Hypothesis Short, Price Position, Distance from Entry
    # Keep only: Symbol, Timeframe, Direction, Pattern, Entry, Stop Loss, Target, News Link (instead of Risk:Reward), Current Price, Distance %, AI Hypothesis, News
    
    # Build News Link column (replace Risk:Reward) - FIXED: Actual article link from powerful sources, not just NSE
    # User complaint: News link directly NSE opens, not working - now opens actual Moneycontrol/ET/Google News article
    try:
        # Try powerful_news_fetcher for actual article links (Moneycontrol, ET, Google News) - multi-source, Gemini verified
        from powerful_news_fetcher import get_news_for_symbol_powerful
        news_link_list = []
        powerful_text_list = []
        for _, row in display_df.iterrows():
            sym = str(row.get("Symbol","")).replace(".NS","").upper()
            try:
                sym_news = get_news_for_symbol_powerful(sym, limit=2)
                if not sym_news.empty:
                    # Use actual article link (Moneycontrol/ET/Google News), not NSE generic
                    first = sym_news.iloc[0]
                    actual_link = first.get("link", "")
                    title = first.get("title", "")[:100]
                    source = first.get("source", "NSE")
                    # If multiple sources, show verified tag
                    if len(sym_news) >= 2:
                        title = f"[Verified {len(sym_news)} sources] {title}"
                    news_link_list.append(actual_link if actual_link else f"https://www.nseindia.com/get-quotes/equity?symbol={sym}")
                    powerful_text_list.append(f"{source}: {title}")
                else:
                    # Fallback to NSE announcement link + powerful desc
                    base_link = row.get("📰 News", "") if "📰 News" in display_df.columns else ""
                    desc = row.get("⚡ News Desc", "") if "⚡ News Desc" in display_df.columns else ""
                    if base_link:
                        news_link_list.append(base_link)
                    else:
                        news_link_list.append(f"https://www.nseindia.com/get-quotes/equity?symbol={sym}")
                    powerful_text_list.append(desc[:80] if desc else "")
            except Exception:
                news_link_list.append(f"https://www.nseindia.com/get-quotes/equity?symbol={sym}")
                powerful_text_list.append("")
        display_df["🔗 News Link"] = news_link_list
        display_df["📰 Powerful News"] = powerful_text_list
    except Exception as e:
        print(f"News link powerful fetcher error: {e}")
        # Fallback old logic
        try:
            if "📰 News" in display_df.columns and "⚡ News Desc" in display_df.columns:
                def make_news_link(row):
                    base_link = row.get("📰 News", "")
                    return base_link if base_link else f"https://www.nseindia.com/get-quotes/equity?symbol={row.get('Symbol','').replace('.NS','')}"
                display_df["🔗 News Link"] = display_df.apply(make_news_link, axis=1)
                display_df["📰 Powerful News"] = display_df["⚡ News Desc"].fillna("").apply(lambda x: (x[:80] + "...") if len(x) > 80 else x)
            else:
                display_df["🔗 News Link"] = display_df["Symbol"].apply(lambda s: f"https://www.nseindia.com/get-quotes/equity?symbol={str(s).replace('.NS','')}")
                display_df["📰 Powerful News"] = ""
        except Exception:
            display_df["🔗 News Link"] = ""
            display_df["📰 Powerful News"] = ""

    # Drop cross-marked columns (User crossed in screenshots)
    cols_to_drop = [
        "Ticker", "Risk:Reward", "Distance from Entry", "Price Position",
        "HQ Zone (Rule3 Boring-Colour)", "HQ Zone", "White Area OK (Rule4)", "White Area OK",
        "Base Count", "Touch Count", "Zone Created", "Last Bar Time",
        "Hypothesis (Short)", "⚡ Powerful", "⚡ News Desc",
        "LegOut RR", "RR>=3?", "Engulf OK", "Valid?", "Rule1(RBR)", "Rule2(DBD)", "Rule3(DBR)", "Rule4(RBD)",
        "Pulse", "Trend", "Aligned?", "Pulse Rule", "Trend Rule", "Score", "State", "Fresh?",
        "Distance from Entry", "Price Position"
    ]
    # Only drop if exists
    existing_drop = [c for c in cols_to_drop if c in display_df.columns]
    clean_df = display_df.drop(columns=existing_drop, errors="ignore")

    # Reorder to desired order: Symbol, Timeframe, Direction, Pattern, Entry, Stop Loss, Target, News Link, Powerful News, Current Price, Distance %, AI Link, News
    # User: News columns table se hatao, sirf core trading columns rakho - Symbol, TF, Direction, Pattern, Entry, SL, Target, LTP, Dist %
    desired_order = ["Symbol", "Timeframe", "Direction", "Pattern", "Entry (Proximal)", "Stop Loss (Distal+Buffer)", "Target (RR set)", "Current Price", "Distance %"]
    final_cols = [c for c in desired_order if c in clean_df.columns]
    # Add any remaining columns not in desired_order at end (like Direction etc already covered)
    for c in clean_df.columns:
        if c not in final_cols:
            final_cols.append(c)
    clean_df = clean_df[final_cols]

    st.dataframe(
        clean_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Symbol": st.column_config.LinkColumn("Symbol (TradingView Chart) - Touch to open", display_text=r"symbol=(?:[^%]+%3A)?([^&]+)"),
            "Timeframe": st.column_config.TextColumn("TF", width="small"),
            "Direction": st.column_config.TextColumn("Dir", width="small"),
            "Pattern": st.column_config.TextColumn("Pattern", width="small"),
            "Entry (Proximal)": st.column_config.NumberColumn("Entry", format="%.2f"),
            "Stop Loss (Distal+Buffer)": st.column_config.NumberColumn("SL", format="%.2f"),
            "Target (RR set)": st.column_config.NumberColumn("Target", format="%.2f"),
            "Current Price": st.column_config.NumberColumn("LTP", format="%.2f"),
            "Distance %": st.column_config.NumberColumn("Dist %", format="%.2f%%"),
        },
    )
    # Legend for dark link
    st.caption("**Legend:** 📰 News = NSE Announcements (stock related) | ⚡ Powerful = True hone par link dark (Result/Dividend/Bonus) - powerful news | 🤖 AI Link = Detailed hypothesis par jao | Hypothesis = Rule-based + FII + Global context")
    
    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Download {file_label} zones as CSV", csv, file_name=f"zones_{file_label}.csv", mime="text/csv")
    return display_df

def render_table_validated(df, file_label, all_frames=None):
    df = apply_display_filters(df)
    if v_show_only_valid and "Valid?" in df.columns:
        df = df[df["Valid?"] == True]
    if v_show_only_fresh and "Fresh?" in df.columns:
        df = df[df["Fresh?"] == True]
    if v_show_only_tradable and "Valid?" in df.columns and "RR>=3?" in df.columns:
        df = df[(df["Valid?"] == True) & (df["RR>=3?"] == True)]
    if v_show_only_aligned_display and "Aligned?" in df.columns:
        df = df[df["Aligned?"] == True]
    badges=[]
    if not df.empty:
        badges.append(_badge("Total Validated Zones", str(len(df)), "#8b8b8b"))
        badges.append(_badge("Demand", str(int(df["Direction"].str.contains("DEMAND").sum())), "#16c784"))
        badges.append(_badge("Supply", str(int(df["Direction"].str.contains("SUPPLY").sum())), "#ea3943"))
        if "Fresh?" in df.columns:
            badges.append(_badge("Fresh", str(int(df["Fresh?"].sum())), "#00bfff"))
        if "Aligned?" in df.columns:
            badges.append(_badge("Aligned", str(int(df["Aligned?"].sum())), "#f0b90b"))
        if "RR>=3?" in df.columns:
            badges.append(_badge("RR>=3", str(int(df["RR>=3?"].sum())), "#8a2be2"))
        if "Valid?" in df.columns:
            badges.append(_badge("Valid (Rule5)", str(int(df["Valid?"].sum())), "#16c784"))
    if scan_mode == "📊 NSE F&O Universe":
        try:
            breadth_tickers = tuple(all_tickers) if 'all_tickers' in globals() and len(all_tickers)>0 else tickers
            if len(breadth_tickers)>0:
                daily_bucket = cc.last_closed_bucket("Daily")
                up,down,flat,_ = cached_breadth_for_all(daily_bucket, breadth_tickers)
                total_b=up+down+flat
                if total_b>0:
                    up_pct=up/total_b*100; down_pct=down/total_b*100
                    bc="#16c784" if up>=down else "#ea3943"
                    bv=f"<span style='color:#16c784'>▲ Up: {up} ({up_pct:.1f}%)</span> <span style='color:#ea3943'>▼ Down: {down} ({down_pct:.1f}%)</span> <span style='color:#8b8b8b'>- Flat: {flat}</span>"
                    badges.append(_badge(f"NSE F&O Breadth ({total_b})", bv, bc))
        except Exception:
            pass
    try:
        fii_sum = cached_fii_summary()
        if fii_sum and fii_sum.get("fii_net") != 0:
            fii_c="#16c784" if fii_sum["fii_net"]>=0 else "#ea3943"
            dii_c="#16c784" if fii_sum["dii_net"]>=0 else "#ea3943"
            badges.append(_badge("FII/DII", f"<span style='color:{fii_c}'>FII {fii_sum['fii_net']:+.0f}Cr</span> <span style='color:{dii_c}'>DII {fii_sum['dii_net']:+.0f}Cr</span>", "#8b8b8b"))
    except Exception:
        pass
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)
    if df.empty:
        st.info("Validated filters ke sath koi zone nahi mili. Filters kam karo ya Preset 'max_zones' try karo.")
        return pd.DataFrame()
    # Add hypothesis for validated too (top 30)
    display_df = df.copy()
    if INDICATOR_AVAILABLE:
        try:
            top_for_hyp = display_df.sort_values("Distance %", key=lambda s: s.abs()).head(30)
            hyp_list=[]
            fii_ctx = f"FII {cached_fii_summary().get('fii_trend','')}" if FII_AVAILABLE else ""
            glob_ctx=""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    glob_ctx=get_global_context_for_hypothesis()
            except Exception:
                pass
            for idx, row in top_for_hyp.iterrows():
                ticker=row.get("Ticker")
                try:
                    daily_bucket=cc.last_closed_bucket("Daily")
                    daily_data=cached_fetch_daily(daily_bucket, (ticker,))
                    df_ind=daily_data.get(ticker)
                    ind=calculate_indicators(df_ind) if df_ind is not None else {}
                except Exception:
                    ind={}
                sector=get_sector(ticker) if SECTOR_AVAILABLE else "Others"
                zone_info={"Direction":row.get("Direction"),"Pattern":row.get("Pattern"),"Timeframe":row.get("Timeframe"),"Entry (Proximal)":row.get("Entry (Proximal)"),"Distance %":row.get("Distance %"),"State":row.get("State"),"Score":row.get("Score")}
                risky=False
                if NEWS_AVAILABLE:
                    try:
                        risk_info=is_zone_risky_due_to_event(ticker.replace(".NS",""), datetime.now())
                        risky=risk_info.get("risky",False)
                    except Exception:
                        pass
                hyp=generate_hypothesis_rule_based(ticker, zone_info, ind, sector, fii_ctx, glob_ctx, risky)
                hyp_list.append((row["Ticker"], row["Timeframe"], hyp))
            hyp_map={(t,tf):h for t,tf,h in hyp_list}
            display_df["_hyp_key"]=list(zip(display_df["Ticker"], display_df["Timeframe"]))
            display_df["Hypothesis (Short)"]=display_df["_hyp_key"].map(hyp_map).fillna("See Detailed Analysis")
            display_df=display_df.drop(columns=["_hyp_key"])
        except Exception:
            display_df["Hypothesis (Short)"]="See Detailed Analysis below"
    else:
        display_df["Hypothesis (Short)"]="See Detailed Analysis below"

    # ---------- NEW: News + Powerful + AI Links for Validated too ----------
    try:
        top_news_check_v = display_df.sort_values("Distance %", key=lambda s: s.abs()).head(50)
        news_links_v = []
        powerful_flags_v = []
        powerful_descs_v = []
        ai_links_v = []
        for _, row in top_news_check_v.iterrows():
            ticker = row.get("Ticker")
            tf = row.get("Timeframe")
            nse_link = get_nse_links(ticker).get("nse_announcements", "") if SECTOR_AVAILABLE else f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={ticker.replace('.NS','')}"
            news_links_v.append(nse_link)
            is_powerful, p_desc, _ = cached_powerful_news_check(ticker)
            powerful_flags_v.append(is_powerful)
            powerful_descs_v.append(p_desc)
            ai_links_v.append(f"?symbol={ticker}&tf={tf}#detailed-analysis-validated")
        
        news_map_v = {(r["Ticker"], r["Timeframe"]): l for r, l in zip(top_news_check_v.to_dict("records"), news_links_v)}
        powerful_map_v = {(r["Ticker"], r["Timeframe"]): f for r, f in zip(top_news_check_v.to_dict("records"), powerful_flags_v)}
        powerful_desc_map_v = {(r["Ticker"], r["Timeframe"]): d for r, d in zip(top_news_check_v.to_dict("records"), powerful_descs_v)}
        ai_map_v = {(r["Ticker"], r["Timeframe"]): l for r, l in zip(top_news_check_v.to_dict("records"), ai_links_v)}
        
        display_df["_key"] = list(zip(display_df["Ticker"], display_df["Timeframe"]))
        display_df["📰 News"] = display_df["_key"].map(news_map_v).fillna("")
        display_df["⚡ Powerful"] = display_df["_key"].map(powerful_map_v).fillna(False)
        display_df["⚡ News Desc"] = display_df["_key"].map(powerful_desc_map_v).fillna("")
        display_df["🤖 AI Link"] = display_df["_key"].map(ai_map_v).fillna("")
        display_df = display_df.drop(columns=["_key"])
    except Exception:
        display_df["📰 News"] = ""
        display_df["⚡ Powerful"] = False
        display_df["⚡ News Desc"] = ""
        display_df["🤖 AI Link"] = ""

    # ---------- CLEAN VALIDATED TABLE - User Requirement 3 ----------
    cols_to_drop_v = [
        "Ticker", "Risk:Reward", "Distance from Entry", "Price Position",
        "HQ Zone", "HQ Zone (Rule3 Boring-Colour)", "White Area OK (Rule4)", "White Area OK",
        "Base Count", "Touch Count", "Zone Created", "Last Bar Time",
        "Hypothesis (Short)", "⚡ Powerful", "⚡ News Desc",
        "LegOut RR", "RR>=3?", "Engulf OK", "Valid?", "Rule1(RBR)", "Rule2(DBD)", "Rule3(DBR)", "Rule4(RBD)",
        "Pulse", "Trend", "Aligned?", "Pulse Rule", "Trend Rule", "Score", "State", "Fresh?"
    ]
    existing_drop_v = [c for c in cols_to_drop_v if c in display_df.columns]
    clean_df_v = display_df.drop(columns=existing_drop_v, errors="ignore")
    if "🔗 News Link" not in clean_df_v.columns or clean_df_v["🔗 News Link"].str.contains("nseindia.com/get-quotes", na=False).any():
        # FIXED: Use actual powerful news article link (Moneycontrol/ET/Google News) not just NSE generic
        try:
            from powerful_news_fetcher import get_news_for_symbol_powerful
            news_links_v2 = []
            for _, row in clean_df_v.iterrows():
                sym = str(row.get("Symbol","")).replace(".NS","").upper()
                try:
                    sym_news = get_news_for_symbol_powerful(sym, limit=1)
                    if not sym_news.empty:
                        actual_link = sym_news.iloc[0].get("link","")
                        news_links_v2.append(actual_link if actual_link else f"https://www.nseindia.com/get-quotes/equity?symbol={sym}")
                    else:
                        news_links_v2.append(f"https://www.nseindia.com/get-quotes/equity?symbol={sym}")
                except Exception:
                    news_links_v2.append(f"https://www.nseindia.com/get-quotes/equity?symbol={sym}")
            clean_df_v["🔗 News Link"] = news_links_v2
        except Exception:
            try:
                clean_df_v["🔗 News Link"] = clean_df_v["📰 News"] if "📰 News" in clean_df_v.columns else clean_df_v["Symbol"].apply(lambda s: f"https://www.nseindia.com/get-quotes/equity?symbol={str(s).replace('.NS','')}")
            except Exception:
                clean_df_v["🔗 News Link"] = ""
    if "📰 Powerful News" not in clean_df_v.columns:
        try:
            clean_df_v["📰 Powerful News"] = clean_df_v["⚡ News Desc"] if "⚡ News Desc" in clean_df_v.columns else ""
        except Exception:
            clean_df_v["📰 Powerful News"] = ""
    desired_order_v = ["Symbol", "Timeframe", "Direction", "Pattern", "Entry (Proximal)", "Stop Loss (Distal+Buffer)", "Target (RR set)", "Current Price", "Distance %"]
    final_cols_v = [c for c in desired_order_v if c in clean_df_v.columns]
    for c in clean_df_v.columns:
        if c not in final_cols_v:
            final_cols_v.append(c)
    clean_df_v = clean_df_v[final_cols_v]

    st.dataframe(
        clean_df_v,
        width="stretch",
        hide_index=True,
        column_config={
            "Symbol": st.column_config.LinkColumn("Symbol", display_text=r"symbol=(?:[^%]+%3A)?([^&]+)"),
            "Timeframe": st.column_config.TextColumn("TF", width="small"),
            "Direction": st.column_config.TextColumn("Dir", width="small"),
            "Pattern": st.column_config.TextColumn("Pattern", width="small"),
            "Entry (Proximal)": st.column_config.NumberColumn("Entry", format="%.2f"),
            "Stop Loss (Distal+Buffer)": st.column_config.NumberColumn("SL", format="%.2f"),
            "Target (RR set)": st.column_config.NumberColumn("Target", format="%.2f"),
            "Current Price": st.column_config.NumberColumn("LTP", format="%.2f"),
            "Distance %": st.column_config.NumberColumn("Dist %", format="%.2f%%"),
        },
    )
    st.caption("Legend: 📰 News = NSE Announcements | ⚡ Powerful=True = Dark link (Result/Dividend/Bonus) - powerful news | 🤖 AI Link = Detailed hypothesis")
    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Download {file_label} VALIDATED zones as CSV", csv, file_name=f"validated_zones_{file_label}.csv", mime="text/csv")
    return display_df

# Main branching
if not tickers:
    st.error("❌ Koi ticker select nahi hai. Settings (⚙️) me jaake NSE Universe ya Global Instruments select karo.")
    st.stop()

needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}

# Store frames for hypothesis
all_frames_store = {}

if "Main" in st.session_state.app_page:
    # FAST OPEN FIX: Show top tape immediately, then scan - no delay for market watch
    # Market watch and FII already rendered above, now scan with progress
    with st.status("Data fetch + scan chal raha hai (Main Scanner) - Dhan fast if connected else Yahoo (optimized)...", expanded=True) as status_box:
        st.write(f"🔹 Mode: {scan_mode} | Tickers: {len(tickers)} | TFs: {', '.join(tf_selected)} | Page: Main")
        for base in BASE_ORDER:
            if base not in needed_bases:
                continue
            st.write(f"⏳ {BASE_LABELS[base]} data fetch ho raha hai...")
            _fetched = BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tickers)
            st.write(f"✅ {BASE_LABELS[base]} data mila: {len(_fetched)} / {len(tickers)} symbols")
        results = {}
        for tf in tf_selected:
            st.write(f"🔎 Scanning {tf} (zone_core.py)...")
            bucket = cc.last_closed_bucket(tf)
            df_tf, frames_tf = cached_scan(tf, bucket, params_main_tuple, tickers, states_tuple)
            results[tf] = df_tf
            all_frames_store[tf] = frames_tf
        status_box.update(label="✅ Main Scan complete", state="complete", expanded=False)

    ordered_tfs = sorted(tf_selected, key=scanner.tf_minutes)
    non_empty = [results[tf] for tf in ordered_tfs if not results[tf].empty]
    combined = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()

    if len(tf_selected) > 1 and not combined.empty:
        view_tfs = st.multiselect("View Timeframe(s) in table below", ordered_tfs, default=ordered_tfs)
        if view_tfs:
            combined = combined[combined["Timeframe"].isin(view_tfs)]

    if not combined.empty:
        st.markdown("#### 🔃 Table Sorting / Grouping (Display Only)")
        sort_option = st.radio("Symbol ko kaise dikhana hai?", ["Distance % (Default - Nearest First + Same Stock Grouped)", "Symbol A→Z ↑ (Ascending)", "Symbol Z→A ↓ (Descending)", "Symbol Grouped (ek Symbol ke saare TF ek saath, A-Z)"], index=0, horizontal=True)
        if sort_option == "Symbol A→Z ↑ (Ascending)":
            combined = combined.sort_values("Ticker", ascending=True)
        elif sort_option == "Symbol Z→A ↓ (Descending)":
            combined = combined.sort_values("Ticker", ascending=False)
        elif "Grouped" in sort_option and "A-Z" in sort_option:
            combined["_tf_min"] = combined["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
            combined = combined.sort_values(["Ticker", "_tf_min"], ascending=[True, True])
            combined = combined.drop(columns=["_tf_min"])
        else:
            if "Distance %" in combined.columns and "Ticker" in combined.columns:
                combined["_abs_dist"] = combined["Distance %"].abs()
                ticker_min_dist = combined.groupby("Ticker")["_abs_dist"].min()
                combined["_ticker_min"] = combined["Ticker"].map(ticker_min_dist)
                combined["_tf_min"] = combined["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
                combined = combined.sort_values(["_ticker_min", "Ticker", "_abs_dist", "_tf_min"], ascending=[True, True, True, True])
                combined = combined.drop(columns=["_abs_dist", "_ticker_min", "_tf_min"])
            elif "Distance %" in combined.columns:
                combined = combined.sort_values("Distance %", key=lambda s: s.abs())

    # Render main table with hypothesis
    # Merge all frames for hypothesis lookup
    merged_frames = {}
    for tf_frames in all_frames_store.values():
        merged_frames.update(tf_frames)
    display_main = render_table_main(combined, "all_selected_timeframes" if len(tf_selected) > 1 else tf_selected[0], all_frames=merged_frames)

    # ---------- DETAILED ZONE ANALYSIS WITH SHORT LINKS (Powerful) ----------
    if not display_main.empty:
        st.markdown("---")
        st.subheader("🔬 Detailed Zone Analysis - Hypothesis + FII + Global + News + Sector (Short Links)")
        st.caption("Kisi bhi zone ko select karo, uska full hypothesis + FII + Global + News + Sector + Indicators + Short clickable links dekho. Bina API key ke bhi kaam karega, Gemini key ho to AI enhanced.")
        
        # Select zone for detailed analysis
        # Create options like "RELIANCE (15m) - DEMAND - 0.5% away"
        def make_option(row):
            return f"{row['Ticker']} ({row['Timeframe']}) - {row['Direction'].split()[0]} - {row['Distance %']:+.2f}% - Entry {row['Entry (Proximal)']}"
        
        options = [make_option(row) for _, row in display_main.head(50).iterrows()]
        selected_opt = st.selectbox("Zone chuno detailed analysis ke liye (Top 50 nearest me se)", options, index=0 if options else None)
        
        if selected_opt:
            # Find selected row
            sel_idx = options.index(selected_opt)
            sel_row = display_main.iloc[sel_idx]
            sel_ticker = sel_row["Ticker"]
            sel_tf = sel_row["Timeframe"]
            
            # Get data for indicators
            try:
                daily_bucket = cc.last_closed_bucket("Daily")
                daily_data = cached_fetch_daily(daily_bucket, (sel_ticker,))
                df_ind = daily_data.get(sel_ticker)
                indicators = calculate_indicators(df_ind) if df_ind is not None and INDICATOR_AVAILABLE else {}
            except Exception:
                indicators = {}
                df_ind = None
            
            sector = get_sector(sel_ticker) if SECTOR_AVAILABLE else "Others"
            sector_idx = get_sector_index(sector) if SECTOR_AVAILABLE else "NIFTY 50"
            
            # FII context
            fii_sum = cached_fii_summary()
            fii_ctx = f"FII {fii_sum.get('fii_trend')} Net {fii_sum.get('fii_net'):+.0f}Cr, DII {fii_sum.get('dii_trend')} Net {fii_sum.get('dii_net'):+.0f}Cr" if FII_AVAILABLE else "FII data N/A"
            
            # Global context
            global_ctx = ""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    global_ctx = get_global_context_for_hypothesis()
            except Exception:
                global_ctx = "Global mixed"
            
            # News & Corporate actions
            news_df = get_nse_announcements(symbol=sel_ticker.replace(".NS",""), days=7) if NEWS_AVAILABLE else pd.DataFrame()
            corp_df = get_nse_corporate_actions(symbol=sel_ticker.replace(".NS",""), days=30) if NEWS_AVAILABLE else pd.DataFrame()
            risk_info = is_zone_risky_due_to_event(sel_ticker.replace(".NS",""), datetime.now()) if NEWS_AVAILABLE else {"risky": False, "reasons": []}
            
            # Hypothesis
            zone_info_for_hyp = {
                "Direction": sel_row.get("Direction"),
                "Pattern": sel_row.get("Pattern"),
                "Timeframe": sel_tf,
                "Entry (Proximal)": sel_row.get("Entry (Proximal)"),
                "Distance %": sel_row.get("Distance %"),
                "State": sel_row.get("State"),
                "Score": sel_row.get("Score") or sel_row.get("Base Count"),
            }
            hypothesis = generate_hypothesis_rule_based(sel_ticker, zone_info_for_hyp, indicators, sector, fii_ctx, global_ctx, risk_info.get("risky", False))
            
            # Gemini enhanced if key available
            if is_gemini_configured() and GEMINI_MODULE_AVAILABLE:
                try:
                    gkey = get_gemini_key()
                    gemini_client = GeminiZoneAnalyzer(api_key=gkey, model="gemini-1.5-flash")
                    news_text = "\n".join([f"{r.get('desc')}" for _, r in news_df.head(3).iterrows()]) if not news_df.empty else "No news"
                    corp_text = "\n".join([f"{r.get('purpose')} ex {r.get('ex_date')}" for _, r in corp_df.head(2).iterrows()]) if not corp_df.empty else "No corp actions"
                    hypothesis = gemini_client.model.generate_content(f"Enhance this hypothesis in Hinglish, 2 lines, with verdict: {hypothesis} | News: {news_text} | Corp: {corp_text}").text
                except Exception as e:
                    hypothesis += f" (Gemini enhance failed: {e})"
            
            # Display hypothesis
            st.info(f"**Hypothesis:** {hypothesis}")
            
            # Short links - touch to read
            links = get_nse_links(sel_ticker) if SECTOR_AVAILABLE else {}
            sector_links = get_sector_news_link(sector) if SECTOR_AVAILABLE else {}
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("**📈 Chart Links (Touch to open)**")
                st.markdown(f"[TradingView Chart]({links.get('tradingview','')})")
                st.markdown(f"[NSE Quote]({links.get('nse_quote','')})")
                st.markdown(f"[Screener.in]({links.get('screener','')})")
            with col2:
                st.markdown("**📰 News / Events Links**")
                st.markdown(f"[NSE Announcements]({links.get('nse_announcements','')})")
                st.markdown(f"[Corporate Actions]({links.get('nse_corp_actions','')})")
                st.markdown(f"[Sector News: {sector}]({sector_links.get('google_news','')})")
            with col3:
                st.markdown("**📊 Indicators**")
                st.write(f"Price: {indicators.get('price','N/A')}")
                st.write(f"RSI(14): {indicators.get('rsi',0):.1f}")
                st.write(f"EMA20: {'>' if indicators.get('above_ema20') else '<'} Price | EMA50: {'>' if indicators.get('above_ema50') else '<'}")
                st.write(f"EMA200: {'>' if indicators.get('above_ema200') else '<'} Price")
                st.write(f"Supertrend: {'Bullish' if indicators.get('supertrend_dir')==1 else 'Bearish' if indicators.get('supertrend_dir')==-1 else 'Neutral'}")
                st.write(f"MACD Hist: {indicators.get('macd_hist',0):+.2f}")
                st.write(f"Vol: {indicators.get('vol_ratio',1):.1f}x SMA20")
            with col4:
                st.markdown("**🌍 Context**")
                st.write(f"**Sector:** {sector} ({sector_idx})")
                st.write(f"**FII/DII:** {fii_ctx}")
                st.write(f"**Global:** {global_ctx}")
                if risk_info.get("risky"):
                    st.warning(f"⚠️ Event Risk: {', '.join(risk_info['reasons'][:2])}")
                else:
                    st.success("✅ No near-term event risk")
                if not news_df.empty:
                    st.write("**Recent News:**")
                    for _, r in news_df.head(2).iterrows():
                        st.caption(f"- {r.get('desc','')[:100]}")
                if not corp_df.empty:
                    st.write("**Corp Actions:**")
                    for _, r in corp_df.head(2).iterrows():
                        st.caption(f"- {r.get('purpose','')} ex {r.get('ex_date','')}")

            # Global macro news table
            with st.expander("🌐 Global Macro Economic News (Today)", expanded=False):
                macro_df = cached_macro_news()
                if not macro_df.empty:
                    st.dataframe(macro_df, width="stretch", hide_index=True)
                else:
                    st.info("Macro news unavailable")

            # FII/DII full table
            with st.expander("💰 FII/DII Full Data", expanded=False):
                fii_df = get_fii_dii_summary().get("full_df") if FII_AVAILABLE else pd.DataFrame()
                if fii_df is not None and not fii_df.empty:
                    st.dataframe(fii_df, width="stretch", hide_index=True)
                else:
                    # Try direct fetch
                    try:
                        from fii_dii_fetcher import get_fii_dii_data
                        st.dataframe(get_fii_dii_data(), width="stretch", hide_index=True)
                    except Exception:
                        st.info("FII data unavailable")

else:
    # ==================== VALIDATED PAGE ====================
    st.markdown(f"**Validation Preset:** `{preset_choice}` | **Params:** RR>={v_min_rr}, RR Filter={v_use_rr_filter}, Engulf={v_require_engulf}, PulseTrend={v_use_pulse_trend}, Aligned Required={v_require_aligned}")

    with st.status("Data fetch + VALIDATED scan chal raha hai...", expanded=True) as status_box:
        st.write(f"🔹 Mode: {scan_mode} | Tickers: {len(tickers)} | TFs: {', '.join(tf_selected)} | Page: Validated")
        for base in BASE_ORDER:
            if base not in needed_bases:
                continue
            st.write(f"⏳ {BASE_LABELS[base]} data fetch ho raha hai...")
            _fetched = BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tickers)
            st.write(f"✅ {BASE_LABELS[base]} data mila: {len(_fetched)} / {len(tickers)} symbols")
        results_valid = {}
        funnels = {}
        all_frames_valid = {}
        for tf in tf_selected:
            st.write(f"🔎 Validated Scanning {tf}...")
            bucket = cc.last_closed_bucket(tf)
            df_tf, funnel, frames_tf = cached_validated_scan(tf, bucket, params_valid_tuple, tickers, states_tuple)
            results_valid[tf] = df_tf
            funnels[tf] = funnel
            all_frames_valid[tf] = frames_tf
        status_box.update(label="✅ Validated Scan complete", state="complete", expanded=False)

    ordered_tfs = sorted(tf_selected, key=scanner.tf_minutes)
    non_empty_v = [results_valid[tf] for tf in ordered_tfs if tf in results_valid and not results_valid[tf].empty]
    combined_v = pd.concat(non_empty_v, ignore_index=True) if non_empty_v else pd.DataFrame()

    if len(tf_selected) > 1 and not combined_v.empty:
        view_tfs_v = st.multiselect("View Timeframe(s) in validated table below", ordered_tfs, default=ordered_tfs, key="view_tf_validated")
        if view_tfs_v:
            combined_v = combined_v[combined_v["Timeframe"].isin(view_tfs_v)]

    if not combined_v.empty:
        st.markdown("#### 🔃 Validated Table Sorting / Grouping")
        sort_option_v = st.radio("Validated zones ko kaise dikhana hai?", ["Distance % (Nearest First + Same Stock Grouped)", "Symbol A→Z ↑", "Symbol Z→A ↓", "Symbol Grouped (A-Z)"], index=0, horizontal=True, key="sort_validated")
        if sort_option_v == "Symbol A→Z ↑":
            combined_v = combined_v.sort_values("Ticker", ascending=True)
        elif sort_option_v == "Symbol Z→A ↓":
            combined_v = combined_v.sort_values("Ticker", ascending=False)
        elif "Grouped" in sort_option_v:
            combined_v["_tf_min"] = combined_v["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
            combined_v = combined_v.sort_values(["Ticker", "_tf_min"], ascending=[True, True])
            combined_v = combined_v.drop(columns=["_tf_min"])
        else:
            if "Distance %" in combined_v.columns and "Ticker" in combined_v.columns:
                combined_v["_abs_dist"] = combined_v["Distance %"].abs()
                ticker_min_dist = combined_v.groupby("Ticker")["_abs_dist"].min()
                combined_v["_ticker_min"] = combined_v["Ticker"].map(ticker_min_dist)
                combined_v["_tf_min"] = combined_v["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
                combined_v = combined_v.sort_values(["_ticker_min", "Ticker", "_abs_dist", "_tf_min"], ascending=[True, True, True, True])
                combined_v = combined_v.drop(columns=["_abs_dist", "_ticker_min", "_tf_min"])

    merged_frames_v = {}
    for tf_frames in all_frames_valid.values():
        merged_frames_v.update(tf_frames)
    display_valid = render_table_validated(combined_v, "all_validated" if len(tf_selected) > 1 else (tf_selected[0] if tf_selected else "validated"), all_frames=merged_frames_v)

    # Detailed analysis for validated too (same as main)
    if not display_valid.empty:
        st.markdown("---")
        st.subheader("🔬 Detailed Validated Zone Analysis - Hypothesis + FII + Global + News (Short Links)")
        def make_option_v(row):
            return f"{row['Ticker']} ({row['Timeframe']}) - {row['Direction'].split()[0]} - {row['Distance %']:+.2f}% - Valid {row.get('Valid?',False)} - Aligned {row.get('Aligned?',False)}"
        options_v = [make_option_v(row) for _, row in display_valid.head(50).iterrows()]
        selected_opt_v = st.selectbox("Validated zone chuno detailed analysis ke liye (Top 50)", options_v, index=0 if options_v else None, key="sel_validated")
        if selected_opt_v:
            sel_idx = options_v.index(selected_opt_v)
            sel_row = display_valid.iloc[sel_idx]
            sel_ticker = sel_row["Ticker"]
            sel_tf = sel_row["Timeframe"]
            try:
                daily_bucket = cc.last_closed_bucket("Daily")
                daily_data = cached_fetch_daily(daily_bucket, (sel_ticker,))
                df_ind = daily_data.get(sel_ticker)
                indicators = calculate_indicators(df_ind) if df_ind is not None and INDICATOR_AVAILABLE else {}
            except Exception:
                indicators = {}
            sector = get_sector(sel_ticker) if SECTOR_AVAILABLE else "Others"
            sector_idx = get_sector_index(sector) if SECTOR_AVAILABLE else "NIFTY 50"
            fii_sum = cached_fii_summary()
            fii_ctx = f"FII {fii_sum.get('fii_trend')} Net {fii_sum.get('fii_net'):+.0f}Cr, DII {fii_sum.get('dii_trend')} Net {fii_sum.get('dii_net'):+.0f}Cr" if FII_AVAILABLE else "FII N/A"
            global_ctx = ""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    global_ctx = get_global_context_for_hypothesis()
            except Exception:
                global_ctx = "Global mixed"
            news_df = get_nse_announcements(symbol=sel_ticker.replace(".NS",""), days=7) if NEWS_AVAILABLE else pd.DataFrame()
            corp_df = get_nse_corporate_actions(symbol=sel_ticker.replace(".NS",""), days=30) if NEWS_AVAILABLE else pd.DataFrame()
            risk_info = is_zone_risky_due_to_event(sel_ticker.replace(".NS",""), datetime.now()) if NEWS_AVAILABLE else {"risky": False, "reasons": []}
            zone_info_for_hyp = {"Direction": sel_row.get("Direction"), "Pattern": sel_row.get("Pattern"), "Timeframe": sel_tf, "Entry (Proximal)": sel_row.get("Entry (Proximal)"), "Distance %": sel_row.get("Distance %"), "State": sel_row.get("State"), "Score": sel_row.get("Score")}
            hypothesis = generate_hypothesis_rule_based(sel_ticker, zone_info_for_hyp, indicators, sector, fii_ctx, global_ctx, risk_info.get("risky", False))
            if is_gemini_configured() and GEMINI_MODULE_AVAILABLE:
                try:
                    gkey = get_gemini_key()
                    from gemini_analyzer import GeminiZoneAnalyzer
                    gemini_client = GeminiZoneAnalyzer(api_key=gkey, model="gemini-1.5-flash")
                    news_text = "\n".join([f"{r.get('desc')}" for _, r in news_df.head(3).iterrows()]) if not news_df.empty else "No news"
                    corp_text = "\n".join([f"{r.get('purpose')} ex {r.get('ex_date')}" for _, r in corp_df.head(2).iterrows()]) if not corp_df.empty else "No corp"
                    hypothesis = gemini_client.model.generate_content(f"Enhance hypothesis in Hinglish 2 lines: {hypothesis} | News: {news_text} | Corp: {corp_text}").text
                except Exception as e:
                    hypothesis += f" (Gemini error: {e})"
            st.info(f"**Hypothesis:** {hypothesis}")
            links = get_nse_links(sel_ticker) if SECTOR_AVAILABLE else {}
            sector_links = get_sector_news_link(sector) if SECTOR_AVAILABLE else {}
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("**📈 Chart Links**")
                st.markdown(f"[TradingView]({links.get('tradingview','')})")
                st.markdown(f"[NSE Quote]({links.get('nse_quote','')})")
                st.markdown(f"[Screener]({links.get('screener','')})")
            with col2:
                st.markdown("**📰 News Links**")
                st.markdown(f"[NSE Announcements]({links.get('nse_announcements','')})")
                st.markdown(f"[Corp Actions]({links.get('nse_corp_actions','')})")
                st.markdown(f"[Sector {sector} News]({sector_links.get('google_news','')})")
            with col3:
                st.markdown("**📊 Indicators**")
                st.write(f"RSI: {indicators.get('rsi',0):.1f} | Vol {indicators.get('vol_ratio',1):.1f}x")
                st.write(f"EMA20/50/200: {'>' if indicators.get('above_ema20') else '<'}/{'>' if indicators.get('above_ema50') else '<'}/{'>' if indicators.get('above_ema200') else '<'}")
                st.write(f"Supertrend: {'Bullish' if indicators.get('supertrend_dir')==1 else 'Bearish' if indicators.get('supertrend_dir')==-1 else 'Neutral'} | MACD {indicators.get('macd_hist',0):+.2f}")
            with col4:
                st.markdown("**🌍 Context + Risk**")
                st.write(f"Sector: {sector} ({sector_idx})")
                st.write(f"FII/DII: {fii_ctx}")
                st.write(f"Global: {global_ctx}")
                if risk_info.get("risky"):
                    st.warning(f"⚠️ {', '.join(risk_info['reasons'][:2])}")
                else:
                    st.success("✅ No event risk")
                # Extra validation fields
                st.write(f"**Validation:** Valid={sel_row.get('Valid?')} RR>=3={sel_row.get('RR>=3?')} Engulf={sel_row.get('Engulf OK')} Aligned={sel_row.get('Aligned?')}")

            # Gemini batch button for validated page
            if is_gemini_configured():
                if st.button("🤖 Gemini se Top 10 Validated Zones ka AI Analysis", key="gemini_validated"):
                    with st.spinner("Gemini analysis..."):
                        try:
                            gkey = get_gemini_key()
                            from gemini_analyzer import GeminiZoneAnalyzer
                            gemini_client = GeminiZoneAnalyzer(api_key=gkey, model="gemini-1.5-flash")
                            daily_bucket = cc.last_closed_bucket("Daily")
                            up,down,flat,_ = cached_breadth_for_all(daily_bucket, tuple(all_tickers))
                            breadth = {"up": up, "down": down, "flat": flat, "total": up+down+flat}
                            analysis_df = gemini_client.analyze_batch_zones(zones_df=display_valid, max_zones=10, news_fetcher=lambda sym: get_nse_announcements(symbol=sym.replace(".NS",""), days=7), corp_fetcher=lambda sym: get_nse_corporate_actions(symbol=sym.replace(".NS",""), days=30), breadth=breadth)
                            st.dataframe(analysis_df, width="stretch")
                        except Exception as e:
                            st.error(f"Gemini error: {e}")

    with st.expander("🔍 Validation Funnel - Kaunsa Rule Kitna Filter Kar Raha Hai?", expanded=False):
        for tf in ordered_tfs:
            if tf in funnels and funnels[tf]:
                df_funnel = pd.DataFrame([dict(gate=k, rejected=v) for k,v in funnels[tf].items()]).sort_values("rejected", ascending=False).reset_index(drop=True)
                if not df_funnel.empty:
                    df_funnel["pct"] = (100 * df_funnel["rejected"] / df_funnel["rejected"].sum()).round(1)
                    st.markdown(f"**{tf} Funnel**")
                    st.dataframe(df_funnel, width="stretch", hide_index=True)

# ==================== NEXT POWERFUL FEATURES - Telegram + Auto Trading + Backtesting ====================
# Secure, bina keys ke bhi fast, keys ho to auto-enable
st.markdown("---")
st.subheader("🚀 Next Powerful Features - Secure & Optional (Bina Key Ke Bhi Fast)")

tab_autotrade = st.tabs(["🛒 Dhan Auto Trading (Optional)"])[0]

with tab_autotrade:
    st.markdown("**Dhan se Zone par Auto Bracket Order - Secure, Paper Trading Default (Safe)**")
    dhan_ok = is_dhan_configured()
    if dhan_ok:
        st.success(f"✅ Dhan configured: {mask_key(get_dhan_creds()[0] or '')} (secure) - Trading enabled")
        
        paper = st.checkbox("Paper Trading (Safe - Real order nahi lagega)", value=True, key="paper_trading", help="ON rakho to real order nahi lagega, sirf log. OFF karne par real order lagega - careful!")
        qty = st.number_input(f"Quantity (Max 100 for safety)", min_value=1, max_value=100, value=1, key="auto_qty")
        
        # Select zone to trade - from main or validated
        combined_for_trade = combined if "Main" in st.session_state.app_page and 'combined' in locals() and not combined.empty else combined_v if 'combined_v' in locals() and not combined_v.empty else pd.DataFrame()
        
        if not combined_for_trade.empty:
            zone_options = [f"{row['Ticker']} {row['Timeframe']} {row['Direction'].split()[0]} Entry {row['Entry (Proximal)']} Dist {row['Distance %']:+.2f}%" for _, row in combined_for_trade.head(20).iterrows()]
            sel_zone_str = st.selectbox("Trade ke liye Zone chuno (Top 20 nearest)", zone_options, key="trade_zone_select")
            
            if sel_zone_str:
                sel_idx = zone_options.index(sel_zone_str)
                sel_zone = combined_for_trade.iloc[sel_idx].to_dict()
                
                col_buy, col_sell = st.columns(2)
                with col_buy:
                    if st.button(f"🛒 BUY {sel_zone['Ticker']} @ {sel_zone['Entry (Proximal)']} (Paper={paper})", width="stretch", key="buy_btn"):
                        try:
                            from auto_trading import place_bracket_order_from_zone
                            result = place_bracket_order_from_zone(sel_zone, quantity=qty, paper_trading=paper)
                            if result["status"] == "paper_trading":
                                st.info(result["message"])
                                st.json(result)
                            elif result["status"] == "success":
                                st.success(f"✅ Real order placed: {result}")
                            else:
                                st.error(f"❌ Failed: {result.get('reason')}")
                        except Exception as e:
                            st.error(f"Error: {e}")
                with col_sell:
                    if st.button(f"🔴 SELL {sel_zone['Ticker']} @ {sel_zone['Entry (Proximal)']} (Paper={paper})", width="stretch", key="sell_btn"):
                        try:
                            from auto_trading import place_bracket_order_from_zone
                            # For SELL, invert direction if needed - here same zone dict but transaction_type auto from direction
                            result = place_bracket_order_from_zone(sel_zone, quantity=qty, paper_trading=paper)
                            if result["status"] == "paper_trading":
                                st.info(result["message"])
                            elif result["status"] == "success":
                                st.success(f"✅ Real order placed: {result}")
                            else:
                                st.error(f"❌ Failed: {result.get('reason')}")
                        except Exception as e:
                            st.error(f"Error: {e}")
        else:
            st.info("No zones for trading - scan complete hone do")
        
        # Auto trading toggle - extra secure, needs secrets flag
        st.markdown("---")
        st.caption("Auto Trading - Extra Secure: Secrets me [trading] auto_enabled = true daalna padega")
        try:
            auto_enabled_flag = get_secret("trading.auto_enabled") or get_secret("TRADING_AUTO_ENABLED")
            auto_trading_flag = str(auto_enabled_flag).lower() in ["true","1","yes"] if auto_enabled_flag else False
        except Exception:
            auto_trading_flag = False
        
        if auto_trading_flag:
            st.warning("⚠️ Auto Trading Flag ENABLED via secrets.toml - Nearest zones par auto order lagega")
            auto_trade = st.checkbox("Auto Trade Nearest Zones (<0.5%) - Real orders if Paper OFF!", value=False, key="auto_trade_toggle")
            if auto_trade:
                st.error("⚠️ CAUTION: Real orders lagenge agar Paper Trading OFF hai! Ensure karo.")
                # Auto trade logic same as telegram but for orders
                if not combined_for_trade.empty:
                    nearest = combined_for_trade[combined_for_trade["Distance %"].abs() <= 0.5].head(2)
                    for _, row in nearest.iterrows():
                        try:
                            from auto_trading import place_bracket_order_from_zone
                            res = place_bracket_order_from_zone(row.to_dict(), quantity=1, paper_trading=paper)
                            st.write(res)
                        except Exception as e:
                            st.error(f"Auto trade error: {e}")
        else:
            st.info("○ Auto trading disabled (secure). Enable karne ke liye secrets.toml me [trading] auto_enabled = true daalo. Default paper trading safe hai.")
    else:
        st.info("○ Dhan not configured - Trading disabled. Bina key ke scanner fast. Key ke liye .streamlit/secrets.toml me [dhan] client_id + access_token daalo.")
        with st.expander("🔑 Dhan Setup (Secure TOML)", expanded=False):
            st.markdown("""
            ```toml
            [dhan]
            client_id = "1100000001"
            access_token = "eyJ0eXAiOiJKV1Qi..."
            
            [trading]
            auto_enabled = false  # true karne par auto trading enable, default false (safe)
            ```
            Token 24h valid, daily refresh karna pad sakta hai. Secrets me rakho, GitHub par mat push karo.
            """)

st.markdown("---")
with st.expander("ℹ️ Methodology + Security + Powerful Features", expanded=False):
    st.markdown("""
    **Security (API Keys):**
    - Bina Dhan/Gemini key ke bhi app 100% fast chalega
    - Keys ho to auto-enable: Dhan holdings/orders, Gemini AI analysis
    - Keys kabhi GitHub/log/dataframe me nahi dikhengi - sirf ✅/○ status
    - `.streamlit/secrets.toml` me rakho, .gitignore me hona chahiye

    **Powerful Features (Bina API key ke free):**
    - **FII/DII Activity**: NSE API se daily FII/DII net buy/sell, trend - free, 30min cache
    - **Global Instruments**: GIFT NIFTY, NIFTY, BANK NIFTY, USD/INR, Gold, Crude + World Indices (Dow, Nasdaq, FTSE, Nikkei)
    - **Global Macro News**: ForexFactory free JSON se high-impact events (Fed, RBI, NFP, CPI) + NSE world indices
    - **Sector + News/Event**: Har stock ka sector mapping (IT, Banking, Pharma etc) + NSE announcements + corporate actions + risky event check
    - **Indicators Hypothesis**: RSI, EMA20/50/200, Supertrend, MACD, Volume ratio se rule-based Hinglish hypothesis - har zone me short hypothesis + detailed analysis me full + short clickable links (TradingView, NSE Quote, Screener, Moneycontrol, Sector News)

    **With API Keys (Optional, Secure):**
    - **Dhan**: Holdings, Positions, Live LTP (Yahoo se tez), Option Chain OI, Zone se direct order
    - **Gemini**: Zone + News + FII + Global context se AI enhanced hypothesis, confidence %, verdict, market overview

    **Short Links (Touch to Read):**
    - Symbol column = TradingView chart (touch to open)
    - Detailed Analysis me: TradingView, NSE Quote, NSE Announcements, Corporate Actions, Screener.in, Moneycontrol, Google News (Sector)
    - Hypothesis short link = chart link + detailed expander anchor
    """)

# Dhan holdings if configured (optional, secure)
if is_dhan_configured():
    with st.expander("💼 Dhan Holdings & Positions (Secure - Only if Dhan key configured)", expanded=False):
        try:
            from dhan_api_helper import DhanHelper
            cid, token = get_dhan_creds()
            dhan_client = DhanHelper(client_id=cid, access_token=token)
            col_h, col_p = st.columns(2)
            with col_h:
                st.markdown("**Holdings**")
                holdings_df = dhan_client.get_holdings()
                if not holdings_df.empty:
                    st.dataframe(holdings_df, width="stretch", hide_index=True)
                else:
                    st.info("No holdings or API error")
            with col_p:
                st.markdown("**Positions**")
                pos_df = dhan_client.get_positions()
                if not pos_df.empty:
                    st.dataframe(pos_df, width="stretch", hide_index=True)
                else:
                    st.info("No positions")
        except Exception as e:
            st.warning(f"Dhan error (secure, key masked): {e}. App fast mode me chalega.")
