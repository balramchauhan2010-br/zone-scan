import pandas as pd
import streamlit as st
import numpy as np

import data_fetch
import scanner
import candle_clock as cc
import market_cap as mc
import global_instruments as gi
from fno_universe import get_fno_symbols, to_yahoo_tickers, chart_url

# NEW: validation module as second page
import zone_core_validation as zcv

st.set_page_config(page_title="NSE F&O Supply/Demand Zone Scanner", layout="wide", page_icon="📈",
                    initial_sidebar_state="collapsed")

# Session state for page navigation
if "app_page" not in st.session_state:
    st.session_state.app_page = "📈 Main Scanner (zone_core.py)"

# -----------------------------------------------------------------------------
# Top bar
# -----------------------------------------------------------------------------
gear_col, title_col = st.columns([0.06, 0.94])
with title_col:
    # Title changes based on page
    if "Validated" in st.session_state.app_page:
        st.title("✅ Validated Zones - Second Page (zone_core_validation.py)")
    else:
        st.title("📈 NSE F&O Supply/Demand Zone Scanner")
with gear_col:
    st.write("")
    settings_pop = st.popover("⚙️", help="Scanner Settings - Page Navigation + Filters")

with settings_pop:
    st.subheader("🧭 App Navigation (Second Page)")
    app_page = st.radio(
        "Page चुनें - Setting में Touch करके यहाँ से दूसरे पेज पर जा सकते हैं",
        ["📈 Main Scanner (zone_core.py)", "✅ Validated Zones (zone_core_validation.py) - Second Page"],
        index=0 if "Main" in st.session_state.app_page else 1,
        help="Main Scanner = purana zone_core.py se zones. Validated Zones = zone_core_validation.py ke 5 sudhaar (Fresh proximal, 1:3 RR, DBR/RBD engulf, pulse/trend) se filter kiye hue zones. Dono pages same data/tickers use karte hain, bas validation alag hai."
    )
    st.session_state.app_page = app_page
    st.markdown("---")

    st.subheader("⚙️ Scanner Settings (Common for both pages)")

    enable_low_tf = st.checkbox(
        "⚡ Enable Low Timeframes (3m, 5m, 10m)",
        value=False,
        help="3m,5m,10m 1m data se bante hain, thoda heavy. Enable par hi dikhenge."
    )
    low_tfs = getattr(scanner, 'LOW_TF_LIST', ["3m", "5m", "10m"])
    standard_tfs = getattr(scanner, 'STANDARD_TF_LIST', scanner.TF_LIST)
    extended_tfs = getattr(scanner, 'EXTENDED_TF_LIST', low_tfs + standard_tfs)
    available_tfs = extended_tfs if enable_low_tf else standard_tfs

    raw_tf_selected = st.multiselect(
        "Timeframes (custom bhi type kar sakte hain - jaise 5m, 3m, 45m, 3H)",
        available_tfs, 
        default=available_tfs, 
        accept_new_options=True,
        help="Preset ke alawa custom type karke Enter. Low TF ke liye upar checkbox ON karo.",
    )
    tf_selected, invalid_tfs = [], []
    for _raw in (raw_tf_selected or []):
        _norm = scanner.normalize_tf(_raw)
        if _norm:
            if not enable_low_tf and _norm in low_tfs:
                invalid_tfs.append(f"{_raw} (low TF disabled)")
                continue
            tf_selected.append(_norm)
        else:
            invalid_tfs.append(_raw)
    tf_selected = list(dict.fromkeys(tf_selected))
    if invalid_tfs:
        st.warning(f"Ignore kiya: {', '.join(invalid_tfs)}")
    if not tf_selected:
        tf_selected = list(available_tfs)
    tf_selected = sorted(tf_selected, key=scanner.tf_minutes)

    st.markdown("---")
    st.subheader("🌍 Universe Type")

    scan_mode = st.radio(
        "Kis universe ko scan karna hai?",
        ["📊 NSE F&O Universe", "🌍 Top Global Instruments"],
        index=0,
        horizontal=True,
    )

    @st.cache_data(show_spinner=False, ttl=24 * 3600)
    def cached_universe():
        return get_fno_symbols(try_live=True)

    symbols, universe_source = cached_universe()
    all_tickers = to_yahoo_tickers(symbols)
    total_n = len(all_tickers)

    tickers = ()
    universe_label = None
    global_labels_selected = []

    if scan_mode == "📊 NSE F&O Universe":
        _size_options = sorted({n for n in [25, 50, 75, 100, 150, 200, total_n] if n <= total_n})
        _size_labels = [f"All ({total_n})" if n == total_n else f"Top {n}" for n in _size_options]
        _default_label = f"All ({total_n})" if f"All ({total_n})" in _size_labels else _size_labels[-1]
        universe_label = st.select_slider(
            "Universe (Market-Cap size)", options=_size_labels, value=_default_label,
        )
        _n_selected = total_n if universe_label.startswith("All") else int(universe_label.replace("Top ", ""))
        tickers = list(mc.top_n_tickers(all_tickers, _n_selected))
        st.caption(f"{len(tickers)} tickers selected ({universe_source}) - Mode: NSE F&O")
        tickers = tuple(tickers)
    else:
        st.info("🌍 Global Mode: Sirf selected global instruments scan honge.")
        global_labels_selected = st.multiselect(
            "🌍 Top Global Instruments", 
            gi.labels(), 
            default=gi.labels()[:8] if len(gi.labels()) >= 8 else gi.labels(),
        )
        global_tickers = [gi.label_to_yahoo(lbl) for lbl in global_labels_selected]
        global_tickers = [t for t in global_tickers if t]
        tickers = tuple(dict.fromkeys(global_tickers))
        if not tickers:
            st.warning("⚠️ Kam se kam 1 global instrument select karo.")
        st.caption(f"{len(tickers)} global tickers selected - Mode: Global")

    st.markdown("---")
    st.subheader("🔍 Filters (Common)")
    c1, c2 = st.columns(2)
    state_filter = c1.multiselect("State", ["Fresh", "Tested"], default=["Fresh", "Tested"],
                                   label_visibility="collapsed", placeholder="Zone State")
    direction_filter = c2.selectbox("Direction", ["Both", "Demand only", "Supply only"],
                                     label_visibility="collapsed")
    hq_only = st.checkbox("⭐ HQ zones only (Rule3)", value=False)

    # ---- Main Scanner specific ----
    with st.expander("📐 EOD Range Filter", expanded=False):
        eod_advanced = st.checkbox("Advanced: alag High/Low %", value=False, key="eod_adv")
        if eod_advanced:
            eod_high_pct = st.slider("High Buffer % (+)", 0.0, 50.0, 10.0, 0.5, key="eod_h")
            eod_low_pct = st.slider("Low Buffer % (-)", 0.0, 50.0, 10.0, 0.5, key="eod_l")
        else:
            eod_pct = st.slider("EOD Buffer % (+High / -Low)", 0.0, 50.0, 10.0, 0.5, key="eod_both")
            eod_high_pct = eod_pct
            eod_low_pct = eod_pct

    with st.expander("🔧 Rule Toggles & Target (Main Scanner)", expanded=False):
        target_rr = st.number_input("Target RR (min 1:3)", min_value=3.0, max_value=10.0, value=3.0, step=0.5, key="rr_main")
        en_wick = st.checkbox("Rule1: Leg-in closing wick guard", value=True, key="wick_main")
        en_cover = st.checkbox("Rule2: Leg-out 90% coverage guard", value=True, key="cover_main")
        en_hq = st.checkbox("Rule3: Boring-colour HQ flag", value=True, key="hq_main")
        en_white = st.checkbox("Rule4: White-area tag", value=True, key="white_main")

    # ---- Validated Page specific filters ----
    st.markdown("---")
    st.subheader("✅ Validated Page Filters (Second Page ke liye)")
    with st.expander("✅ Validation Rules - zone_core_validation.py", expanded=True):
        st.caption("Ye rules sirf Second Page (Validated Zones) par lagenge. Main Scanner ke zones ko hi validate karke filter kiya jayega.")
        preset_choice = st.selectbox(
            "Validation Preset",
            ["spec_strict (aapki spec jaise)", "max_zones (sabse zyada zones)", "better_wr (better win-rate)", "high_accuracy (sabse tez filter)", "custom"],
            index=0,
            help="Preset = PINE_DEFAULTS + validation tightness. custom me aap khud tick kar sakte hain."
        )
        # Default values from PINE_DEFAULTS
        v_use_rr_filter = st.checkbox("Use LegOut RR Filter (1:3 se kam wale reject) - Rule 2", value=False, help="Agar ON hai to leg-out candle ne khud 1:3 nahi diya to zone reject. OFF par sirf flag lagta hai, reject nahi.")
        v_min_rr = st.slider("Min LegOut RR (Rule 2)", 1.0, 5.0, 3.0, 0.5)
        v_require_engulf = st.checkbox("Require Engulf for Reversal DBR/RBD - Rule 3/4", value=True, help="DBR ko upar DBD zone ka engulf, RBD ko neeche RBR zone ka engulf chahiye.")
        v_engulf_mode = st.selectbox("Engulf Mode", ["distal_close", "distal_wick", "proximal_close", "proximal_wick"], index=0)
        v_engulf_pos = st.selectbox("Engulf Ref Position", ["high", "low", "base"], index=0)
        v_use_pulse_trend = st.checkbox("Use Pulse/Trend (Rule 7)", value=True)
        v_require_aligned = st.checkbox("Require Pulse+Trend Aligned (sirf aligned zones)", value=False, help="ON karne par sirf wahi zones jahan Demand par pulse=+1 & trend=+1, Supply par pulse=-1 & trend=-1")
        v_fresh_prox = st.checkbox("Fresh Uses Proximal (Rule 1 - sahi definition)", value=True, disabled=True, help="Hamesha ON - proximal touch hi Tested banata hai, legOutMidLevel bug fix.")

        st.markdown("**Display Filters (Validated Table ke liye)**")
        v_show_only_fresh = st.checkbox("Show only Fresh (untouched proximal)", value=False)
        v_show_only_tradable = st.checkbox("Show only Tradable (valid + RR>=3 + entry)", value=False, help="Sirf wahi zones jahan entry leni chahiye - Rule 5 + RR")
        v_show_only_valid = st.checkbox("Show only Valid Demand/Supply (Rule 5 final)", value=True, help="RBR&Rule1 / DBR&Rule3 / DBD&Rule2 / RBD&Rule4 pass wale hi")
        v_show_only_aligned_display = st.checkbox("Display me sirf Aligned dikhao", value=False)

    with st.expander("🗄️ Cache / Refresh", expanded=False):
        force_rescan = st.button("🔄 Force Rescan (bypass cache)", width="stretch")
        st.caption("Scan tabhi dobara chalta hai jab candle close hoti hai (NSE session aware).")

# -----------------------------------------------------------------------------
# Cached fetchers
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_1m(bucket_key, tick_tuple):
    return data_fetch.fetch_1m(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_5m(bucket_key, tick_tuple):
    return data_fetch.fetch_5m(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_15m(bucket_key, tick_tuple):
    return data_fetch.fetch_15m(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_60m(bucket_key, tick_tuple):
    return data_fetch.fetch_60m(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_daily(bucket_key, tick_tuple):
    return data_fetch.fetch_daily(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=180)
def cached_market_watch():
    return data_fetch.fetch_market_watch_quotes([item["yahoo"] for item in gi.MARKET_WATCH])

BASE_ORDER = ["1m", "5m", "15m", "60m", "daily"]
BASE_LABELS = {"1m": "1m", "5m": "5m", "15m": "15m", "60m": "1H (60m)", "daily": "Daily"}
BASE_BUCKET_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "60m": "1H", "daily": "Daily"}
BASE_FETCHERS = {
    "1m": cached_fetch_1m, "5m": cached_fetch_5m, "15m": cached_fetch_15m,
    "60m": cached_fetch_60m, "daily": cached_fetch_daily,
}

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_scan(tf, bucket_key, params_tuple, tick_tuple, states_tuple):
    params = dict(params_tuple)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tick_tuple)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    return scanner.scan_universe(tf, frames, params, states=list(states_tuple))

# ---- Validated scan ----
def scan_validated_universe(tf: str, frames: dict, params: dict, states=None):
    """zone_core_validation.py se scan - same frames par, extra validation fields ke saath"""
    states = states or ["Fresh", "Tested"]
    rows = []
    funnel_agg = {}
    for symbol, df in frames.items():
        if df is None or len(df) < 25:
            continue
        try:
            engine = zcv.ZoneEngine(df, **params)
            zones = engine.run()
            # aggregate gate counts for funnel
            for k, v in engine.gate_counts.items():
                funnel_agg[k] = funnel_agg.get(k, 0) + v

            # Pulse/Trend tagging - agar enabled hai to same df se tag karo (higher TF ke liye daily use karna better hota, par yahan simple)
            if params.get("usePulseTrend", True):
                try:
                    rules = zcv.resolve_rules(tf)
                    # For pulse/trend we need higher TF frames - we try to use same df as fallback
                    # Real higher TF resampling needs daily/hourly base, but for now same df se kaam chalega
                    # If we have daily data available for this symbol, use it for higher TF
                    zcv.apply_pulse_trend(zones, df, df, rules["pulse"], rules["trend"], rules["pulse_tf"], rules["trend_tf"])
                except Exception:
                    pass

            active = [z for z in zones if z.state in states]
            if not active:
                continue
            current_price = float(df["close"].iloc[-1])
            last_bar_time = df.index[-1]
            for z in active:
                distance = current_price - z.proxVal
                distance_pct = (distance / current_price * 100.0) if current_price else float("nan")
                risk = abs(z.proxVal - z.slVal)
                reward = abs(z.tpVal - z.proxVal)
                rr = reward / risk if risk else float("nan")
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
                    "Current Price": round(current_price, 2),
                    "Distance %": round(distance_pct, 2),
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
                    "Last Bar Time": last_bar_time,
                })
        except Exception:
            continue
    cols = ["Symbol","Timeframe","Ticker","Direction","Pattern","State","Fresh?","Entry (Proximal)","Stop Loss (Distal+Buffer)","Target (RR set)","Risk:Reward","Current Price","Distance %","LegOut RR","RR>=3?","Engulf OK","Valid?","Rule1(RBR)","Rule2(DBD)","Rule3(DBR)","Rule4(RBD)","Pulse","Trend","Aligned?","Pulse Rule","Trend Rule","HQ Zone","Score","Touch Count","Zone Created","Last Bar Time"]
    if not rows:
        return pd.DataFrame(columns=cols), funnel_agg
    out = pd.DataFrame(rows)[cols]
    out = out.sort_values("Distance %", key=lambda s: s.abs())
    return out.reset_index(drop=True), funnel_agg

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_validated_scan(tf, bucket_key, params_tuple, tick_tuple, states_tuple):
    params = dict(params_tuple)
    base = scanner.base_dataset_for_tf(tf)
    raw_by_base = {base: BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tick_tuple)}
    frames = scanner.build_timeframe_frames(tf, raw_by_base)
    df, funnel = scan_validated_universe(tf, frames, params, states=list(states_tuple))
    return df, funnel

# Common params
params_main = dict(
    targetRR=float(target_rr),
    eodHighBufferPct=float(eod_high_pct),
    eodLowBufferPct=float(eod_low_pct),
    enableClosingWickCheck=bool(en_wick),
    enableLegOutCoverCheck=bool(en_cover),
    enableHQBaseColourCheck=bool(en_hq),
    enableWhiteAreaCheck=bool(en_white),
)
params_main_tuple = tuple(sorted(params_main.items()))
states_tuple = tuple(state_filter) if state_filter else ("Fresh", "Tested")

# Validated params - preset handling
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

# Merge common EOD + validation UI
params_valid = dict(
    targetRR=float(target_rr),
    eodHighBufferPct=float(eod_high_pct),
    eodLowBufferPct=float(eod_low_pct),
    enableClosingWickCheck=bool(en_wick),
    enableLegOutCoverCheck=bool(en_cover),
    enableHQBaseColourCheck=bool(en_hq),
    enableWhiteAreaCheck=bool(en_white),
    # validation specific
    minLegOutRR=float(v_min_rr),
    useLegOutRRFilter=bool(v_use_rr_filter),
    requireEngulfForReversal=bool(v_require_engulf),
    engulfMode=str(v_engulf_mode),
    engulfRefPosition=str(v_engulf_pos),
    usePulseTrend=bool(v_use_pulse_trend),
    requirePulseTrendAligned=bool(v_require_aligned),
    freshUsesProximal=True,
    trackFromNextBar=True,
)
# preset overrides UI if not custom
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
    st.toast("Cache cleared - fresh scan chal raha hai...", icon="🔄")

def _badge(label: str, value: str, color: str) -> str:
    return (f'<span style="background:{color}22;border:1px solid {color};border-radius:6px;'
            f'padding:4px 10px;margin:3px;display:inline-block;font-size:13px;color:#eaeaea;'
            f'white-space:nowrap;"><b>{label}</b> {value}</span>')

def render_market_watch():
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
    st.markdown("".join(chips), unsafe_allow_html=True)

render_market_watch()
st.markdown("---")

def apply_display_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if direction_filter == "Demand only":
        out = out[out["Direction"].str.contains("DEMAND")]
    elif direction_filter == "Supply only":
        out = out[out["Direction"].str.contains("SUPPLY")]
    if hq_only and "HQ Zone (Rule3 Boring-Colour)" in out.columns:
        out = out[out["HQ Zone (Rule3 Boring-Colour)"] == True]
    elif hq_only and "HQ Zone" in out.columns:
        out = out[out["HQ Zone"] == True]
    return out

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_nifty_daily(bucket_key):
    raw = data_fetch.fetch_daily(["^NSEI"])
    return raw.get("^NSEI")

@st.cache_data(show_spinner=False, ttl=300)
def cached_breadth_for_all(bucket_key, tick_tuple):
    try:
        raw = data_fetch.fetch_daily(list(tick_tuple))
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
            chg_pct = (curr - prev) / prev * 100.0
            details.append((sym, chg_pct))
            if chg_pct > 0.05:
                up += 1
            elif chg_pct < -0.05:
                down += 1
            else:
                flat += 1
        except Exception:
            continue
    return up, down, flat, details

def render_table_main(df: pd.DataFrame, file_label: str):
    df = apply_display_filters(df)
    badges = []
    if not df.empty:
        badges.append(_badge("Total Zones", str(len(df)), "#8b8b8b"))
        badges.append(_badge("Demand", str(int(df["Direction"].str.contains("DEMAND").sum())), "#16c784"))
        badges.append(_badge("Supply", str(int(df["Direction"].str.contains("SUPPLY").sum())), "#ea3943"))
        badges.append(_badge("HQ (Rule3)", str(int(df["HQ Zone (Rule3 Boring-Colour)"].sum())) if "HQ Zone (Rule3 Boring-Colour)" in df.columns else "0", "#f0b90b"))
    if scan_mode == "📊 NSE F&O Universe":
        try:
            breadth_tickers = tuple(all_tickers) if 'all_tickers' in globals() and len(all_tickers) > 0 else tickers
            if len(breadth_tickers) > 0:
                daily_bucket = cc.last_closed_bucket("Daily")
                up, down, flat, _details = cached_breadth_for_all(daily_bucket, breadth_tickers)
                total_b = up + down + flat
                if total_b > 0:
                    up_pct = up / total_b * 100
                    down_pct = down / total_b * 100
                    breadth_color = "#16c784" if up >= down else "#ea3943"
                    breadth_value = (f"<span style='color:#16c784'>▲ Up: {up} ({up_pct:.1f}%)</span> <span style='color:#ea3943'>▼ Down: {down} ({down_pct:.1f}%)</span> <span style='color:#8b8b8b'>- Flat: {flat}</span>")
                    badges.append(_badge(f"NSE F&O Breadth ({total_b})", breadth_value, breadth_color))
        except Exception:
            pass
    nifty_df = cached_nifty_daily(cc.last_closed_bucket("Daily"))
    nifty_zone = scanner.nearest_zone_for_symbol(nifty_df, params_main, states=["Fresh", "Tested"])
    if nifty_zone:
        color = "#16c784" if nifty_zone["direction"] == "DEMAND" else "#ea3943"
        nifty_url = f"https://www.tradingview.com/chart/?symbol=NSE%3ANIFTY"
        badges.append(f'<a href="{nifty_url}" target="_blank" style="text-decoration:none;">' + _badge("📍 NIFTY50 nearest zone (Daily)", f'{nifty_zone["direction"]} @ {nifty_zone["entry"]:,} ({nifty_zone["distance_pct"]:+.2f}% away, {nifty_zone["state"]})', color) + "</a>")
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)
    if df.empty:
        st.info("Is filter ke sath koi live zone nahi mili.")
        return
    st.dataframe(df.drop(columns=["Ticker"]), width="stretch", hide_index=True, column_config={"Symbol": st.column_config.LinkColumn("Symbol (TradingView Chart)", display_text=r"symbol=(?:[^%]+%3A)?([^&]+)"), "Timeframe": st.column_config.TextColumn("Timeframe", width="small"), "HQ Zone (Rule3 Boring-Colour)": st.column_config.CheckboxColumn("HQ Zone (Rule3)"), "White Area OK (Rule4)": st.column_config.CheckboxColumn("White Area OK (Rule4)"), "Entry (Proximal)": st.column_config.NumberColumn(format="%.2f"), "Stop Loss (Distal+Buffer)": st.column_config.NumberColumn(format="%.2f"), "Target (RR set)": st.column_config.NumberColumn(format="%.2f"), "Current Price": st.column_config.NumberColumn(format="%.2f"), "Distance from Entry": st.column_config.NumberColumn(format="%.2f"), "Distance %": st.column_config.NumberColumn(format="%.2f%%"),})
    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Download {file_label} zones as CSV", csv, file_name=f"zones_{file_label}.csv", mime="text/csv")

def render_table_validated(df: pd.DataFrame, file_label: str):
    # Apply common filters + validated specific
    df = apply_display_filters(df)
    if v_show_only_valid and "Valid?" in df.columns:
        df = df[df["Valid?"] == True]
    if v_show_only_fresh and "Fresh?" in df.columns:
        df = df[df["Fresh?"] == True]
    if v_show_only_tradable:
        # Tradable = valid + RR>=3 + (Fresh or entry exists)
        if "Valid?" in df.columns and "RR>=3?" in df.columns:
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
    # Breadth same as main
    if scan_mode == "📊 NSE F&O Universe":
        try:
            breadth_tickers = tuple(all_tickers) if 'all_tickers' in globals() and len(all_tickers) > 0 else tickers
            if len(breadth_tickers) > 0:
                daily_bucket = cc.last_closed_bucket("Daily")
                up, down, flat, _details = cached_breadth_for_all(daily_bucket, breadth_tickers)
                total_b = up + down + flat
                if total_b > 0:
                    up_pct = up / total_b * 100
                    down_pct = down / total_b * 100
                    breadth_color = "#16c784" if up >= down else "#ea3943"
                    breadth_value = (f"<span style='color:#16c784'>▲ Up: {up} ({up_pct:.1f}%)</span> <span style='color:#ea3943'>▼ Down: {down} ({down_pct:.1f}%)</span> <span style='color:#8b8b8b'>- Flat: {flat}</span>")
                    badges.append(_badge(f"NSE F&O Breadth ({total_b})", breadth_value, breadth_color))
        except Exception:
            pass
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)
    if df.empty:
        st.info("Validated filters ke sath koi zone nahi mili. Filters kam karo ya Preset 'max_zones' try karo.")
        return
    # Show dataframe with extra validation columns
    st.dataframe(
        df.drop(columns=["Ticker"]),
        width="stretch",
        hide_index=True,
        column_config={
            "Symbol": st.column_config.LinkColumn("Symbol (TradingView Chart)", display_text=r"symbol=(?:[^%]+%3A)?([^&]+)"),
            "Timeframe": st.column_config.TextColumn("Timeframe", width="small"),
            "Fresh?": st.column_config.CheckboxColumn("Fresh?"),
            "RR>=3?": st.column_config.CheckboxColumn("RR>=3?"),
            "Engulf OK": st.column_config.CheckboxColumn("Engulf OK"),
            "Valid?": st.column_config.CheckboxColumn("Valid?"),
            "Aligned?": st.column_config.CheckboxColumn("Aligned?"),
            "HQ Zone": st.column_config.CheckboxColumn("HQ"),
            "Entry (Proximal)": st.column_config.NumberColumn(format="%.2f"),
            "Stop Loss (Distal+Buffer)": st.column_config.NumberColumn(format="%.2f"),
            "Target (RR set)": st.column_config.NumberColumn(format="%.2f"),
            "Current Price": st.column_config.NumberColumn(format="%.2f"),
            "Distance %": st.column_config.NumberColumn(format="%.2f%%"),
            "LegOut RR": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Download {file_label} VALIDATED zones as CSV", csv, file_name=f"validated_zones_{file_label}.csv", mime="text/csv")

# -----------------------------------------------------------------------------
# Main logic branching based on page
# -----------------------------------------------------------------------------
if not tickers:
    st.error("❌ Koi ticker select nahi hai. Settings (⚙️) me jaake NSE Universe ya Global Instruments select karo.")
    st.stop()

needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}

# Common status box for data fetch
if "Main" in st.session_state.app_page:
    # ==================== MAIN SCANNER PAGE ====================
    with st.status("Data fetch + scan chal raha hai (Main Scanner)...", expanded=True) as status_box:
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
            results[tf] = cached_scan(tf, bucket, params_main_tuple, tickers, states_tuple)
        status_box.update(label="✅ Main Scan complete", state="complete", expanded=False)

    ordered_tfs = sorted(tf_selected, key=scanner.tf_minutes)
    non_empty = [results[tf] for tf in ordered_tfs if not results[tf].empty]
    combined = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()

    if len(tf_selected) > 1 and not combined.empty:
        view_tfs = st.multiselect(
            "View Timeframe(s) in table below (scan already covers all selected above)",
            ordered_tfs, default=ordered_tfs,
        )
        if view_tfs:
            combined = combined[combined["Timeframe"].isin(view_tfs)]

    if not combined.empty:
        st.markdown("#### 🔃 Table Sorting / Grouping (Display Only)")
        sort_option = st.radio(
            "Symbol ko kaise dikhana hai?",
            ["Distance % (Default - Nearest First + Same Stock Grouped)", "Symbol A→Z ↑ (Ascending)", "Symbol Z→A ↓ (Descending)", "Symbol Grouped (ek Symbol ke saare TF ek saath, A-Z)"],
            index=0,
            horizontal=True,
        )
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

    render_table_main(combined, "all_selected_timeframes" if len(tf_selected) > 1 else tf_selected[0])

else:
    # ==================== VALIDATED ZONES SECOND PAGE ====================
    st.markdown(f"**Validation Preset:** `{preset_choice}` | **Params:** RR>={v_min_rr}, RR Filter={v_use_rr_filter}, Engulf={v_require_engulf}, PulseTrend={v_use_pulse_trend}, Aligned Required={v_require_aligned}")

    with st.status("Data fetch + VALIDATED scan chal raha hai (Second Page)...", expanded=True) as status_box:
        st.write(f"🔹 Mode: {scan_mode} | Tickers: {len(tickers)} | TFs: {', '.join(tf_selected)} | Page: Validated")
        for base in BASE_ORDER:
            if base not in needed_bases:
                continue
            st.write(f"⏳ {BASE_LABELS[base]} data fetch ho raha hai...")
            _fetched = BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tickers)
            st.write(f"✅ {BASE_LABELS[base]} data mila: {len(_fetched)} / {len(tickers)} symbols")
        results_valid = {}
        funnels = {}
        for tf in tf_selected:
            st.write(f"🔎 Validated Scanning {tf} (zone_core_validation.py)...")
            bucket = cc.last_closed_bucket(tf)
            df_tf, funnel = cached_validated_scan(tf, bucket, params_valid_tuple, tickers, states_tuple)
            results_valid[tf] = df_tf
            funnels[tf] = funnel
        status_box.update(label="✅ Validated Scan complete", state="complete", expanded=False)

    ordered_tfs = sorted(tf_selected, key=scanner.tf_minutes)
    non_empty_v = [results_valid[tf] for tf in ordered_tfs if tf in results_valid and not results_valid[tf].empty]
    combined_v = pd.concat(non_empty_v, ignore_index=True) if non_empty_v else pd.DataFrame()

    if len(tf_selected) > 1 and not combined_v.empty:
        view_tfs_v = st.multiselect(
            "View Timeframe(s) in validated table below",
            ordered_tfs, default=ordered_tfs,
            key="view_tf_validated"
        )
        if view_tfs_v:
            combined_v = combined_v[combined_v["Timeframe"].isin(view_tfs_v)]

    # Sorting for validated - same logic as main but with new grouping
    if not combined_v.empty:
        st.markdown("#### 🔃 Validated Table Sorting / Grouping")
        sort_option_v = st.radio(
            "Validated zones ko kaise dikhana hai?",
            ["Distance % (Nearest First + Same Stock Grouped)", "Symbol A→Z ↑", "Symbol Z→A ↓", "Symbol Grouped (A-Z)"],
            index=0,
            horizontal=True,
            key="sort_validated"
        )
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

    render_table_validated(combined_v, "all_validated" if len(tf_selected) > 1 else (tf_selected[0] if tf_selected else "validated"))

    # Show funnel / gate counts for debugging - kaunsa rule kitna filter kar raha hai
    with st.expander("🔍 Validation Funnel - Kaunsa Rule Kitna Filter Kar Raha Hai? (Debug)", expanded=False):
        st.caption("Har TF ke liye kaunsa gate kitne zones ko reject karta hai - isse pata chalega ki aapka filter kitna strict hai.")
        for tf in ordered_tfs:
            if tf in funnels and funnels[tf]:
                df_funnel = pd.DataFrame([dict(gate=k, rejected=v) for k,v in funnels[tf].items()]).sort_values("rejected", ascending=False).reset_index(drop=True)
                if not df_funnel.empty:
                    df_funnel["pct"] = (100 * df_funnel["rejected"] / df_funnel["rejected"].sum()).round(1)
                    st.markdown(f"**{tf} Funnel**")
                    st.dataframe(df_funnel, width="stretch", hide_index=True)

    with st.expander("ℹ️ Validation Rules Explained (Second Page)", expanded=False):
        st.markdown("""
        **Second Page = zone_core_validation.py ke 7 sudhaar:**

        1. **Fresh Zone = Proximal Line untouched**: Pehle legOutMidLevel use hota tha jiski wajah se har zone creation bar par hi Tested ban jata tha. Ab proximal line (proxVal) touch par hi Tested, creation bar ke baad se tracking shuru.

        2. **LegOut 1:3 RR Gate**: Zone banane wali single leg-out candle ne khud >=1:3 reward diya ho (legOutHigh-prox)/risk >=3 demand, (prox-legOutLow)/risk >=3 supply. `useLegOutRRFilter` ON par reject, OFF par sirf flag.

        3. **Rule-3 DBR Reversal Demand**: DBR (bearish leg-in, bullish leg-out) tabhi valid jab leg-in ke upar pehle se DBD supply zone bana ho aur leg-out close us DBD ke distal se upar band ho = engulf.

        4. **Rule-4 RBD Reversal Supply**: RBD (bullish leg-in, bearish leg-out) tabhi valid jab leg-in ke neeche pehle se RBR demand zone bana ho aur leg-out close us RBR ke distal se neeche band ho.

        5. **Final Decision**: Demand valid = (RBR & Rule1) or (DBR & Rule3), Supply valid = (DBD & Rule2) or (RBD & Rule4)

        6. **Swing Range**: Swing candle ki min range = swingRangeAtrMult x ATR (default 0.05)

        7. **Pulse + Trend**: Har zone par higher TF bias (EMA_SLOPE/MACD_HIST/SMA200/EMA_STACK/SUPERTREND/EMA20_50) aur middle TF direction (ST_20_4/ST_10_3/ST_7_2/DONCHIAN/EMA_TRIPLE/DI_CROSS) ka tag. Aligned tab jab demand par pulse=+1 & trend=+1, supply par -1 & -1. Higher-TF value sirf completed bar se aati hai (no look-ahead).

        **Presets:**
        - `spec_strict`: Aapki spec jaise, strict engulf + 1:3 flag
        - `max_zones`: Sabse zyada zones - loose base, engulf OFF, RR sirf flag - 1H: 1760 zones
        - `better_wr`: Better win-rate - pulse/trend alignment ON
        - `high_accuracy`: Sabse tez filter - sab ON + RR reject - 1H: 101 zones / 80% WR
        """)

st.markdown("---")
with st.expander("ℹ️ Methodology / Limitations (Main Scanner)", expanded=False):
    st.markdown("""
    - **Main Scanner**: zone_core.py - Pine parity scanner, proximal/distal, EOD filter, scoring.
    - **Validated Second Page**: zone_core_validation.py - upar ke 7 rules se filter kiye hue zones, same data par.
    - **NSE F&O Breadth**: All 213 ka daily close vs prev close.
    - **Sorting**: Distance % Nearest First + Same Stock Grouped - nearest stock ke saare TF ek saath.
    - **Navigation**: Settings (⚙️) me jaake Page radio se Main / Validated me switch kar sakte hain.
    """)
