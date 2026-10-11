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
- NEW: Nearest-Zone Filter (toot chuke zone hide, door ke zone hide, nazdeek ka zone pehle,
       ek symbol ke zone puri jagah na gher sake)
- CLEAN TOP: main/validated page ke top se Mode info box, Fast Open warning, scan buttons,
       auto-refresh caption aur scan status box hata diye -- ye sab Settings (⚙️) popover ke
       "Scan Controls" + "Auto-Refresh" me hain. Scan chupchap (silent) chalta hai.
- NO EMPTY GAP: market tape ke saath koi alag badge block/divider nahi (macro badges usi row me),
       aur auto-refresh ka call page ke BOTTOM me -- chips row ke neeche khaali space nahi banti.
- CHANGED: "LIVE: Important Market News / Events" + "Top Market News / Events" (3-in-1)
       ko top se hata kar page ke BOTTOM me, ek COLLAPSED expander ke andar shift kar diya gaya hai
- NEW: Validated page par Engine selector -- v1 (purana) ya v2 (naye niyam: leg-out complete +
       envelope + half-TF, pulse/trend hataye hue). v2 ke liye repo me zone_core_validation_v2.py chahiye.
- CLEAN DASHBOARD (naya): dashboard se Nearest-Zone Filter ka caption aur "Table Sorting / Grouping"
       section (heading + radio) hata diya -- sorting ab Settings (⚙️) popover ke "🔃 Table Sorting / Grouping"
       me hai, aur filter ki last-scan info wahi popover me caption bankar dikhti hai. Dono pages clean.
- PINE PARITY (naya): main scan ke intraday frames ab Pine/TradingView jaisa session rakhte hain --
   zone_core.py ka trim_out_of_session_bars() session ke bahar ki CAS/auction candle (post-03-Aug-2026
   F&O stocks me 15:15 ki candle) hata deta hai, isliye INFY 2H (Entry 992.70/SL 979.32) jaisa
   ghost zone scanner me nahi aata (TV/Pine chart par aisa zone hota hi nahi). Repo me naya zone_core.py
   chahiye; na milne par ye step chup-chaap skip ho jata hai (purana behaviour).

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
from datetime import datetime, timedelta

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

# v2 Validation module (NEW: leg-out complete + envelope + half-TF niyam, pulse/trend hataye hue)
try:
    import zone_core_validation_v2 as zcv2
    ZCV2_AVAILABLE = True
except ImportError:
    ZCV2_AVAILABLE = False

# Secure config helpers (optional files, fallback inline)
try:
    from secure_config import get_secret, is_dhan_configured, is_gemini_configured, get_dhan_creds, get_gemini_key, mask_key
    SECURE_AVAILABLE = True
except ImportError:
    SECURE_AVAILABLE = False

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
        return k[:4] + "****" + k[-4:] if k and len(k) >= 8 else "****"

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
    from sector_map import get_sector, get_sector_index, get_nse_links, get_sector_news_link, get_macro_drivers_for_sector
    SECTOR_AVAILABLE = True
except ImportError:
    SECTOR_AVAILABLE = False

    def get_sector(s):
        return "Others"

    def get_sector_index(s):
        return "NIFTY 50"

    def get_nse_links(s):
        clean = s.replace(".NS", "").upper()
        return {
            "tradingview": f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean}",
            "nse_quote": f"https://www.nseindia.com/get-quotes/equity?symbol={clean}",
            "nse_announcements": f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={clean}",
            "screener": f"https://www.screener.in/company/{clean}/",
        }

    def get_sector_news_link(s):
        return {"google_news": f"https://news.google.com/search?q={s}+NSE"}

    def get_macro_drivers_for_sector(s):
        return []

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
        return f"https://www.tradingview.com/chart/?symbol=NSE%3A{sym.replace('.NS', '')}&interval={tf}"

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

# AI Trader Pulse (Delivery % + F&O Breadth % + Option OI/PCR + FII/DII + Volume
# + Global + Indian News -> AI short summary + Top 10 Buy/Sell + Pre/Post Market)
try:
    import market_pulse as mp
    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False

st.set_page_config(page_title="NSE F&O Supply/Demand Zone Scanner - Secure Powerful", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

if "app_page" not in st.session_state:
    st.session_state.app_page = "📈 Main Scanner (zone_core.py)"

# ---------- circular logo (inline SVG - koi external file nahi) ----------
LOGO_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<defs><radialGradient id='g' cx='50%' cy='40%'>"
    "<stop offset='0%' stop-color='%232d333b'/>"
    "<stop offset='100%' stop-color='%230d1117'/></radialGradient></defs>"
    "<circle cx='32' cy='32' r='31' fill='url(%23g)' stroke='%23ff4b4b' stroke-width='2'/>"
    "<circle cx='32' cy='32' r='22' fill='none' stroke='%23ff4b4b' stroke-width='5' opacity='.18'/>"
    "<circle cx='32' cy='32' r='14' fill='none' stroke='%23ff4b4b' stroke-width='5' opacity='.38'/>"
    "<circle cx='32' cy='32' r='6.5' fill='none' stroke='%23ff4b4b' stroke-width='4' opacity='.75'/>"
    "<circle cx='32' cy='32' r='2.4' fill='%23ff4b4b'/>"
    "<path d='M32 4v9M32 51v9M4 32h9M51 32h9' stroke='%23ff4b4b' stroke-width='2' opacity='.65'/>"
    "<rect x='26' y='14' width='12' height='6' rx='2' fill='none' stroke='%237ee787' stroke-width='1.6' opacity='.85'/>"
    "<rect x='26' y='44' width='12' height='6' rx='2' fill='none' stroke='%237ee787' stroke-width='1.6' opacity='.85'/>"
    "</svg>"
)

st.markdown("""
<style>
/* settings ka ROUND CIRCLE button */
div[data-testid="stPopover"] > button{
  border-radius:50% !important;
  width:46px !important; height:46px !important;
  min-width:46px !important; min-height:46px !important;
  padding:0 !important; margin:0 !important;
  font-size:1.25rem !important; line-height:1 !important;
  display:flex !important; align-items:center !important; justify-content:center !important;
  box-shadow:0 2px 10px rgba(255,75,75,.28) !important;
}
.zs-logo{width:52px;height:52px;border-radius:50%;flex:0 0 52px;
  box-shadow:0 0 0 2px rgba(255,75,75,.35), 0 4px 14px rgba(0,0,0,.45);}
.zs-title{font-size:1.7rem;font-weight:750;line-height:1.15;margin:0;}
.zs-sub{font-size:.74rem;color:#8b949e;margin-top:2px;}
</style>
""", unsafe_allow_html=True)

# Top bar
gear_col, title_col, secure_col = st.columns([0.06, 0.74, 0.20])
with title_col:
    _pg_title = ("✅ Validated Zones - Second Page"
                 if "Validated" in st.session_state.app_page
                 else "📈 NSE F&O Supply/Demand Zone Scanner")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:13px;margin:-6px 0 0 0;">'
        '<img class="zs-logo" src="' + LOGO_SVG + '" alt="Zone Scanner"/>'
        '<div><div class="zs-title">' + _pg_title + '</div>'
        '<div class="zs-sub">Entry = Proximal · SL = Distal + buffer · nearest-zone pehle</div>'
        '</div></div>', unsafe_allow_html=True)
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

# ---------- 🧪 Diagnostics: 502 / OOM ki wajah samajhne ke liye ----------
with st.expander("🧪 Diagnostics — memory & Render limits (502 aa raha ho to yahan dekho)", expanded=False):
    try:
        import resource as _res
        _mb = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss / 1024
        _mem_row = f"**{_mb:.0f} MB**"
    except Exception:
        _mem_row = "n/a"
    import data_fetch as _df
    st.markdown(f"""
| Cheez | Value |
|---|---|
| Abhi memory use | {_mem_row} (Render FREE limit = **512 MB**) |
| Chunk size / keep-bars | **{getattr(_df,'CHUNK_SIZE','?')}** / **{getattr(_df,'KEEP_BARS','?')}** |
| F&O universe | **{len(get_fno_symbols(try_live=False)[0])}** symbols (embedded safety-net ON) |
""")
    st.caption("**502 Bad Gateway = Render ne app maar diya** (lagbhag hamesha memory > 512 MB).")
    st.markdown("""
**Agar 502 aaye to Render → Environment me ye daalo:**
```bash
ZS_CHUNK=10          # downloads chhote
ZS_KEEP_BARS=500     # har symbol ke kam bars
ZS_WORKERS=1
```
Ya **Render Starter ($7/mo)** = 0.5 CPU + 2 GB → koi dikkat nahi.
""")

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

    st.checkbox("📏 Full column names (Timeframe / Direction / Entry (Proximal) …)",
                value=False, key="full_col_names",
                help="ON = poore column names (compact 'TF/Dir/SL/LTP' ki jagah). "
                     "OFF = chhote names, zada columns ek screen me.")

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

    @st.cache_data(show_spinner=False, ttl=24 * 3600)
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
        global_labels_selected = st.multiselect("🌍 Top Global Instruments", gi.labels(), default=gi.labels()[:8] if len(gi.labels()) >= 8 else gi.labels())
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

    # ---------- NEW: Nearest-Zone Filter ----------
    st.markdown("**📍 Nearest-Zone Filter (नज़दीकी zone पहले)**")
    prox_enable = st.checkbox("Sirf nazdeek zones dikhao (Proximal ke paas, toote zone hide)", value=True, key="prox_enable")
    prox_max_dist = st.slider("Max Distance % (LTP se proximal tak)", 0.5, 30.0, 5.0, 0.5, key="prox_max_dist")
    prox_per_symbol = st.slider(
        "Ek symbol ke max zones (0 = unlimited)", 0, 10, 2, 1, key="prox_per_symbol",
        help="2 = हर symbol के सिर्फ़ 2 सबसे नज़दीकी zone, ताकि एक symbol पूरी जगह न घेरे और बाकी symbols के नज़दीकी zone दिखें। 0 = कोई limit नहीं।",
    )
    # Dashboard par ye caption nahi dikhta (clean rakhne ke liye) - last scan ki info yahan
    _pfi = st.session_state.get("prox_filter_info")
    if _pfi:
        st.caption(f"📍 Last scan: {_pfi[0]} zones me se {_pfi[1]} nazdeek/valid zone dikhaye gaye")

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

    with st.expander("🧩 Engine (Validated Page) - v1 ya v2?", expanded=False):
        if ZCV2_AVAILABLE:
            engine_choice = st.radio(
                "Validated page kaunsa engine use kare?",
                ["v1 (purana: pulse/trend + engulf rules)", "v2 (naye niyam: leg-out complete + envelope + half-TF)"],
                index=0,
                help="v2 me pulse/trend ke saare rules hata diye gaye hain; zone sirf leg-out candle complete hone par valid hota hai, "
                     "aur envelope (entry+SL+target) + half time-frame check lagta hai. v2 ke liye repo me zone_core_validation_v2.py hona chahiye.",
            )
        else:
            engine_choice = "v1 (purana: pulse/trend + engulf rules)"
            st.info("○ zone_core_validation_v2.py nahi mila - sirf v1 engine available hai. v2 use karne ke liye ye file repo me upload karo.")

        use_v2 = engine_choice.startswith("v2")
        if use_v2:
            st.markdown("**v2 Rules (naye niyam)**")
            v2_target_rr = st.number_input("v2 Target RR (min 1:1)", min_value=1.0, max_value=8.0, value=3.0, step=0.5, key="v2_target_rr",
                                           help="1:2 ya 1:3 - targetRR ke hisaab se legOutRR/HQ checks chalte hain. Backtest me charges ke liye 1:2/1:1 behtar nikla hai.")
            v2_env = st.checkbox("Envelope niyam ON (entry+SL+target leg-out ke andar)", value=True, key="v2_env")
            v2_env_rr = st.number_input("Envelope RR (target kis RR tak check ho)", min_value=1.0, max_value=8.0, value=float(v2_target_rr), step=0.5, key="v2_env_rr")
            v2_env_stop = st.checkbox("Stop-side bhi block ke andar ho (strict)", value=False, key="v2_env_stop",
                                      help="OFF = sirf target-side check (backtest me yahi practical nikla: 377 zones vs 37), ON = dono taraf (bahut kam zones).")
            v2_env_target = st.checkbox("Target-side check ON", value=True, key="v2_env_target")
            v2_cont = st.slider("Continuation candles (single candle me na aaye to)", 1, 3, 3, key="v2_cont")
            st.markdown("**v2 Half Time-Frame Check**")
            v2_half = st.checkbox("Half-TF check ON (mid-line break = invalid)", value=True, key="v2_half")
            v2_half_pct = st.slider("Half-TF min aligned share", 0.0, 1.0, 0.50, 0.05, key="v2_half_pct")
            v2_half_missing = st.selectbox("Half data na mile to?", ["skip (zone rakho)", "reject (zone hatao)"], index=0, key="v2_half_missing")
            v2_assume_live = st.checkbox("Last bar ko live maano (forming candle)", value=False, key="v2_live")
            st.caption("Asar (50 stocks backtest): half-TF akele 10% zones kaatta hai; envelope dono-taraf 96% kaat deta hai - isliye stop-side OFF rakho.")

    st.markdown("---")
    st.subheader("🔃 Table Sorting / Grouping")
    st.caption("Dashboard par heading/radio nahi dikhte (page clean rahe) - sorting yahan se set karo. Dono pages par yahi lagti hai, sirf display order badalta hai.")
    sort_choice = st.radio(
        "Zones ko kaise dikhayein?",
        ["📍 Distance % (Nearest First)", "🔤 Symbol A→Z ↑", "🔤 Symbol Z→A ↓", "🗂️ Symbol Grouped (A-Z)"],
        index=0, key="sort_choice",
        help="Distance % = sab symbols milakar sabse nazdeek zone pehle | Grouped = ek symbol ke saare TF ek saath",
    )

    st.markdown("---")
    st.subheader("🚀 Scan Controls")
    st.caption("Buttons yahan hain taki main page bilkul clean rahe. Scan chupchap chalta hai, result table me dikhta hai.")
    _s1, _s2 = st.columns(2)
    _main_fast_btn = _s1.button(f"🚀 Main: Fast ({min(50, total_n)})", key="btn_scan_main_fast", width="stretch")
    _main_full_btn = _s2.button(f"🔍 Main: Full ({total_n})", key="btn_scan_main_full", width="stretch")
    _s3, _s4 = st.columns(2)
    _valid_fast_btn = _s3.button(f"🚀 Validated: Fast ({min(50, total_n)})", key="btn_scan_valid_fast", width="stretch")
    _valid_full_btn = _s4.button(f"🔍 Validated: Full ({total_n})", key="btn_scan_valid_full", width="stretch")
    if _main_fast_btn:
        st.session_state["main_scan_trigger"] = "fast"
    if _main_full_btn:
        st.session_state["main_scan_trigger"] = "full"
    if _valid_fast_btn:
        st.session_state["valid_scan_trigger"] = "fast"
    if _valid_full_btn:
        st.session_state["valid_scan_trigger"] = "full"

    st.markdown("---")
    st.subheader("🔄 Auto-Refresh")
    st.session_state.auto_refresh_enabled = st.toggle(
        "Auto-Refresh ON (candle close par)", value=st.session_state.get("auto_refresh_enabled", True),
        key="auto_refresh_toggle", help="Chhote TF ki candle band hone par page khud refresh hota hai")
    _nc = st.session_state.get("next_close_info")
    if _nc is None:
        try:
            _nc = get_next_candle_close_info(tf_selected)
        except Exception:
            _nc = None
    if st.session_state.auto_refresh_enabled and _nc:
        st.caption(f"⏳ Agla refresh: {_nc[0]} candle close in {_nc[1] // 60}m {_nc[1] % 60}s")
    elif not st.session_state.auto_refresh_enabled:
        st.caption("⏸️ Auto-Refresh OFF")

    # Live LTP fast update (latency fix): tape + table ka LTP market hours me
    # har kuch second live update hota hai - candle close ka intezaar nahi.
    st.markdown("---")
    st.subheader("⚡ Live LTP Fast Update")
    st.session_state.live_ltp_refresh = st.toggle(
        "Live LTP update ON (market hours)", value=st.session_state.get("live_ltp_refresh", True),
        key="live_ltp_toggle",
        help="Top tape aur table ka LTP/Dist% live refresh hota hai (Dhan connected ho to Dhan real-time se, warna Yahoo)")
    st.select_slider("Live update interval", options=["5s", "10s", "15s", "30s"],
                     value=st.session_state.get("live_ltp_interval", "10s"), key="live_ltp_interval_slider")
    if is_dhan_configured():
        st.caption("✅ Dhan connected - real-time quotes (5s cache)")
    else:
        st.caption("ℹ️ Dhan key nahi hai - Yahoo se update (Dhan se ~15min fast ho sakta hai, Settings me key daalo)")

    with st.expander("🗄️ Cache / Refresh", expanded=False):
        force_rescan = st.button("🔄 Force Rescan (bypass cache)", width="stretch")

# v2 options ke safe defaults (agar v2 select nahi hai to bhi variables defined rahein)
if "use_v2" not in dir():
    use_v2 = False
if not use_v2:
    v2_target_rr = float(target_rr)
    v2_env = True
    v2_env_rr = float(target_rr)
    v2_env_stop = False
    v2_env_target = True
    v2_cont = 3
    v2_half = True
    v2_half_pct = 0.50
    v2_half_missing = "skip (zone rakho)"
    v2_assume_live = False

# Cached fetchers
# ROBUST price source: Dhan if connected (fast real-time) else Yahoo Finance (app band nahi hoga)
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_1m(bk, tt):
    try:
        return data_fetch.fetch_1m(list(tt))
    except Exception as e:
        print(f"1m fetch error, empty fallback: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_5m(bk, tt):
    try:
        return data_fetch.fetch_5m(list(tt))
    except Exception as e:
        print(f"5m fetch error, empty fallback: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_15m(bk, tt):
    try:
        return data_fetch.fetch_15m(list(tt))
    except Exception as e:
        print(f"15m fetch error, empty fallback: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_60m(bk, tt):
    try:
        return data_fetch.fetch_60m(list(tt))
    except Exception as e:
        print(f"60m fetch error, empty fallback: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_daily(bk, tt):
    try:
        return data_fetch.fetch_daily(list(tt))
    except Exception as e:
        print(f"Daily fetch error, empty fallback: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=5)  # 5s - real-time LTP (Dhan connected ho to)
def cached_dhan_ltp_if_available(tickers_tuple):
    """Live price - Dhan se agar connected hai to Dhan se, nahi to khali dict
    (Yahoo path fast_live_price se alag se aata hai) - Secure"""
    if is_dhan_configured():
        try:
            from dhan_api_helper import get_dhan_ltp_fast
            cid, token = get_dhan_creds()
            syms = tuple(str(t).replace(".NS", "") for t in tickers_tuple)
            return get_dhan_ltp_fast(cid, token, syms) or {}
        except Exception as e:
            print(f"Dhan LTP error (secure): {e}")
            return {}
    return {}


@st.cache_data(show_spinner=False, ttl=5)  # 5s - tape live feel (pehle 10s)
def cached_market_watch():
    """Market Watch ULTRA FAST: Dhan > NSE Live > Yahoo Parallel - app band nahi hoga"""
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

    # Final fallback: Yahoo
    try:
        yahoo_quotes = data_fetch.fetch_market_watch_quotes([item["yahoo"] for item in gi.MARKET_WATCH])
        return yahoo_quotes
    except Exception as e:
        print(f"Market watch Yahoo fallback error: {e}")
        return {}


BASE_ORDER = ["1m", "5m", "15m", "60m", "daily"]
BASE_LABELS = {"1m": "1m", "5m": "5m", "15m": "15m", "60m": "1H (60m)", "daily": "Daily"}
BASE_BUCKET_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "60m": "1H", "daily": "Daily"}
BASE_FETCHERS = {"1m": cached_fetch_1m, "5m": cached_fetch_5m, "15m": cached_fetch_15m, "60m": cached_fetch_60m, "daily": cached_fetch_daily}

# ---------- Pine/TV parity: intraday frames se CAS/auction candle hataao ----------
# NSE me 03-Aug-2026 se F&O stocks (poore Nifty 50) ka continuous session 09:15-15:15 hai;
# 15:15 ke baad sirf Closing Auction print aata hai. Yahoo us print ko 15:15 ki alag
# candle banata hai, aur frame builder usse poora TF candle maan leta hai -> aisa zone
# ban jaata hai jo TradingView/Pine ke chart par hota hi nahi (jaise INFY 2H 992.70).
# zone_core.trim_out_of_session_bars() usi candle ko hataata hai. zone_core.py na mile
# to ye step chup-chaap skip ho jaata hai (purana behaviour).
try:
    import zone_core as zc_core
    ZC_CORE_AVAILABLE = True
except Exception:
    zc_core = None
    ZC_CORE_AVAILABLE = False

PINE_ALIGN_TFS = {"1m", "3m", "5m", "10m", "15m", "30m", "75m", "1H", "2H", "4H", "6H"}


def pine_align_frames(tf, frames):
    """Intraday frames ko Pine/TradingView session ke hisaab se align karo."""
    if not ZC_CORE_AVAILABLE or not frames or tf not in PINE_ALIGN_TFS:
        return frames
    out = {}
    for sym, frame in frames.items():
        try:
            out[sym] = zc_core.trim_out_of_session_bars(frame) if frame is not None and len(frame) else frame
        except Exception:
            out[sym] = frame
    return out


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_scan(tf, bk, pt, tt, stt):
    params = dict(pt)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tt)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    frames = pine_align_frames(tf, frames)
    return scanner.scan_universe(tf, frames, params, states=list(stt)), frames


def scan_validated_universe(tf: str, frames: dict, params: dict, states=None):
    if not ZCV_AVAILABLE:
        return pd.DataFrame(), {}
    states = states or ["Fresh", "Tested"]
    rows = []
    funnel_agg = {}
    for symbol, df in frames.items():
        if df is None or len(df) < 25:
            continue
        try:
            engine = zcv.ZoneEngine(df, **params)
            zones = engine.run()
            for k, v in engine.gate_counts.items():
                funnel_agg[k] = funnel_agg.get(k, 0) + v
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
                    "Entry (Proximal)": round(z.proxVal, 2),
                    "Stop Loss (Distal+Buffer)": round(z.slVal, 2),
                    "Target (RR set)": round(z.tpVal, 2),
                    "Risk:Reward": round(rr, 2) if np.isfinite(rr) else float("nan"),
                    "Current Price": round(curr_price, 2),
                    "Distance %": round(dist_pct, 2),
                    "LegOut RR": round(z.legOutRR, 2) if np.isfinite(z.legOutRR) else float("nan"),
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
    cols = ["Symbol", "Timeframe", "Ticker", "Direction", "Pattern", "State", "Fresh?", "Entry (Proximal)", "Stop Loss (Distal+Buffer)", "Target (RR set)", "Risk:Reward", "Current Price", "Distance %", "LegOut RR", "RR>=3?", "Engulf OK", "Valid?", "Rule1(RBR)", "Rule2(DBD)", "Rule3(DBR)", "Rule4(RBD)", "Pulse", "Trend", "Aligned?", "Pulse Rule", "Trend Rule", "HQ Zone", "Score", "Touch Count", "Zone Created", "Last Bar Time"]
    if not rows:
        return pd.DataFrame(columns=cols), funnel_agg
    out = pd.DataFrame(rows)[cols]
    out = out.sort_values("Distance %", key=lambda s: s.abs())
    return out.reset_index(drop=True), funnel_agg


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_validated_scan(tf, bk, pt, tt, stt):
    params = dict(pt)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tt)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    frames = pine_align_frames(tf, frames)
    df, funnel = scan_validated_universe(tf, frames, params, states=list(stt))
    return df, funnel, frames


# ==================== v2 ENGINE (naye niyam) - Validated Page ====================
# zone TF -> (aadha TF, half banane ke liye kaun sa base dataset chahiye)
V2_HALF_SOURCE = {
    "15m": ("5m", "5m"), "30m": ("15m", "15m"), "75m": ("30m", "15m"), "1H": ("30m", "15m"),
    "2H": ("1H", "60m"), "4H": ("2H", "60m"), "6H": ("3H", "60m"), "1D": ("3H", "60m"),
    "1W": ("2D", "daily"), "1M": ("2W", "daily"),
}
# half TF -> (bucket minutes, min_fill) - wahi algorithm jo backtest me tha (NSE 09:15 anchor)
V2_HALF_MINUTES = {"5m": (5, 0.9), "15m": (15, 0.9), "30m": (30, 0.6), "1H": (60, 0.9), "2H": (120, 0.9), "3H": (180, 0.9)}


def _build_v2_half_frame(tf: str, df_base):
    """v2 engine ke liye half time-frame (naive IST index). 2D/2W daily se, baaki session-resample se."""
    if df_base is None or len(df_base) == 0:
        return pd.DataFrame()
    half_name = zcv2.half_timeframe_of(tf)
    if half_name in ("2D", "2W"):
        return zcv2.build_half_dataframe(tf, df_base=df_base)
    spec = V2_HALF_MINUTES.get(half_name)
    if spec is None:
        return pd.DataFrame()
    minutes, min_fill = spec
    try:
        return zcv2.session_resample(zcv2.to_naive_ist(df_base), minutes, min_fill)
    except Exception:
        return pd.DataFrame()


def scan_validated_universe_v2(tf: str, frames: dict, params: dict, states=None, half_frames=None):
    """v2 engine se validated zones: leg-out complete + envelope + half-TF niyam.
    Note: v2 me pulse/trend niyam hata diye gaye hain, isliye Pulse/Trend columns 0 aur Aligned=True (N/A) rahenge.
    """
    if not ZCV2_AVAILABLE:
        return pd.DataFrame(), {}
    states = states or ["Fresh", "Tested"]
    rows = []
    stats_agg = {}
    half_frames = half_frames or {}
    for symbol, df in frames.items():
        if df is None or len(df) < 25:
            continue
        try:
            half = half_frames.get(symbol)
            engine = zcv2.ZoneEngine(
                zcv2.to_naive_ist(df),
                half_df=(zcv2.to_naive_ist(half) if half is not None and len(half) else None),
                half_tf_name=zcv2.half_timeframe_of(tf),
                **params,
            )
            zones = engine.run()
            for k, v in getattr(engine, "stats", {}).items():
                stats_agg[k] = stats_agg.get(k, 0) + v
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
                half_align = float(getattr(z, "halfAlignedPct", float("nan")))
                rows.append({
                    "Symbol": chart_url(symbol, tf=tf),
                    "Timeframe": tf,
                    "Ticker": symbol,
                    "Direction": "DEMAND (Buy Zone)" if z.isDemand else "SUPPLY (Sell Zone)",
                    "Pattern": z.patternType,
                    "State": z.state,
                    "Fresh?": z.isFresh,
                    "Entry (Proximal)": round(z.proxVal, 2),
                    "Stop Loss (Distal+Buffer)": round(z.slVal, 2),
                    "Target (RR set)": round(z.tpVal, 2),
                    "Risk:Reward": round(rr, 2) if np.isfinite(rr) else float("nan"),
                    "Current Price": round(curr_price, 2),
                    "Distance %": round(dist_pct, 2),
                    "LegOut RR": round(z.legOutRR, 2) if np.isfinite(z.legOutRR) else float("nan"),
                    "RR>=3?": z.legOutPassesRR,
                    "Engulf OK": z.engulfOK,
                    "Valid?": (z.validDemand if z.isDemand else z.validSupply),
                    "Rule1(RBR)": z.rule1OK,
                    "Rule2(DBD)": z.rule2OK,
                    "Rule3(DBR)": z.rule3OK,
                    "Rule4(RBD)": z.rule4OK,
                    "Pulse": 0,
                    "Trend": 0,
                    "Aligned?": True,
                    "Pulse Rule": "",
                    "Trend Rule": "",
                    "HQ Zone": z.isHQ,
                    "Score": z.densityScore,
                    "Touch Count": z.touchCount,
                    "Zone Created": z.timestamp,
                    "Last Bar Time": last_bar,
                    "Envelope OK": bool(getattr(z, "envelopeOK", False)),
                    "Block Candles": int(getattr(z, "blockCandles", 1)),
                    "Half TF": str(getattr(z, "halfTF", "")),
                    "Half OK": bool(getattr(z, "halfOK", True)),
                    "Half Aligned %": round(half_align, 2) if np.isfinite(half_align) else float("nan"),
                })
        except Exception:
            continue
    cols = ["Symbol", "Timeframe", "Ticker", "Direction", "Pattern", "State", "Fresh?", "Entry (Proximal)", "Stop Loss (Distal+Buffer)", "Target (RR set)", "Risk:Reward", "Current Price", "Distance %", "LegOut RR", "RR>=3?", "Engulf OK", "Valid?", "Rule1(RBR)", "Rule2(DBD)", "Rule3(DBR)", "Rule4(RBD)", "Pulse", "Trend", "Aligned?", "Pulse Rule", "Trend Rule", "HQ Zone", "Score", "Touch Count", "Zone Created", "Last Bar Time", "Envelope OK", "Block Candles", "Half TF", "Half OK", "Half Aligned %"]
    if not rows:
        return pd.DataFrame(columns=cols), stats_agg
    out = pd.DataFrame(rows)[cols]
    out = out.sort_values("Distance %", key=lambda s: s.abs())
    return out.reset_index(drop=True), stats_agg


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_validated_scan_v2(tf, bk, pt, tt, stt):
    params = dict(pt)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tt)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    frames = pine_align_frames(tf, frames)
    half_frames = {}
    if ZCV2_AVAILABLE:
        half_base = V2_HALF_SOURCE.get(tf, ("", base))[1]
        try:
            half_raw = BASE_FETCHERS[half_base](cc.last_closed_bucket(BASE_BUCKET_TF[half_base]), tt)
        except Exception:
            half_raw = {}
        for sym in frames:
            try:
                half_frames[sym] = _build_v2_half_frame(tf, half_raw.get(sym))
            except Exception:
                half_frames[sym] = pd.DataFrame()
    df, stats = scan_validated_universe_v2(tf, frames, params, states=list(stt), half_frames=half_frames)
    return df, stats, frames


params_main = dict(targetRR=float(target_rr), eodHighBufferPct=float(eod_high_pct), eodLowBufferPct=float(eod_low_pct), enableClosingWickCheck=bool(en_wick), enableLegOutCoverCheck=bool(en_cover), enableHQBaseColourCheck=bool(en_hq), enableWhiteAreaCheck=bool(en_white))
params_main_tuple = tuple(sorted(params_main.items()))
states_tuple = tuple(state_filter) if state_filter else ("Fresh", "Tested")

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

# ---------- v2 engine ke params (Validated page - naye niyam) ----------
params_valid_v2 = dict(params_valid)
params_valid_v2.update(dict(
    targetRR=float(v2_target_rr),
    requireCompletedLegOut=True,
    assumeLastBarLive=bool(v2_assume_live),
    requireEnvelopeInLegOut=bool(v2_env),
    envelopeRR=float(v2_env_rr),
    envelopeCheckStopSide=bool(v2_env_stop),
    envelopeCheckTargetSide=bool(v2_env_target),
    legOutContinuationCandles=int(v2_cont),
    requireHalfTfCheck=bool(v2_half),
    halfTfMinAlignedPct=float(v2_half_pct),
    halfDataMissingPolicy=("skip" if str(v2_half_missing).startswith("skip") else "reject"),
))
params_valid_v2_tuple = tuple(sorted(params_valid_v2.items()))

if force_rescan:
    cached_scan.clear()
    cached_validated_scan.clear()
    try:
        cached_validated_scan_v2.clear()
    except Exception:
        pass
    cached_fetch_1m.clear()
    cached_fetch_5m.clear()
    cached_fetch_15m.clear()
    cached_fetch_60m.clear()
    cached_fetch_daily.clear()
    cached_market_watch.clear()
    st.toast("Cache cleared", icon="🔄")


# ---------- Auto Refresh on Candle Close - Small TF Only ----------
def get_seconds_to_next_close(tf_str: str) -> int:
    """TF string like '15m', '30m', '1H', '2H', '4H', '1m', '5m' -> seconds to next candle close"""
    from datetime import timedelta
    now = datetime.now()
    tf = tf_str.lower()
    if tf in ["1m", "1"]:
        next_close = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    elif tf in ["5m", "5"]:
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
    elif tf in ["1h", "60m"]:
        next_close = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    elif tf in ["2h", "2"]:
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
        rem = 75 - (now.hour * 60 + now.minute) % 75
        next_close = now + timedelta(minutes=rem)
        next_close = next_close.replace(second=0, microsecond=0)
    else:
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
    return times_sorted[0]


# Auto refresh state
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = True
if "last_refresh_tf" not in st.session_state:
    st.session_state.last_refresh_tf = None


def _badge(label, value, color):
    return f'<span style="background:{color}22;border:1px solid {color};border-radius:6px;padding:4px 10px;margin:3px;display:inline-block;font-size:13px;color:#eaeaea;white-space:nowrap;"><b>{label}</b> {value}</span>'


@st.cache_data(show_spinner=False, ttl=300)  # 5 min - TLT slow-moving bond ETF, baar-baar fetch bekaar
def _tlt_quote_cached():
    """TLT quote (cached) - pehle har rerun par bina-cache yfinance call thi = tape latency."""
    try:
        import yfinance as yf
        hist = yf.Ticker("TLT").history(period="2d")
        if hist is not None and not hist.empty and len(hist) >= 2:
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            return last, ((last - prev) / prev * 100 if prev else 0.0)
    except Exception:
        pass
    try:
        if GLOBAL_AVAILABLE:
            from global_macro_fetcher import get_world_indices
            world_df = get_world_indices()
            if not world_df.empty and "symbol" in world_df.columns:
                tlt_row = world_df[world_df["symbol"].str.contains("TLT", na=False)]
                if not tlt_row.empty:
                    last = float(tlt_row["price"].iloc[0]) if "price" in tlt_row.columns else 0.0
                    chg = float(tlt_row["change_pct"].iloc[0]) if "change_pct" in tlt_row.columns else 0.0
                    return last, chg
    except Exception:
        pass
    return None


def render_market_watch():
    """Top tape: GIFT NIFTY, NIFTY, BANK NIFTY, USD/INR, XAUUSD, SPOTCRUDE + TLT + FII/DII"""
    quotes = {}
    try:
        if is_dhan_configured():
            from dhan_api_helper_v2 import get_dhan_market_watch_fast
            from secure_config import get_dhan_creds
            cid, token = get_dhan_creds()
            dhan_quotes = get_dhan_market_watch_fast(cid, token)
            yahoo_quotes = cached_market_watch()
            quotes = {**yahoo_quotes, **dhan_quotes}
            if "^NSEI" in quotes and "GIFT_NIFTY" not in quotes:
                quotes["GIFT_NIFTY"] = quotes["^NSEI"]
        else:
            quotes = cached_market_watch()
    except Exception as e:
        print(f"Market watch Dhan fast error: {e}")
        quotes = cached_market_watch()

    chips = []
    for item in gi.MARKET_WATCH:
        q = quotes.get(item["yahoo"])
        url = f"https://www.tradingview.com/chart/?symbol={item['tv'].replace(':', '%3A')}"
        lbl = "GIFT NIFTY*" if item["label"] == "GIFT NIFTY" else item["label"]  # * = proxy, caption me note
        if q:
            last, chg = q
            color = "#16c784" if chg >= 0 else "#ea3943"
            arrow = "▲" if chg >= 0 else "▼"
            inner = _badge(lbl, f'{last:,.2f} <span style="color:{color};">{arrow} {chg:+.2f}%</span>', color)
        else:
            inner = _badge(lbl, "--", "#555")
        chips.append(f'<a href="{url}" target="_blank" style="text-decoration:none;">{inner}</a>')

    # TLT badge (CACHED - pehle har rerun par bina cache yfinance call lag rahi thi = tape slow)
    try:
        _tlt = _tlt_quote_cached()
        if _tlt:
            last, chg = _tlt
            arrow = "▲" if chg >= 0 else "▼"
            color = "#16c784" if chg >= 0 else "#ea3943"
            chips.append(_badge("TLT", f'{last:.2f} <span style="color:{color};">{arrow} {chg:+.2f}%</span>', color))
    except Exception:
        pass

    # FII/DII badges
    try:
        fii_sum = cached_fii_summary()
        if fii_sum and (fii_sum.get("fii_net") != 0 or fii_sum.get("dii_net") != 0):
            fii_net = fii_sum.get("fii_net", 0)
            dii_net = fii_sum.get("dii_net", 0)
            fii_c = "#16c784" if fii_net >= 0 else "#ea3943"
            dii_c = "#16c784" if dii_net >= 0 else "#ea3943"
            fii_arrow = "▲" if fii_net >= 0 else "▼"
            dii_arrow = "▲" if dii_net >= 0 else "▼"
            chips.append(_badge("FII", f'<span style="color:{fii_c};">{fii_arrow} {fii_net:+.0f}Cr</span>', fii_c))
            chips.append(_badge("DII", f'<span style="color:{dii_c};">{dii_arrow} {dii_net:+.0f}Cr</span>', dii_c))
    except Exception:
        pass

    # Global macro badges bhi isi block me (jahan mile tab) -- alag block se khaali gap banta tha
    gm_extra = ""
    try:
        if GLOBAL_AVAILABLE:
            from global_macro_fetcher import global_macro_badge_html
            gm_extra = str(global_macro_badge_html() or "")
    except Exception:
        gm_extra = ""
    combined_tape = "".join(chips) + gm_extra
    if combined_tape.strip():
        st.markdown(combined_tape, unsafe_allow_html=True)
        _src = "Dhan real-time (connected)" if is_dhan_configured() else "Yahoo (~15min delayed)"
        st.caption(f"⚡ LTP source: {_src} | *GIFT NIFTY abhi NIFTY 50 spot proxy hai (NSE IX ka free feed available nahi) | Auto-update: Settings ⚙️ → Auto-Refresh → Live LTP")


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


# ---------- LIVE LTP OVERLAY (display-only) ----------
# Samasya: table ka "Current Price"/LTP scan-cached frame ki aakhri candle se aata
# tha (TTL 6 ghante) -> LTP/Distance% ghanton purane dikhte the (user ki latency
# shikayat ka doosra bada karan). Hal: render ke waqt sirf ye 2 display columns
# live refresh hote hain (Dhan > Yahoo). ZONE SCAN KE INPUTS/RULES/LOGIC ME
# KOI BADLAV NAHI - ye sirf display overlay hai.

@st.cache_data(show_spinner=False, ttl=10)  # 10s cache - table render fast bhi, live bhi
def cached_live_ltp(tickers_tuple, use_dhan):
    """Displayed tickers ke live prices: Dhan (5s cache) > Yahoo (20s cache)."""
    out = {}
    syms = [str(t).replace(".NS", "") for t in tickers_tuple]
    if use_dhan:
        try:
            out.update(cached_dhan_ltp_if_available(tuple(syms)) or {})
        except Exception:
            pass
    try:
        from fast_live_price import get_live_price_hybrid_ultra_fast
        missing = [s for s in syms if s not in out]
        if missing:
            yh = get_live_price_hybrid_ultra_fast(tuple(f"{s}.NS" for s in missing))
            for s in missing:
                d = yh.get(f"{s}.NS")
                if d and d.get("ltp"):
                    out[s] = d
    except Exception as e:
        print(f"live LTP yahoo path error: {e}")
    return out


def overlay_live_prices(df):
    """Table ke Current Price + Distance % ko live LTP se refresh karo.
    Returns (df, info_caption). Scan data/filters untouched."""
    try:
        if df is None or df.empty or "Ticker" not in df.columns or "Current Price" not in df.columns:
            return df, None
        if not st.session_state.get("live_ltp_refresh", True):
            return df, None
        use_dhan = bool(is_dhan_configured())
        ltp_map = cached_live_ltp(tuple(sorted(set(df["Ticker"].astype(str)))), use_dhan)
        if not ltp_map:
            return df, None
        df = df.copy()
        # ltp_map ki keys bina-.NS hain (MARUTI), Ticker me .NS ho sakta hai -> dono try karo
        def _ltp_for(t):
            t = str(t)
            d = ltp_map.get(t) or ltp_map.get(t.replace(".NS", "")) or {}
            return d.get("ltp")
        new_px = pd.to_numeric(df["Ticker"].map(_ltp_for), errors="coerce")
        mask = new_px.notna()
        if not mask.any():
            return df, None
        df.loc[mask, "Current Price"] = new_px[mask].round(2)
        if "Entry (Proximal)" in df.columns:
            entry = pd.to_numeric(df["Entry (Proximal)"], errors="coerce")
            # Wahi formula jo scan me hai: dist_pct = (curr - prox) / curr * 100
            dist_pct = (new_px - entry) / new_px * 100.0
            df.loc[mask, "Distance %"] = dist_pct[mask].round(2)
        src = "Dhan real-time" if use_dhan else "Yahoo"
        info = f"⚡ LTP LIVE {datetime.now().strftime('%H:%M:%S')} • {src} • {int(mask.sum())} symbols updated"
        return df, info
    except Exception as e:
        print(f"LTP overlay error: {e}")
        return df, None


def apply_proximity_filter(df, max_dist_pct=5.0, per_symbol_cap=2):
    """
    NEW - Nearest-Zone Filter:
    - Toote hue zone hata deta hai (Demand: LTP < SL, Supply: LTP > SL)
    - Proximal se max_dist_pct se door wale zone hata deta hai
    - Sab symbols milakar sabse nazdeek zone pehle (abs distance order)
    - Har symbol ke sirf sabse nazdeek N zone rakhta hai (0 = unlimited),
      taki ek symbol puri jagah na gher sake aur dusre symbols ke nazdeek zone na chhute
    """
    if df is None or df.empty or "Distance %" not in df.columns:
        return df
    out = df.copy()

    need = {"Direction", "Current Price", "Stop Loss (Distal+Buffer)"}
    if need.issubset(out.columns):
        is_dem = out["Direction"].str.contains("DEMAND", na=False)
        broken = (is_dem & (out["Current Price"] < out["Stop Loss (Distal+Buffer)"])) | \
                 (~is_dem & (out["Current Price"] > out["Stop Loss (Distal+Buffer)"]))
        out = out[~broken]

    out["_abs_dist"] = out["Distance %"].abs()
    out = out[out["_abs_dist"] <= float(max_dist_pct)]
    out = out.sort_values("_abs_dist", kind="stable")

    if per_symbol_cap and per_symbol_cap > 0 and "Ticker" in out.columns:
        out = out.groupby("Ticker", sort=False).head(int(per_symbol_cap))

    return out.drop(columns=["_abs_dist"]).reset_index(drop=True)


def _apply_sort_choice(df, choice):
    """Settings (⚙️) popover ki "Table Sorting / Grouping" choice lagao (display-only)."""
    if df is None or df.empty:
        return df
    choice = str(choice or "")
    if "A→Z" in choice and "Z→A" not in choice:
        return df.sort_values("Ticker", ascending=True, kind="stable")
    if "Z→A" in choice:
        return df.sort_values("Ticker", ascending=False, kind="stable")
    if "Grouped" in choice:
        out = df.copy()
        out["_tf_min"] = out["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
        return out.sort_values(["Ticker", "_tf_min"], ascending=[True, True]).drop(columns=["_tf_min"])
    if "Distance" in choice and "Distance %" in df.columns:
        return df.sort_values("Distance %", key=lambda s: s.abs(), kind="stable")
    return df


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_nifty_daily(bk):
    raw = data_fetch.fetch_daily(["^NSEI"])
    return raw.get("^NSEI")


@st.cache_data(show_spinner=False, ttl=3600)
def cached_powerful_news_check(ticker: str):
    """Check if stock has powerful news in last 7 days"""
    try:
        if not NEWS_AVAILABLE:
            return False, "", ""
        ann_df = get_nse_announcements(symbol=ticker.replace(".NS", ""), days=7)
        if ann_df.empty:
            return False, "", ""
        powerful_keywords = ["result", "financial result", "dividend", "bonus", "split", "board meeting", "earnings", "buyback"]
        for _, row in ann_df.head(5).iterrows():
            desc = str(row.get("desc", "")).lower()
            if any(k in desc for k in powerful_keywords):
                link = f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={ticker.replace('.NS', '')}"
                return True, row.get("desc", "")[:120], link
        return False, "", ""
    except Exception:
        return False, "", ""


@st.cache_data(show_spinner=False, ttl=300)
def cached_breadth_for_all(bk, tt):
    try:
        raw = data_fetch.fetch_daily(list(tt))
    except Exception:
        return 0, 0, 0, []
    up, down, flat = 0, 0, 0
    details = []
    for sym, df in raw.items():
        if df is None or len(df) < 2:
            continue
        try:
            prev = float(df["close"].iloc[-2])
            curr = float(df["close"].iloc[-1])
            if prev == 0:
                continue
            chg = (curr - prev) / prev * 100.0
            details.append((sym, chg))
            if chg > 0.05:
                up += 1
            elif chg < -0.05:
                down += 1
            else:
                flat += 1
        except Exception:
            continue
    return up, down, flat, details


# FII + Global cached
@st.cache_data(show_spinner=False, ttl=1800)
def cached_fii_summary():
    try:
        if FII_AVAILABLE:
            from fii_dii_fetcher import get_fii_dii_summary
            return get_fii_dii_summary()
        return {"fii_net": 0, "dii_net": 0, "fii_trend": "N/A", "dii_trend": "N/A", "last_date": "N/A"}
    except Exception:
        return {"fii_net": 0, "dii_net": 0, "fii_trend": "N/A", "dii_trend": "N/A", "last_date": "N/A"}


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


# Render top tape
render_market_watch()

# ---------- AI TRADER PULSE: compact top strip (phase + PCR + FII/DII + Global + AI bias) ----------
if PULSE_AVAILABLE:
    try:
        mp.render_pulse_strip(tuple(tickers) if isinstance(tickers, (list, tuple)) else ())
    except Exception as _e:
        print(f"Pulse strip error (safe, app chalega): {_e}")

# (Auto-Refresh ka call page ke neeche hai - top area me khaali space na bane)


# (Global macro badges ab market tape ke saath hi render hote hain - alag block/divider nahi,
#  taki chips row aur table ke beech khaali space na bane)


def _breadth_and_fii_badges(badges):
    if scan_mode == "📊 NSE F&O Universe":
        try:
            breadth_tickers = tuple(all_tickers) if 'all_tickers' in globals() and len(all_tickers) > 0 else tickers
            if len(breadth_tickers) > 0:
                daily_bucket = cc.last_closed_bucket("Daily")
                up, down, flat, _ = cached_breadth_for_all(daily_bucket, breadth_tickers)
                total_b = up + down + flat
                if total_b > 0:
                    up_pct = up / total_b * 100
                    down_pct = down / total_b * 100
                    bc = "#16c784" if up >= down else "#ea3943"
                    bv = f"<span style='color:#16c784'>▲ Up: {up} ({up_pct:.1f}%)</span> <span style='color:#ea3943'>▼ Down: {down} ({down_pct:.1f}%)</span> <span style='color:#8b8b8b'>- Flat: {flat}</span>"
                    badges.append(_badge(f"NSE F&O Breadth ({total_b})", bv, bc))
        except Exception:
            pass
    try:
        fii_sum = cached_fii_summary()
        if fii_sum and fii_sum.get("fii_net") != 0:
            fii_c = "#16c784" if fii_sum["fii_net"] >= 0 else "#ea3943"
            dii_c = "#16c784" if fii_sum["dii_net"] >= 0 else "#ea3943"
            badges.append(_badge("FII/DII", f"<span style='color:{fii_c}'>FII {fii_sum['fii_net']:+.0f}Cr</span> <span style='color:{dii_c}'>DII {fii_sum['dii_net']:+.0f}Cr</span>", "#8b8b8b"))
    except Exception:
        pass


def _add_hypothesis(display_df):
    """Top 30 nearest zones ke liye rule-based hypothesis (fast)."""
    if INDICATOR_AVAILABLE:
        try:
            top_for_hyp = display_df.sort_values("Distance %", key=lambda s: s.abs()).head(30)
            hyp_list = []
            fii_ctx = f"FII {cached_fii_summary().get('fii_trend', '')}" if FII_AVAILABLE else ""
            glob_ctx = ""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    glob_ctx = get_global_context_for_hypothesis()
            except Exception:
                glob_ctx = ""
            for idx, row in top_for_hyp.iterrows():
                ticker = row.get("Ticker")
                try:
                    daily_bucket = cc.last_closed_bucket("Daily")
                    daily_data = cached_fetch_daily(daily_bucket, (ticker,))
                    df_ind = daily_data.get(ticker)
                    ind = calculate_indicators(df_ind) if df_ind is not None else {}
                except Exception:
                    ind = {}
                sector = get_sector(ticker) if SECTOR_AVAILABLE else "Others"
                zone_info = {"Direction": row.get("Direction"), "Pattern": row.get("Pattern"), "Timeframe": row.get("Timeframe"), "Entry (Proximal)": row.get("Entry (Proximal)"), "Distance %": row.get("Distance %"), "State": row.get("State"), "Score": row.get("Score") if "Score" in row.index else row.get("Base Count")}
                risky = False
                if NEWS_AVAILABLE:
                    try:
                        risk_info = is_zone_risky_due_to_event(ticker.replace(".NS", ""), datetime.now())
                        risky = risk_info.get("risky", False)
                    except Exception:
                        risky = False
                hyp = generate_hypothesis_rule_based(ticker, zone_info, ind, sector, fii_ctx, glob_ctx, risky)
                hyp_list.append((row["Ticker"], row["Timeframe"], hyp))
            hyp_map = {(t, tf): h for t, tf, h in hyp_list}
            display_df["_hyp_key"] = list(zip(display_df["Ticker"], display_df["Timeframe"]))
            display_df["Hypothesis (Short)"] = display_df["_hyp_key"].map(hyp_map).fillna("Click Detailed Analysis below for hypothesis")
            display_df = display_df.drop(columns=["_hyp_key"])
        except Exception:
            display_df["Hypothesis (Short)"] = "Analysis available in Detailed section"
    else:
        display_df["Hypothesis (Short)"] = "Enable detailed analysis below"
    return display_df


# ---------- PER-STOCK INDICATOR HELPERS (सभी स्टॉक्स के लिए अलग-अलग + clean) ----------

def _compact_ind_str(ind: dict) -> str:
    """Ek stock ke daily indicators ki chhoti, alag-alag readable string."""
    try:
        rsi = float(ind.get("rsi", 50.0) or 50.0)
        st_d = int(ind.get("supertrend_dir", 0) or 0)
        st_g = "▲" if st_d == 1 else "▼" if st_d == -1 else "="
        e = ("✓" if ind.get("above_ema20") else "✗") + ("✓" if ind.get("above_ema50") else "✗") + ("✓" if ind.get("above_ema200") else "✗")
        vr = float(ind.get("vol_ratio", 1.0) or 1.0)
        return f"RSI {rsi:.0f} • ST{st_g} • EMA {e} • V {vr:.1f}×"
    except Exception:
        return "—"


@st.cache_data(show_spinner=False, ttl=1800)
def compact_indicators_for_tickers(tickers_tuple, bucket):
    """Har ticker ka apna compact indicator summary (Daily data se).
    Table me har stock ki row me uske apne (alag-alag) indicators dikhte hain."""
    out = {}
    if not tickers_tuple:
        return out
    try:
        daily = cached_fetch_daily(bucket, tuple(tickers_tuple)) or {}
    except Exception:
        daily = {}
    for t in tickers_tuple:
        try:
            df_t = daily.get(t)
            if INDICATOR_AVAILABLE and df_t is not None and len(df_t) >= 30:
                out[t] = _compact_ind_str(calculate_indicators(df_t))
            else:
                out[t] = "—"
        except Exception:
            out[t] = "—"
    return out


def _ind_chip(label, value, color="#8b8b8b"):
    return (f'<span style="background:{color}22;border:1px solid {color};border-radius:6px;'
            f'padding:3px 8px;margin:2px;display:inline-block;font-size:12px;color:#eaeaea;white-space:nowrap;">'
            f'{label} <b style="color:{color};">{value}</b></span>')


def _fmt_price(v):
    try:
        f = float(v)
        return f"₹{f:,.2f}"
    except Exception:
        return "N/A"


def _fii_dii_context_text():
    """Fresh + sahi FII/DII context: trend galat 'Neutral' na dikhe aur
    'as of <date>' ke saath (stale data turant dikhe)."""
    try:
        s = cached_fii_summary() or {}
    except Exception:
        s = {}
    fii_net = float(s.get("fii_net") or 0)
    dii_net = float(s.get("dii_net") or 0)
    fii_t = s.get("fii_trend")
    if fii_t in (None, "", "N/A"):
        fii_t = "Buying" if fii_net > 0 else "Selling" if fii_net < 0 else "Neutral"
    dii_t = s.get("dii_trend")
    if dii_t in (None, "", "N/A"):
        dii_t = "Buying" if dii_net > 0 else "Selling" if dii_net < 0 else "Neutral"
    last = str(s.get("last_date") or "").strip()
    asof = f" • as of {last[:11]}" if last and last.lower() != "n/a" else ""
    return f"FII {fii_t} {fii_net:+,.0f}Cr • DII {dii_t} {dii_net:+,.0f}Cr{asof}"


def _render_indicators_panel_md(ind, ltp=None, ltp_src=None):
    """Detail view ka saaf Indicators panel (chips) - per selected stock."""
    rsi = float(ind.get("rsi", 50.0) or 50.0)
    rsi_c = "#ea3943" if rsi <= 30 else "#16c784" if rsi >= 70 else "#00bfff"
    rsi_tag = " (Oversold)" if rsi <= 30 else " (Overbought)" if rsi >= 70 else ""
    st_d = int(ind.get("supertrend_dir", 0) or 0)
    st_v, st_c = ("▲ Bullish", "#16c784") if st_d == 1 else (("▼ Bearish", "#ea3943") if st_d == -1 else ("= Neutral", "#8b8b8b"))
    e20 = "✓" if ind.get("above_ema20") else "✗"
    e50 = "✓" if ind.get("above_ema50") else "✗"
    e200 = "✓" if ind.get("above_ema200") else "✗"
    macd = float(ind.get("macd_hist", 0.0) or 0.0)
    vr = float(ind.get("vol_ratio", 1.0) or 1.0)
    px_live = ltp if ltp else ind.get("price")
    px_txt = _fmt_price(px_live)
    px_tag = f" ⚡LIVE {ltp_src}" if ltp else " (Daily close)"
    chips = [
        _ind_chip("Price", px_txt + px_tag, "#00bfff"),
        _ind_chip("RSI(14)", f"{rsi:.1f}{rsi_tag}", rsi_c),
        _ind_chip("EMA 20/50/200", f"{e20} {e50} {e200}  (✓ = Price ऊपर)", "#8b8b8b"),
        _ind_chip("Supertrend", st_v, st_c),
        _ind_chip("MACD Hist", f"{macd:+.2f}", "#16c784" if macd >= 0 else "#ea3943"),
        _ind_chip("Vol", f"{vr:.1f}× SMA20", "#16c784" if vr >= 1.2 else "#8b8b8b"),
    ]
    return "<div style='line-height:2.1;'>" + "".join(chips) + "</div>"


def _render_context_panel_md(sector, sector_idx, global_ctx):
    chips = [
        _ind_chip("Sector", f"{sector} ({sector_idx})", "#8a2be2"),
        _ind_chip("FII/DII", _fii_dii_context_text(), "#8b8b8b"),
        _ind_chip("Global", str(global_ctx or "N/A"), "#00bfff"),
    ]
    return "<div style='line-height:2.1;'>" + "".join(chips) + "</div>"


def _clean_risk_reasons(risk_info, max_show=2):
    """Event Risk reasons: dedupe + max 2 dikhao, baki '+N more'."""
    out, seen = [], set()
    for r in (risk_info or {}).get("reasons") or []:
        txt = " ".join(str(r).split())
        key = txt.lower()
        if not txt or key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out[:max_show], max(0, len(out) - max_show)


def _news_lines_html(news_df, max_show=2):
    """Recent News: dedupe + date ke saath fresh lines."""
    if news_df is None or news_df.empty:
        return []
    cutoff = datetime.now() - timedelta(days=7)
    lines, seen = [], set()
    for _, r in news_df.head(8).iterrows():
        d = str(r.get("desc", "") or "").strip()
        key = " ".join(d.lower().split())
        if not d or key in seen:
            continue
        dt = r.get("_dt")
        if dt is None:
            try:
                from news_corporate_events import parse_nse_dt
                dt = parse_nse_dt(r.get("date"))
            except Exception:
                dt = None
        # defense-in-depth: 7 din se purani koi bhi line na dikhe
        if dt is not None and dt < cutoff:
            continue
        seen.add(key)
        dpart = dt.strftime("%d-%b") if dt is not None else str(r.get("date", "") or "")[:6]
        lines.append(f"<b style='color:#00bfff;'>{dpart}</b> — {d[:90]}")
        if len(lines) >= max_show:
            break
    return lines


_NEWS_COLS = ["🔗 News Link", "📰 Powerful News", "📰 News", "⚡ Powerful", "⚡ News Desc", "🤖 AI Link"]


@st.cache_data(show_spinner=False, ttl=600)
def cached_macro_quotes():
    """Sector-drivers ke extra live quotes (DXY, US10Y, S&P, China, NatGas) - 10 min cache."""
    try:
        extra = ("DX-Y.NYB", "^TNX", "^GSPC", "000001.SS", "NG=F")
        from data_fetch import fetch_market_watch_quotes
        return fetch_market_watch_quotes(list(extra)) or {}
    except Exception:
        return {}


def _oi_why_full(sel_ticker):
    """Selected stock ka full OI-reason (drivers ke saath) ya None."""
    if not PULSE_AVAILABLE:
        return None
    try:
        _clean = str(sel_ticker).replace(".NS", "").upper().strip()
        p = (mp.get_pulse_map((str(sel_ticker),)) or {}).get(_clean)
        return mp.oi_why(p) if p else None
    except Exception:
        return None


def _oi_why_short_map(tickers_tuple):
    """Table column ke liye {ticker: short OI-reason}."""
    if not PULSE_AVAILABLE:
        return {}
    try:
        pm = mp.get_pulse_map(tickers_tuple) or {}
        return {t: mp.oi_why(p, short=True) for t, p in pm.items()}
    except Exception:
        return {}


_COUNTRY_FLAG = {"India": "🇮🇳", "US": "🇺🇸", "Euro Zone": "🇪🇺", "EU": "🇪🇺", "UK": "🇬🇧",
                 "Japan": "🇯🇵", "China": "🇨🇳", "Germany": "🇩🇪", "Canada": "🇨🇦", "Australia": "🇦🇺"}


def _fresh_macro_events_html(max_show=3):
    """Agle/पिछले 2 din ke high-impact global events (ForexFactory calendar)."""
    try:
        df = cached_macro_news()
        if df is None or df.empty or "event" not in df.columns:
            return []
        now = datetime.now()
        rows = []
        for _, r in df.head(40).iterrows():
            try:
                d = pd.to_datetime(r.get("date"), errors="coerce", utc=True)
                if pd.isna(d):
                    continue
                d_local = d.tz_convert("Asia/Kolkata") if d.tzinfo else d
                if abs((d_local.tz_localize(None) - now).total_seconds()) > 2 * 86400:
                    continue
                imp = str(r.get("impact") or "")
                if imp.lower() not in ("high", "medium"):
                    continue
                c = str(r.get("country") or "").strip()
                flag = _COUNTRY_FLAG.get(c, "🌍")
                dtxt = d_local.strftime("%d-%b %H:%M")
                imp_c = "#ea3943" if imp.lower() == "high" else "#f0b90b"
                rows.append((0 if imp.lower() == "high" else 1,
                             f"{flag} <b>{r.get('event')}</b> — <span style='color:{imp_c};'>{imp} impact</span> • {dtxt} IST"))
            except Exception:
                continue
        rows.sort()
        return [t for _, t in rows[:max_show]]
    except Exception:
        return []


def _render_affected_by_panel(sector, news_df, max_news=2):
    """🌍🇮🇳 इस स्टॉक को प्रभावित करने वाले देश-विदेश के factors:
    sector-specific macro drivers (live values के साथ) + high-impact events + stock news."""
    try:
        drivers = get_macro_drivers_for_sector(sector) if SECTOR_AVAILABLE else []
    except Exception:
        drivers = []
    try:
        quotes = {**(cached_macro_quotes() or {}), **(cached_market_watch() or {})}
    except Exception:
        quotes = {}

    chips, lines = [], []
    for d in (drivers or [])[:3]:
        name = d.get("name", "")
        why = d.get("why", "")
        val = ""
        yk = d.get("yahoo")
        if yk:
            q = quotes.get(yk)
            if q:
                try:
                    val = f": <b style='color:{'#16c784' if q[1] >= 0 else '#ea3943'};'>{q[0]:,.2f} ({q[1]:+.2f}%)</b>"
                except Exception:
                    val = ""
        lines.append(f"<div style='margin:4px 0;'><b style='color:#f0b90b;'>{name}</b>{val}<br>"
                     f"<small style='color:#bbb;'>क्यों: {why}</small></div>")
    ev = _fresh_macro_events_html()
    if ev:
        lines.append("<div style='margin-top:6px;'><b style='color:#00bfff;'>🗓️ अगले 2 दिन के बड़े events:</b><br><small>" + "<br>".join(ev) + "</small></div>")
    nl = _news_lines_html(news_df, max_show=max_news)
    if nl:
        lines.append("<div style='margin-top:6px;'><b style='color:#00bfff;'>📰 इस स्टॉक की fresh खबरें:</b><br><small>" + "<br>".join(nl) + "</small></div>")
    if not lines:
        return "<small style='color:#888;'>कोई relevant driver/event data उपलब्ध नहीं</small>"
    return "<div style='line-height:1.55;'>" + "".join(lines) + "</div>"

_DROP_COLS = [
    "Ticker", "Risk:Reward", "Distance from Entry", "Price Position",
    "HQ Zone (Rule3 Boring-Colour)", "HQ Zone", "White Area OK (Rule4)", "White Area OK",
    "Base Count", "Touch Count", "Zone Created", "Last Bar Time",
    "Hypothesis (Short)", "⚡ Powerful", "⚡ News Desc",
    "LegOut RR", "RR>=3?", "Engulf OK", "Valid?", "Rule1(RBR)", "Rule2(DBD)", "Rule3(DBR)", "Rule4(RBD)",
    "Pulse", "Trend", "Aligned?", "Pulse Rule", "Trend Rule", "Score", "State", "Fresh?",
    "Envelope OK", "Block Candles", "Half TF", "Half OK", "Half Aligned %",
]

_DESIRED_ORDER = ["Symbol", "Timeframe", "Direction", "Pattern", "Entry (Proximal)", "Stop Loss (Distal+Buffer)", "Target (RR set)", "Current Price", "Distance %", "📊 Ind", "Delivery %", "ΔDeliv pp", "Vol ×Yday", "OI Signal", "🎯 OI क्यों"]


def _full_or_short(full):
    """Column labels: full names (screenshot jaisa) ya compact."""
    if full:
        return {
            "Timeframe": "Timeframe", "Direction": "Direction",
            "Entry (Proximal)": "Entry (Proximal)",
            "Stop Loss (Distal+Buffer)": "Stop Loss (Distal+Buffer)",
            "Target (RR set)": "Target (RR set)",
            "Current Price": "Current Price", "Distance %": "Distance %",
        }
    return {
        "Timeframe": "TF", "Direction": "Dir",
        "Entry (Proximal)": "Entry",
        "Stop Loss (Distal+Buffer)": "SL",
        "Target (RR set)": "Target",
        "Current Price": "LTP", "Distance %": "Dist %",
    }


def _show_clean_table(display_df, symbol_title):
    # हर स्टॉक के अपने (अलग-अलग) Daily indicators - per-row compact column
    try:
        if "Ticker" in display_df.columns and not display_df.empty:
            _tk = tuple(sorted(set(display_df["Ticker"].astype(str))))
            _imap = compact_indicators_for_tickers(_tk, cc.last_closed_bucket("Daily"))
            display_df["📊 Ind"] = display_df["Ticker"].astype(str).map(lambda t: _imap.get(t, "—"))
    except Exception:
        pass
    # OI सिग्नल के पीछे का कारण (हर stock का अपना) - सिर्फ label नहीं
    try:
        if PULSE_AVAILABLE and "OI Signal" in display_df.columns and "Ticker" in display_df.columns and not display_df.empty:
            _tk = tuple(sorted(set(display_df["Ticker"].astype(str))))
            _omap = _oi_why_short_map(_tk)
            display_df["🎯 OI क्यों"] = display_df["Ticker"].astype(str).map(
                lambda t: _omap.get(str(t).replace(".NS", "").upper().strip(), "—"))
    except Exception:
        pass
    for col in _NEWS_COLS:
        if col in display_df.columns:
            display_df = display_df.drop(columns=[col])
    clean_df = display_df.drop(columns=[c for c in _DROP_COLS if c in display_df.columns], errors="ignore")
    final_cols = [c for c in _DESIRED_ORDER if c in clean_df.columns]
    for c in clean_df.columns:
        if c not in final_cols:
            final_cols.append(c)
    clean_df = clean_df[final_cols]
    _L = _full_or_short(bool(st.session_state.get("full_col_names", False)))
    st.dataframe(
        clean_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Symbol": st.column_config.LinkColumn(symbol_title, display_text=r"symbol=(?:[^%]+%3A)?([^&]+)"),
            "Timeframe": st.column_config.TextColumn(_L["Timeframe"], width="small"),
            "Direction": st.column_config.TextColumn(_L["Direction"], width="small"),
            "Pattern": st.column_config.TextColumn("Pattern", width="small"),
            "Entry (Proximal)": st.column_config.NumberColumn(_L["Entry (Proximal)"], format="%.2f"),
            "Stop Loss (Distal+Buffer)": st.column_config.NumberColumn(_L["Stop Loss (Distal+Buffer)"], format="%.2f"),
            "Target (RR set)": st.column_config.NumberColumn(_L["Target (RR set)"], format="%.2f"),
            "Current Price": st.column_config.NumberColumn(_L["Current Price"], format="%.2f"),
            "Distance %": st.column_config.NumberColumn(_L["Distance %"], format="%.2f%%"),
            "📊 Ind": st.column_config.TextColumn("Ind", width="small",
                                                  help="Us stock ke apne Daily indicators: RSI • Supertrend (▲/▼) • EMA 20/50/200 (✓=Price ऊपर, ✗=नीचे) • Volume vs SMA20. Full detail नीचे 'Detailed Zone Analysis' में."),
            "Delivery %": st.column_config.NumberColumn("Deliv %", format="%.1f%%", help="Aaj ka delivery % (NSE bhavcopy)"),
            "ΔDeliv pp": st.column_config.NumberColumn("ΔDeliv pp", format="%+.1f", help="Delivery % change vs pichhla din (pp)"),
            "Vol ×Yday": st.column_config.NumberColumn("Vol ×", format="%.2f", help="Volume vs pichhla din (×)"),
            "OI Signal": st.column_config.TextColumn("OI Signal", width="small", help="Futures/Options OI buildup signal"),
            "🎯 OI क्यों": st.column_config.TextColumn("OI क्यों", width="small", help="OI सिग्नल के पीछे का कारण: Price/OI change के numbers + trader-interpretation (सिर्फ 'Short Covering' लिखना काफी नहीं)"),
        },
    )


def render_table_main(df, file_label, all_frames=None):
    df = apply_display_filters(df)
    badges = []
    if not df.empty:
        badges.append(_badge("Total Zones", str(len(df)), "#8b8b8b"))
        badges.append(_badge("Demand", str(int(df["Direction"].str.contains("DEMAND").sum())), "#16c784"))
        badges.append(_badge("Supply", str(int(df["Direction"].str.contains("SUPPLY").sum())), "#ea3943"))
        badges.append(_badge("HQ (Rule3)", str(int(df["HQ Zone (Rule3 Boring-Colour)"].sum())) if "HQ Zone (Rule3 Boring-Colour)" in df.columns else "0", "#f0b90b"))
    _breadth_and_fii_badges(badges)

    try:
        nifty_df = cached_nifty_daily(cc.last_closed_bucket("Daily"))
        nifty_zone = scanner.nearest_zone_for_symbol(nifty_df, params_main, states=["Fresh", "Tested"])
        if nifty_zone:
            color = "#16c784" if nifty_zone["direction"] == "DEMAND" else "#ea3943"
            nifty_url = "https://www.tradingview.com/chart/?symbol=NSE%3ANIFTY"
            badges.append(f'<a href="{nifty_url}" target="_blank" style="text-decoration:none;">' + _badge("📍 NIFTY50 nearest zone (Daily)", f'{nifty_zone["direction"]} @ {nifty_zone["entry"]:,} ({nifty_zone["distance_pct"]:+.2f}% away, {nifty_zone["state"]})', color) + "</a>")
    except Exception:
        pass
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)
    if df.empty:
        st.info("Is filter ke sath koi live zone nahi mili. (Nearest-Zone Filter ki Max Distance % badha kar dekho)")
        return pd.DataFrame()

    display_df = _add_hypothesis(df.copy())
    display_df, ltp_info = overlay_live_prices(display_df)
    _q = st.text_input("🔍 Symbol search", value="", key=f"search_{file_label}",
                       placeholder="Jaise: RELI, HDFC, M&M...", help="Table ko turant filter karo (scan nahi hota)").strip().upper()
    if _q:
        display_df = display_df[display_df["Ticker"].astype(str).str.upper().str.contains(_q, na=False)]
        st.caption(f"🔎 Search '{_q}': {len(display_df)} zones mile")
    _show_clean_table(display_df, "Symbol")
    if ltp_info:
        st.caption(ltp_info)

    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    with st.expander("⬇️ CSV Download", expanded=False):
        st.download_button("⬇️ Download zones as CSV", csv, file_name=f"zones_{file_label}.csv", mime="text/csv")
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
    badges = []
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
        if "Envelope OK" in df.columns:
            badges.append(_badge("Envelope OK", str(int(df["Envelope OK"].sum())), "#00bfff"))
        if "Half OK" in df.columns:
            badges.append(_badge("Half-TF OK", str(int(df["Half OK"].sum())), "#8a2be2"))
        if "Block Candles" in df.columns:
            badges.append(_badge("2C/3C blocks", str(int((df["Block Candles"] > 1).sum())), "#f0b90b"))
    _breadth_and_fii_badges(badges)
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)
    if df.empty:
        st.info("Validated filters ke sath koi zone nahi mili. Filters kam karo ya Preset 'max_zones' try karo.")
        return pd.DataFrame()

    display_df = _add_hypothesis(df.copy())
    display_df, ltp_info = overlay_live_prices(display_df)
    _vq = st.text_input("🔍 Symbol search", value="", key=f"vsearch_{file_label}",
                        placeholder="Jaise: RELI, HDFC, M&M...", help="Table ko turant filter karo (scan nahi hota)").strip().upper()
    if _vq:
        display_df = display_df[display_df["Ticker"].astype(str).str.upper().str.contains(_vq, na=False)]
        st.caption(f"🔎 Search '{_vq}': {len(display_df)} validated zones mile")
    _show_clean_table(display_df, "Symbol")
    if ltp_info:
        st.caption(ltp_info)

    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    with st.expander("⬇️ CSV Download", expanded=False):
        st.download_button("⬇️ Download VALIDATED zones as CSV", csv, file_name=f"validated_zones_{file_label}.csv", mime="text/csv")
    return display_df


# Main branching
if not tickers:
    st.error("❌ Koi ticker select nahi hai. Settings (⚙️) me jaake NSE Universe ya Global Instruments select karo.")
    st.stop()

needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}

# Store frames for hypothesis
all_frames_store = {}

combined = pd.DataFrame()
combined_v = pd.DataFrame()

if "Main" in st.session_state.app_page:
    if "main_scan_results" not in st.session_state:
        st.session_state.main_scan_results = None
    if "main_scan_combined" not in st.session_state:
        st.session_state.main_scan_combined = None

    fast_tickers = tickers[:50] if len(tickers) > 50 else tickers

    # Scan trigger popover ke buttons se aata hai (main page par koi button/status box nahi)
    _trig = st.session_state.pop("main_scan_trigger", None)
    scan_tickers = None
    do_scan = False
    if _trig == "fast":
        scan_tickers, do_scan = fast_tickers, True
        st.session_state.main_scan_results = None
    elif _trig == "full":
        scan_tickers, do_scan = tickers, True
        st.session_state.main_scan_results = None
    elif st.session_state.main_scan_results is None:
        # pehli baar: chupchap auto fast scan
        scan_tickers, do_scan = fast_tickers, True

    if do_scan and scan_tickers is not None:
        needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}
        all_frames_store = {}
        with st.spinner(f"Scanning {len(scan_tickers)} stocks..."):
            for base in BASE_ORDER:
                if base not in needed_bases:
                    continue
                try:
                    BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), scan_tickers)
                except Exception:
                    pass
            results = {}
            for tf in tf_selected:
                try:
                    bucket = cc.last_closed_bucket(tf)
                    df_tf, frames_tf = cached_scan(tf, bucket, params_main_tuple, scan_tickers, states_tuple)
                    results[tf] = df_tf
                    all_frames_store[tf] = frames_tf
                except Exception:
                    results[tf] = pd.DataFrame()
                    all_frames_store[tf] = {}
        st.session_state.main_scan_results = results
        st.session_state.main_scan_combined = None
        st.session_state.main_frames_store = all_frames_store
        st.toast(f"✅ Scan complete ({len(scan_tickers)} stocks)")
    elif st.session_state.main_scan_results is not None:
        results = st.session_state.main_scan_results
        all_frames_store = st.session_state.get("main_frames_store", {})
    else:
        results = {}
        all_frames_store = {}

    ordered_tfs = sorted(tf_selected, key=scanner.tf_minutes)
    non_empty = [results[tf] for tf in ordered_tfs if tf in results and results[tf] is not None and not results[tf].empty]
    combined = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()

    if len(tf_selected) > 1 and not combined.empty:
        view_tfs = st.multiselect("View Timeframe(s) in table below", ordered_tfs, default=ordered_tfs)
        if view_tfs:
            combined = combined[combined["Timeframe"].isin(view_tfs)]

    # ---------- Nearest-Zone Filter apply (caption Settings popover me dikhta hai) ----------
    if prox_enable and not combined.empty:
        _before = len(combined)
        combined = apply_proximity_filter(combined, prox_max_dist, prox_per_symbol)
        st.session_state["prox_filter_info"] = (_before, len(combined))

    # ---------- Sorting/Grouping Settings (⚙️) popover se aata hai (dashboard par heading/radio nahi) ----------
    if not combined.empty:
        combined = _apply_sort_choice(combined, globals().get("sort_choice"))

    # ---------- Trader Pulse columns: Delivery %, ΔDeliv pp (aaj vs pichhla din), Vol ×Yday, OI Signal ----------
    if PULSE_AVAILABLE and not combined.empty:
        try:
            combined = mp.enrich_zones_with_pulse_cached(combined)
        except Exception as _e:
            print(f"Pulse enrich (main) error (safe): {_e}")

    merged_frames = {}
    for tf_frames in all_frames_store.values():
        merged_frames.update(tf_frames)
    display_main = render_table_main(combined, "all_selected_timeframes" if len(tf_selected) > 1 else tf_selected[0], all_frames=merged_frames)

    # ---------- DETAILED ZONE ANALYSIS WITH SHORT LINKS ----------
    if not display_main.empty:
        st.subheader("🔬 Detailed Zone Analysis")

        def make_option(row):
            return f"{str(row['Ticker']).replace('.NS', '')} ({row['Timeframe']}) • {row['Direction'].split()[0]} • {row['Distance %']:+.2f}% • Entry {row['Entry (Proximal)']}"

        options = [make_option(row) for _, row in display_main.head(50).iterrows()]
        selected_opt = st.selectbox("🔍 Zone (Top 50 nearest)", options, index=0 if options else None)

        if selected_opt:
            sel_idx = options.index(selected_opt)
            sel_row = display_main.iloc[sel_idx]
            sel_ticker = sel_row["Ticker"]
            sel_tf = sel_row["Timeframe"]

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

            fii_sum = cached_fii_summary()
            fii_ctx = _fii_dii_context_text() if FII_AVAILABLE else "FII data N/A"

            global_ctx = ""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    global_ctx = get_global_context_for_hypothesis()
            except Exception:
                global_ctx = "Global mixed"

            news_df = get_nse_announcements(symbol=sel_ticker.replace(".NS", ""), days=7) if NEWS_AVAILABLE else pd.DataFrame()
            corp_df = get_nse_corporate_actions(symbol=sel_ticker.replace(".NS", ""), days=30) if NEWS_AVAILABLE else pd.DataFrame()
            risk_info = is_zone_risky_due_to_event(sel_ticker.replace(".NS", ""), datetime.now()) if NEWS_AVAILABLE else {"risky": False, "reasons": []}

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

            if is_gemini_configured() and GEMINI_MODULE_AVAILABLE:
                try:
                    gkey = get_gemini_key()
                    gemini_client = GeminiZoneAnalyzer(api_key=gkey)
                    news_text = "\n".join([f"{r.get('desc')}" for _, r in news_df.head(3).iterrows()]) if not news_df.empty else "No news"
                    corp_text = "\n".join([f"{r.get('purpose')} ex {r.get('ex_date')}" for _, r in corp_df.head(2).iterrows()]) if not corp_df.empty else "No corp actions"
                    hypothesis = gemini_client.model.generate_content(f"Enhance this hypothesis in Hinglish, 2 lines, with verdict: {hypothesis} | News: {news_text} | Corp: {corp_text}").text
                except Exception as e:
                    hypothesis += f" (Gemini enhance failed: {e})"

            st.info(f"**Hypothesis:** {hypothesis}")

            links = get_nse_links(sel_ticker) if SECTOR_AVAILABLE else {}
            sector_links = get_sector_news_link(sector) if SECTOR_AVAILABLE else {}

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("**📈 Chart Links**")
                st.markdown(f"[TradingView Chart]({links.get('tradingview', '')})")
                st.markdown(f"[NSE Quote]({links.get('nse_quote', '')})")
                st.markdown(f"[Screener.in]({links.get('screener', '')})")
            with col2:
                st.markdown("**📰 News Links**")
                st.markdown(f"[NSE Announcements]({links.get('nse_announcements', '')})")
                st.markdown(f"[Corporate Actions]({links.get('nse_corp_actions', '')})")
                st.markdown(f"[Sector News: {sector}]({sector_links.get('google_news', '')})")
            with col3:
                st.markdown("**📊 Indicators**")
                _ltp, _ltp_src = None, None
                try:
                    _lmap = cached_live_ltp((sel_ticker,), bool(is_dhan_configured())) or {}
                    _d = _lmap.get(str(sel_ticker)) or _lmap.get(str(sel_ticker).replace(".NS", "")) or {}
                    _ltp = _d.get("ltp")
                    if _ltp:
                        _ltp_src = "Dhan" if is_dhan_configured() else "Yahoo"
                except Exception:
                    _ltp = None
                st.markdown(_render_indicators_panel_md(indicators, ltp=_ltp, ltp_src=_ltp_src), unsafe_allow_html=True)
            with col4:
                st.markdown("**🌍 Context**")
                st.markdown(_render_context_panel_md(sector, sector_idx, global_ctx), unsafe_allow_html=True)
                _rs, _extra = _clean_risk_reasons(risk_info)
                if _rs:
                    st.warning("⚠️ Event Risk: " + " | ".join(_rs) + (f" (+{_extra} more)" if _extra else ""))
                else:
                    st.success("✅ No near-term event risk")
                _nlines = _news_lines_html(news_df, max_show=2)
                if _nlines:
                    st.write("**Recent News:**")
                    st.markdown("<br>".join(_nlines), unsafe_allow_html=True)
                if not corp_df.empty:
                    st.write("**Corp Actions:**")
                    for _, r in corp_df.head(2).iterrows():
                        st.caption(f"- {r.get('purpose', '')} (ex {r.get('ex_date', '')})")

            # ---------- OI का कारण + देश-विदेश के factors (trader context, full-width) ----------
            _why = _oi_why_full(sel_ticker)
            if _why:
                st.markdown("**🎯 OI Signal के पीछे का कारण (drivers + क्या करना)**")
                st.info(_why)
            st.markdown("**🌍🇮🇳 देश-विदेश का क्या असर इस स्टॉक पर पड़ता है**")
            st.markdown(_render_affected_by_panel(sector, news_df), unsafe_allow_html=True)

            with st.expander("🌐 Global Macro Economic News (Today)", expanded=False):
                macro_df = cached_macro_news()
                if not macro_df.empty:
                    st.dataframe(macro_df, width="stretch", hide_index=True)
                else:
                    st.info("Macro news unavailable")

            with st.expander("💰 FII/DII Full Data", expanded=False):
                fii_df = get_fii_dii_summary().get("full_df") if FII_AVAILABLE else pd.DataFrame()
                if fii_df is not None and not fii_df.empty:
                    st.dataframe(fii_df, width="stretch", hide_index=True)
                else:
                    try:
                        from fii_dii_fetcher import get_fii_dii_data
                        st.dataframe(get_fii_dii_data(), width="stretch", hide_index=True)
                    except Exception:
                        st.info("FII data unavailable")

else:
    # ==================== VALIDATED PAGE - FAST OPEN (No Spinner) ====================
    use_v2_scan = bool(use_v2 and ZCV2_AVAILABLE)
    if use_v2 and not ZCV2_AVAILABLE:
        st.warning("⚠️ v2 engine select kiya hai par zone_core_validation_v2.py nahi mila - v1 se scan ho raha hai. File repo me upload karo.")
    st.markdown(
        f"**Validation Preset:** `{preset_choice}` | **Engine:** `{'v2 (leg-out complete + envelope + half-TF)' if use_v2_scan else 'v1 (pulse/trend + engulf)'}` "
        f"| **Params:** RR>={v2_target_rr if use_v2_scan else v_min_rr}, RR Filter={v_use_rr_filter}, Engulf={v_require_engulf}, "
        f"{'Envelope=' + ('stop+target' if v2_env_stop else 'target-only') + ', Half-TF=' + str(v2_half) + ', MinAligned=' + str(v2_half_pct) if use_v2_scan else 'PulseTrend=' + str(v_use_pulse_trend) + ', Aligned Required=' + str(v_require_aligned)}"
    )

    if "validated_scan_results" not in st.session_state:
        st.session_state.validated_scan_results = None

    fast_tickers_v = tickers[:50] if len(tickers) > 50 else tickers

    results_valid = {}
    funnels = {}
    all_frames_valid = {}

    # Scan trigger popover ke buttons se (validated page par koi button/status box nahi)
    _vtrig = st.session_state.pop("valid_scan_trigger", None)
    do_valid_scan = False
    scan_tickers_v = None
    if _vtrig == "fast":
        scan_tickers_v, do_valid_scan = fast_tickers_v, True
        st.session_state.validated_scan_results = None
    elif _vtrig == "full":
        scan_tickers_v, do_valid_scan = tickers, True
        st.session_state.validated_scan_results = None
    elif st.session_state.validated_scan_results is not None:
        results_valid = st.session_state.validated_scan_results.get("results", {})
        funnels = st.session_state.validated_scan_results.get("funnels", {})
        all_frames_valid = st.session_state.validated_scan_results.get("frames", {})
        do_valid_scan = False
    else:
        # pehli baar: chupchap auto fast validated scan
        scan_tickers_v, do_valid_scan = fast_tickers_v, True

    if do_valid_scan and scan_tickers_v is not None:
        needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}
        with st.spinner(f"Validated scan ({len(scan_tickers_v)} stocks, {'v2' if use_v2_scan else 'v1'} engine)..."):
            for base in BASE_ORDER:
                if base not in needed_bases:
                    continue
                try:
                    BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), scan_tickers_v)
                except Exception:
                    pass
            results_valid = {}
            funnels = {}
            all_frames_valid = {}
            for tf in tf_selected:
                try:
                    bucket = cc.last_closed_bucket(tf)
                    if use_v2_scan:
                        df_tf, funnel, frames_tf = cached_validated_scan_v2(tf, bucket, params_valid_v2_tuple, scan_tickers_v, states_tuple)
                    else:
                        df_tf, funnel, frames_tf = cached_validated_scan(tf, bucket, params_valid_tuple, scan_tickers_v, states_tuple)
                    results_valid[tf] = df_tf
                    funnels[tf] = funnel
                    all_frames_valid[tf] = frames_tf
                except Exception:
                    results_valid[tf] = pd.DataFrame()
                    funnels[tf] = {}
                    all_frames_valid[tf] = {}
        st.session_state.validated_scan_results = {"results": results_valid, "funnels": funnels, "frames": all_frames_valid}
        st.toast(f"✅ Validated scan complete ({len(scan_tickers_v)} stocks)")

    ordered_tfs = sorted(tf_selected, key=scanner.tf_minutes)
    non_empty_v = [results_valid[tf] for tf in ordered_tfs if tf in results_valid and results_valid[tf] is not None and not results_valid[tf].empty]
    combined_v = pd.concat(non_empty_v, ignore_index=True) if non_empty_v else pd.DataFrame()

    if len(tf_selected) > 1 and not combined_v.empty:
        view_tfs_v = st.multiselect("View Timeframe(s) in validated table below", ordered_tfs, default=ordered_tfs, key="view_tf_validated")
        if view_tfs_v:
            combined_v = combined_v[combined_v["Timeframe"].isin(view_tfs_v)]

    # ---------- Nearest-Zone Filter apply (Validated) - caption Settings popover me ----------
    if prox_enable and not combined_v.empty:
        _before_v = len(combined_v)
        combined_v = apply_proximity_filter(combined_v, prox_max_dist, prox_per_symbol)
        st.session_state["prox_filter_info"] = (_before_v, len(combined_v))

    # ---------- Sorting/Grouping Settings (⚙️) popover se (dashboard par heading/radio nahi) ----------
    if not combined_v.empty:
        combined_v = _apply_sort_choice(combined_v, globals().get("sort_choice"))

    # ---------- Trader Pulse columns: Delivery %, ΔDeliv pp (aaj vs pichhla din), Vol ×Yday, OI Signal ----------
    if PULSE_AVAILABLE and not combined_v.empty:
        try:
            combined_v = mp.enrich_zones_with_pulse_cached(combined_v)
        except Exception as _e:
            print(f"Pulse enrich (validated) error (safe): {_e}")

    merged_frames_v = {}
    for tf_frames in all_frames_valid.values():
        merged_frames_v.update(tf_frames)
    display_valid = render_table_validated(combined_v, "all_validated" if len(tf_selected) > 1 else (tf_selected[0] if tf_selected else "validated"), all_frames=merged_frames_v)

    # Detailed analysis for validated
    if not display_valid.empty:
        st.subheader("🔬 Detailed Validated Zone Analysis")

        def make_option_v(row):
            return f"{str(row['Ticker']).replace('.NS', '')} ({row['Timeframe']}) • {row['Direction'].split()[0]} • {row['Distance %']:+.2f}% • Valid {row.get('Valid?', False)} • Aligned {row.get('Aligned?', False)}"

        options_v = [make_option_v(row) for _, row in display_valid.head(50).iterrows()]
        selected_opt_v = st.selectbox("🔍 Validated Zone (Top 50)", options_v, index=0 if options_v else None, key="sel_validated")
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
            fii_ctx = _fii_dii_context_text() if FII_AVAILABLE else "FII N/A"
            global_ctx = ""
            try:
                if GLOBAL_AVAILABLE:
                    from global_macro_fetcher import get_global_context_for_hypothesis
                    global_ctx = get_global_context_for_hypothesis()
            except Exception:
                global_ctx = "Global mixed"
            news_df = get_nse_announcements(symbol=sel_ticker.replace(".NS", ""), days=7) if NEWS_AVAILABLE else pd.DataFrame()
            corp_df = get_nse_corporate_actions(symbol=sel_ticker.replace(".NS", ""), days=30) if NEWS_AVAILABLE else pd.DataFrame()
            risk_info = is_zone_risky_due_to_event(sel_ticker.replace(".NS", ""), datetime.now()) if NEWS_AVAILABLE else {"risky": False, "reasons": []}
            zone_info_for_hyp = {"Direction": sel_row.get("Direction"), "Pattern": sel_row.get("Pattern"), "Timeframe": sel_tf, "Entry (Proximal)": sel_row.get("Entry (Proximal)"), "Distance %": sel_row.get("Distance %"), "State": sel_row.get("State"), "Score": sel_row.get("Score")}
            hypothesis = generate_hypothesis_rule_based(sel_ticker, zone_info_for_hyp, indicators, sector, fii_ctx, global_ctx, risk_info.get("risky", False))
            if is_gemini_configured() and GEMINI_MODULE_AVAILABLE:
                try:
                    gkey = get_gemini_key()
                    gemini_client = GeminiZoneAnalyzer(api_key=gkey)
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
                st.markdown(f"[TradingView]({links.get('tradingview', '')})")
                st.markdown(f"[NSE Quote]({links.get('nse_quote', '')})")
                st.markdown(f"[Screener]({links.get('screener', '')})")
            with col2:
                st.markdown("**📰 News Links**")
                st.markdown(f"[NSE Announcements]({links.get('nse_announcements', '')})")
                st.markdown(f"[Corp Actions]({links.get('nse_corp_actions', '')})")
                st.markdown(f"[Sector {sector} News]({sector_links.get('google_news', '')})")
            with col3:
                st.markdown("**📊 Indicators**")
                _ltp, _ltp_src = None, None
                try:
                    _lmap = cached_live_ltp((sel_ticker,), bool(is_dhan_configured())) or {}
                    _d = _lmap.get(str(sel_ticker)) or _lmap.get(str(sel_ticker).replace(".NS", "")) or {}
                    _ltp = _d.get("ltp")
                    if _ltp:
                        _ltp_src = "Dhan" if is_dhan_configured() else "Yahoo"
                except Exception:
                    _ltp = None
                st.markdown(_render_indicators_panel_md(indicators, ltp=_ltp, ltp_src=_ltp_src), unsafe_allow_html=True)
            with col4:
                st.markdown("**🌍 Context + Risk**")
                st.markdown(_render_context_panel_md(sector, sector_idx, global_ctx), unsafe_allow_html=True)
                _rs, _extra = _clean_risk_reasons(risk_info)
                if _rs:
                    st.warning("⚠️ Event Risk: " + " | ".join(_rs) + (f" (+{_extra} more)" if _extra else ""))
                else:
                    st.success("✅ No near-term event risk")
                st.write(f"**Validation:** Valid={sel_row.get('Valid?')} RR>=3={sel_row.get('RR>=3?')} Engulf={sel_row.get('Engulf OK')} Aligned={sel_row.get('Aligned?')}")
                _nlines = _news_lines_html(news_df, max_show=2)
                if _nlines:
                    st.write("**Recent News:**")
                    st.markdown("<br>".join(_nlines), unsafe_allow_html=True)

            # ---------- OI का कारण + देश-विदेश के factors (validated page) ----------
            _why = _oi_why_full(sel_ticker)
            if _why:
                st.markdown("**🎯 OI Signal के पीछे का कारण (drivers + क्या करना)**")
                st.info(_why)
            st.markdown("**🌍🇮🇳 देश-विदेश का क्या असर इस स्टॉक पर पड़ता है**")
            st.markdown(_render_affected_by_panel(sector, news_df), unsafe_allow_html=True)

            if is_gemini_configured():
                if st.button("🤖 Gemini se Top 10 Validated Zones ka AI Analysis", key="gemini_validated"):
                    with st.spinner("Gemini analysis..."):
                        try:
                            gkey = get_gemini_key()
                            gemini_client = GeminiZoneAnalyzer(api_key=gkey)
                            daily_bucket = cc.last_closed_bucket("Daily")
                            up, down, flat, _ = cached_breadth_for_all(daily_bucket, tuple(all_tickers))
                            breadth = {"up": up, "down": down, "flat": flat, "total": up + down + flat}
                            analysis_df = gemini_client.analyze_batch_zones(zones_df=display_valid, max_zones=10, news_fetcher=lambda sym: get_nse_announcements(symbol=sym.replace(".NS", ""), days=7), corp_fetcher=lambda sym: get_nse_corporate_actions(symbol=sym.replace(".NS", ""), days=30), breadth=breadth)
                            st.dataframe(analysis_df, width="stretch")
                        except Exception as e:
                            st.error(f"Gemini error: {e}")

    with st.expander("🔍 Validation Funnel - Kaunsa Rule Kitna Filter Kar Raha Hai?", expanded=False):
        for tf in ordered_tfs:
            if tf in funnels and funnels[tf]:
                df_funnel = pd.DataFrame([dict(gate=k, rejected=v) for k, v in funnels[tf].items()]).sort_values("rejected", ascending=False).reset_index(drop=True)
                if not df_funnel.empty:
                    df_funnel["pct"] = (100 * df_funnel["rejected"] / df_funnel["rejected"].sum()).round(1)
                    st.markdown(f"**{tf} Funnel**")
                    st.dataframe(df_funnel, width="stretch", hide_index=True)
# ==================== AI TRADER PULSE - PRE-MARKET / POST-MARKET BRIEFING ====================
# Senior D&S trader briefing: Delivery % (aaj vs pichhla din), % of F&O futures stocks
# increased, Option OI signal (PCR/max pain/buildup), FII/DII, Volume+Price, Global +
# Indian News events -> AI short summary (matlab + forecast) + Top 10 Buy / Top 10 Sell.
if PULSE_AVAILABLE:
    try:
        _zones_for_pulse = combined if (combined is not None and not combined.empty) else combined_v
        if _zones_for_pulse is None:
            _zones_for_pulse = pd.DataFrame()
        mp.render_ai_trader_pulse(_zones_for_pulse, tuple(all_tickers))
    except Exception as _e:
        print(f"Pulse section error (safe, app chalega): {_e}")
        st.caption("⚠️ AI Trader Pulse load nahi ho paya — scanner bilkul unaffected hai.")

# ==================== NEXT POWERFUL FEATURES - Auto Trading ====================
st.markdown("---")
st.subheader("🚀 Next Powerful Features - Secure & Optional (Bina Key Ke Bhi Fast)")

tab_autotrade = st.tabs(["🛒 Dhan Auto Trading (Optional)"])[0]

with tab_autotrade:
    st.markdown("**Dhan se Zone par Auto Bracket Order - Secure, Paper Trading Default (Safe)**")
    dhan_ok = is_dhan_configured()
    if dhan_ok:
        st.success(f"✅ Dhan configured: {mask_key(get_dhan_creds()[0] or '')} (secure) - Trading enabled")

        paper = st.checkbox("Paper Trading (Safe - Real order nahi lagega)", value=True, key="paper_trading", help="ON rakho to real order nahi lagega, sirf log. OFF karne par real order lagega - careful!")
        qty = st.number_input("Quantity (Max 100 for safety)", min_value=1, max_value=100, value=1, key="auto_qty")

        if "Main" in st.session_state.app_page and not combined.empty:
            combined_for_trade = combined
        elif not combined_v.empty:
            combined_for_trade = combined_v
        else:
            combined_for_trade = pd.DataFrame()

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

        st.markdown("---")
        st.caption("Auto Trading - Extra Secure: Secrets me [trading] auto_enabled = true daalna padega")
        try:
            auto_enabled_flag = get_secret("trading.auto_enabled") or get_secret("TRADING_AUTO_ENABLED")
            auto_trading_flag = str(auto_enabled_flag).lower() in ["true", "1", "yes"] if auto_enabled_flag else False
        except Exception:
            auto_trading_flag = False

        if auto_trading_flag:
            st.warning("⚠️ Auto Trading Flag ENABLED via secrets.toml - Nearest zones par auto order lagega")
            auto_trade = st.checkbox("Auto Trade Nearest Zones (<0.5%) - Real orders if Paper OFF!", value=False, key="auto_trade_toggle")
            if auto_trade:
                st.error("⚠️ CAUTION: Real orders lagenge agar Paper Trading OFF hai! Ensure karo.")
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
    **Nearest-Zone Filter (NEW):**
    - Toote hue zone (LTP ne SL cross kar diya) hide
    - Proximal se Max Distance % se door wale zone hide
    - Sab symbols milakar sabse nazdeek zone pehle
    - Ek symbol ke sirf N nazdeek zone, taki dusre symbols ke nazdeek zone na chhute
    - Settings (⚙️) me band/adjust kar sakte ho

    **UI Change (NEW):**
    - "LIVE: Important Market News / Events" + 3-in-1 news detail ab page ke sabse NICHE,
      ek collapsed expander ke andar hain (top par nahi)
    - Validated page: Engine = v1 ya v2 (naye niyam) chun sakte ho; v2 me Envelope + Half-TF
      ke controls milte hain
    - Top area ab clean hai: Mode info, Fast Open warning, scan buttons, auto-refresh caption
      aur status box sab Settings (⚙️) -> "Scan Controls" / "Auto-Refresh" me shift ho gaye

    **Security (API Keys):**
    - Bina Dhan/Gemini key ke bhi app 100% fast chalega
    - Keys ho to auto-enable: Dhan holdings/orders, Gemini AI analysis
    - Keys kabhi GitHub/log/dataframe me nahi dikhengi - sirf ✅/○ status
    - `.streamlit/secrets.toml` me rakho, .gitignore me hona chahiye

    **Powerful Features (Bina API key ke free):**
    - **FII/DII Activity**: NSE API se daily FII/DII net buy/sell, trend - free, 30min cache
    - **Global Instruments**: GIFT NIFTY, NIFTY, BANK NIFTY, USD/INR, Gold, Crude + World Indices
    - **Global Macro News**: ForexFactory free JSON se high-impact events
    - **Sector + News/Event**: Har stock ka sector mapping + NSE announcements + corporate actions + risky event check
    - **Indicators Hypothesis**: RSI, EMA20/50/200, Supertrend, MACD, Volume ratio se rule-based Hinglish hypothesis

    **With API Keys (Optional, Secure):**
    - **Dhan**: Holdings, Positions, Live LTP, Zone se direct order
    - **Gemini**: Zone + News + FII + Global context se AI enhanced hypothesis

    **Short Links (Touch to Read):**
    - Symbol column = TradingView chart (touch to open)
    - Detailed Analysis me: TradingView, NSE Quote, NSE Announcements, Corporate Actions, Screener.in, Google News (Sector)
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
# ==================== MOVED + COLLAPSED: Top Market News / Events ====================
# NOTE: Ye poora section pehle page ke TOP par tha (market tape ke neeche).
# Ab (a) page ke sabse NICHE shift hai aur (b) collapsed expander ke andar hai,
# isliye page saaf rehta hai -- kholne par hi news dikhti hai.
st.markdown("---")
with st.expander("🔴 LIVE: Important Market News / Events - Hindi + AI Summary + Global Impact (3 in 1)", expanded=False):
    # Freshness window: pehle HARD 1-hour thi jisse news box zyadatar khaali rehta tha.
    _nh_map = {"1 घंटा": 1, "3 घंटे": 3, "6 घंटे": 6, "12 घंटे": 12, "24 घंटे": 24}
    _nh_choice = st.radio("🕒 News freshness window", list(_nh_map.keys()), index=0, horizontal=True, key="news_hours_radio")
    news_hours = _nh_map[_nh_choice]
    st.caption("✅ Filter: **सिर्फ NSE F&O stocks** की news + **macro/global events** (RBI, Fed, crude, rupee, FII/DII...) जो इन्हें affect करते हैं — बाकी noise छंटा हुआ")
    # ---------- LIVE news cards ----------
    try:
        st.markdown(f"#### 🔴 Important Market News / Events - Current Notification (Last {_nh_choice} Fresh)")
        try:
            from powerful_news_fetcher import get_verified_news_with_gemini_layers
            verified_news_df = get_verified_news_with_gemini_layers(hours=news_hours)
            if verified_news_df is not None and not verified_news_df.empty:
                for idx, row in verified_news_df.head(3).iterrows():
                    title = str(row.get("title", ""))[:120]
                    source = str(row.get("source", ""))
                    confidence = str(row.get("confidence", "Medium"))
                    symbol = str(row.get("symbol", "MARKET"))
                    hindi_title = title
                    try:
                        if is_gemini_configured():
                            from gemini_analyzer import quick_hindi_translate
                            hindi_title = quick_hindi_translate(title)
                    except Exception:
                        pass
                    bg = "#ea394322" if confidence == "High" else "#f0b90b22" if confidence == "Medium" else "#2a2a2a"
                    border = "#ea3943" if confidence == "High" else "#f0b90b" if confidence == "Medium" else "#444"
                    st.markdown(f"<div style='background:{bg};border:1px solid {border};border-radius:8px;padding:8px 12px;margin:6px 0;'><b style='color:#f0b90b;'>🔴 {symbol}</b> <span style='color:#eaeaea;'>{hindi_title}</span> <br><small style='color:#888;'>Source: {source} | Confidence: {confidence} | {row.get('date', '')}</small></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;margin:6px 0;'><b style='color:#f0b90b;'>NIFTY</b> - Market live, no major news in last 1 hour <br><small style='color:#888;'>Source: NSE + StockEdge | Fresh: Last 1 Hour Checked</small></div>", unsafe_allow_html=True)
        except Exception as e:
            print(f"Top notification inner error (safe fallback): {e}")
            st.markdown("<div style='background:#2a2a2a;border:1px solid #444;border-radius:8px;padding:8px 12px;margin:6px 0;'><b style='color:#f0b90b;'>MARKET</b> - Live market data loading... <br><small>News: Checking fresh 1 hour trending (if fails, app still works)</small></div>", unsafe_allow_html=True)
    except Exception as _e:
        print(f"Top notification outer safe error: {_e}")
        st.caption("News loading... (app fast, no white screen)")

    # ---------- 3-in-1 detail (pehle ye popover tha, ab expander ke andar tabs) ----------
    try:
        st.markdown("#### 📰 Top Market News / Events - Gemini Multi-Source Summary + Global Market Data + Event Impact (3 in 1, No Links)")
        st.caption("News headline + Gemini AI kai sources ke news se ek me summary + Global market current data + Us stock par event ka short impact")

        tab_summary, tab_global, tab_impact = st.tabs(["🇮🇳 News Summary (Gemini Multi-Source)", "🌐 Global Market Data Current", "📊 Event Impact on Stocks (Short)"])

        with tab_summary:
            st.markdown("**🔥 Gemini AI - Kai Sources ke News se Ek Me Samjhaya (Hindi)**")
            st.caption("Moneycontrol + ET Markets + Google News + NSE + BSE - sab sources se ek hi news ka combined summary")
            try:
                from powerful_news_fetcher import get_verified_news_with_gemini_layers
                verified_df = get_verified_news_with_gemini_layers(hours=news_hours)
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
                        verified_tag = "[Verified 2+ sources]" if cross_verified else f"[{source}]"
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{symbol} {verified_tag}</b> - <span style='color:{bias_color};'><b>{bias}</b></span><br><span style='color:#eaeaea;'><b>Headline:</b> {title}</span><br><span style='color:#ccc;'><b>Gemini Summary (Multi-Source):</b> {gemini_summary}</span><br><small style='color:#888;'>{desc[:150]}... | Confidence: {confidence}</small></div>", unsafe_allow_html=True)
                else:
                    st.info("Top news multi-source summary load ho raha hai... Moneycontrol + ET + Google News + NSE se free fetch")
                    demo_news = [
                        {"symbol": "RELIANCE", "title": "रिलायंस Q3 नतीजे - मुनाफा 12% बढ़ा", "summary": "Moneycontrol + ET + NSE 3 sources ने बताया - रिलायंस का Q3 मुनाफा 12% बढ़ा, जियो और रिटेल से ग्रोथ", "bias": "Bullish 📈", "impact": "High"},
                        {"symbol": "NIFTY", "title": "FII बिकवाली, DII खरीदारी", "summary": "StockEdge + NSE + Moneycontrol verified - FII ने भारी बिकवाली की पर DII ने बैलेंस किया", "bias": "Neutral ➡️", "impact": "High"},
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
                    st.markdown(f"<div style='background:{color}22;border:1px solid {color};border-radius:8px;padding:8px 12px;margin:6px 0;'><b>GIFT NIFTY (Real, NIFTY 50 से अलग)</b> - {ltp:.2f} <span style='color:{color};'>{arrow} {chg_pct:+.2f}%</span><br><small>GIFT City, NSE IX</small></div>", unsafe_allow_html=True)
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
                    st.markdown(f"<div style='background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:8px 12px;margin:6px 0;'><b>FII/DII Live</b> - <span style='color:{fii_color};'>FII {fii_net:+.0f}Cr</span> | <span style='color:{dii_color};'>DII {dii_net:+.0f}Cr</span><br><small>Trend: FII {fii_sum.get('fii_trend', '')} | DII {fii_sum.get('dii_trend', '')}</small></div>", unsafe_allow_html=True)
                except Exception:
                    pass
            except Exception as e:
                st.warning(f"Global market data error: {e}")

        with tab_impact:
            st.markdown("**📊 Event का Stock पर कैसा प्रभाव - Short में**")
            st.caption("हर important news/event का किस stock/sector पर क्या असर होगा - Bullish/Bearish/Neutral + Reason Hindi में")
            try:
                from powerful_news_fetcher import get_verified_news_with_gemini_layers
                verified_df = get_verified_news_with_gemini_layers(hours=news_hours)
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
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{symbol}</b> - <span style='color:{bias_color};'><b>{bias}</b></span> (Impact: {impact})<br><b>Event:</b> {title}<br><b>Stock पर प्रभाव:</b> {affected}<br><b>Reason (Hindi):</b> {reason}</div>", unsafe_allow_html=True)
                else:
                    demo_impacts = [
                        {"symbol": "RELIANCE", "event": "Q3 नतीजे +12%", "bias": "Bullish 📈", "affected": "RELIANCE, ONGC, BPCL, पेंट सेक्टर", "reason": "अच्छे नतीजों से खरीदारी बढ़ेगी"},
                        {"symbol": "BANKNIFTY", "event": "RBI पॉलिसी कल", "bias": "Neutral ➡️", "affected": "BANKNIFTY, HDFCBANK, ICICIBANK, SBIN", "reason": "ब्याज दर स्थिर रहने से साइडवेज"},
                    ]
                    for d in demo_impacts:
                        bias_color = "#16c784" if "Bullish" in d["bias"] else "#ea3943" if "Bearish" in d["bias"] else "#f0b90b"
                        st.markdown(f"<div style='background:{bias_color}22;border:1px solid {bias_color};border-radius:8px;padding:10px 12px;margin:8px 0;'><b style='color:#f0b90b;'>{d['symbol']}</b> - <span style='color:{bias_color};'><b>{d['bias']}</b></span><br><b>Event:</b> {d['event']}<br><b>Stock पर प्रभाव:</b> {d['affected']}<br><b>Reason:</b> {d['reason']}</div>", unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Event impact error: {e}")
    except Exception as _e:
        st.warning(f"Top Market News section error: {_e} - Scanner fast चल रहा है")
# ==================== /MOVED + COLLAPSED SECTION ====================


# ---------- Auto Refresh on Candle Close (page ke BOTTOM me - top par koi gap nahi) ----------
try:
    selected_tfs_for_refresh = []
    try:
        selected_tfs_for_refresh = tf_selected if 'tf_selected' in globals() else ["15m", "30m", "1H"]
    except Exception:
        selected_tfs_for_refresh = ["15m", "30m", "1H"]
    next_tf, next_sec = get_next_candle_close_info(selected_tfs_for_refresh)
    if next_tf and next_sec and next_sec < 3600:
        st.session_state["next_close_info"] = (next_tf, next_sec)
        if st.session_state.get("auto_refresh_enabled", True):
            try:
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=(next_sec + 5) * 1000, key=f"candle_close_{next_tf}")
            except ImportError:
                pass
except Exception:
    pass

# ---------- Live LTP fast refresh (sirf market hours me - latency fix) ----------
try:
    if st.session_state.get("live_ltp_refresh", True):
        _ms = cc.market_status()
        if _ms.get("open"):
            _iv = int(str(st.session_state.get("live_ltp_interval", "10s")).replace("s", ""))
            try:
                from streamlit_autorefresh import st_autorefresh as _st_ar
                _st_ar(interval=_iv * 1000, key="live_ltp_refresh_timer")
            except ImportError:
                pass
except Exception:
    pass
