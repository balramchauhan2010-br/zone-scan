import pandas as pd
import streamlit as st

import data_fetch
import scanner
import candle_clock as cc
import market_cap as mc
import global_instruments as gi
from fno_universe import get_fno_symbols, to_yahoo_tickers, chart_url

st.set_page_config(page_title="NSE F&O Supply/Demand Zone Scanner", layout="wide", page_icon="📈",
                    initial_sidebar_state="collapsed")

# -----------------------------------------------------------------------------
# Top bar: a small ⚙️ gear icon (top-left) opens ALL scanner settings in a
# popover. No permanent sidebar -> the full page width stays free for the
# results table.
# -----------------------------------------------------------------------------
gear_col, title_col = st.columns([0.06, 0.94])
with title_col:
    st.title("📈 NSE F&O Supply/Demand Zone Scanner")
with gear_col:
    st.write("")
    settings_pop = st.popover("⚙️", help="Scanner Settings")

with settings_pop:
    st.subheader("⚙️ Scanner Settings")

    # ---- NEW: Enable low TFs toggle (Requirement 1) ----
    enable_low_tf = st.checkbox(
        "⚡ Enable Low Timeframes (3m, 5m, 10m)",
        value=False,
        help="3m, 5m, 10m timeframes 1m data se bante hain, isliye thoda slow aur heavy ho sakta hai. "
             "Enable karne par hi ye options dikhenge aur scan honge. Intraday scalping ke liye useful."
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
        help="Preset TFs ke alawa apna khud ka timeframe type karke Enter dabayein - "
             "format '<number>m' (minutes) ya '<number>H' (hours), jaise '5m', '3m', '45m', '3H', '8H'. "
             "Low TF (3m/5m/10m) ke liye upar wala checkbox enable karna padega.",
    )
    tf_selected, invalid_tfs = [], []
    for _raw in (raw_tf_selected or []):
        _norm = scanner.normalize_tf(_raw)
        if _norm:
            if not enable_low_tf and _norm in low_tfs:
                invalid_tfs.append(f"{_raw} (low TF disabled - checkbox enable karo)")
                continue
            tf_selected.append(_norm)
        else:
            invalid_tfs.append(_raw)
    tf_selected = list(dict.fromkeys(tf_selected))
    if invalid_tfs:
        st.warning(f"Samajh nahi aaya / disabled, ignore kiya: {', '.join(invalid_tfs)} "
                    f"(format '5m' / '45m' / '3H' jaisa hona chahiye, low TF ke liye toggle ON karo)")
    if not tf_selected:
        tf_selected = list(available_tfs)
    tf_selected = sorted(tf_selected, key=scanner.tf_minutes)

    st.markdown("---")
    st.subheader("🌍 Universe Type")

    scan_mode = st.radio(
        "Kis universe ko scan karna hai? (ek hi select hoga)",
        ["📊 NSE F&O Universe", "🌍 Top Global Instruments"],
        index=0,
        horizontal=True,
        help="Pehle dono add hote the. Ab aapko ek chunna hai - ya to NSE F&O stocks ya to Global Instruments."
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
            help="Market cap ke hisaab se top-N NSE F&O stocks scan honge. By default All selected hai.",
        )
        _n_selected = total_n if universe_label.startswith("All") else int(universe_label.replace("Top ", ""))
        tickers = list(mc.top_n_tickers(all_tickers, _n_selected))
        st.caption(f"{len(tickers)} tickers selected ({universe_source}) - Mode: NSE F&O")
        tickers = tuple(tickers)

    else:
        st.info("🌍 Global Mode: Sirf selected global instruments scan honge, NSE F&O nahi.")
        global_labels_selected = st.multiselect(
            "🌍 Top Global Instruments (select karo)", 
            gi.labels(), 
            default=gi.labels()[:8] if len(gi.labels()) >= 8 else gi.labels(),
            help="NSE ke bajaye sirf ye global instruments scan honge.",
        )
        global_tickers = [gi.label_to_yahoo(lbl) for lbl in global_labels_selected]
        global_tickers = [t for t in global_tickers if t]
        tickers = tuple(dict.fromkeys(global_tickers))
        if not tickers:
            st.warning("⚠️ Kam se kam 1 global instrument select karo, warna scan empty rahega.")
        st.caption(f"{len(tickers)} global tickers selected (live Yahoo Finance) - Mode: Global")

    st.markdown("---")
    st.subheader("🔍 Filters")
    c1, c2 = st.columns(2)
    state_filter = c1.multiselect("State", ["Fresh", "Tested"], default=["Fresh", "Tested"],
                                   label_visibility="collapsed", placeholder="Zone State")
    direction_filter = c2.selectbox("Direction", ["Both", "Demand only", "Supply only"],
                                     label_visibility="collapsed")
    hq_only = st.checkbox("⭐ HQ zones only (Rule3)", value=False)

    with st.expander("📐 EOD Range Filter", expanded=False):
        eod_advanced = st.checkbox("Advanced: alag High/Low %", value=False)
        if eod_advanced:
            eod_high_pct = st.slider("High Buffer % (+)", 0.0, 50.0, 10.0, 0.5)
            eod_low_pct = st.slider("Low Buffer % (-)", 0.0, 50.0, 10.0, 0.5)
        else:
            eod_pct = st.slider("EOD Buffer % (+High / -Low, dono saath)", 0.0, 50.0, 10.0, 0.5)
            eod_high_pct = eod_pct
            eod_low_pct = eod_pct

    with st.expander("🔧 Rule Toggles & Target", expanded=False):
        target_rr = st.number_input("Target RR (min 1:3)", min_value=3.0, max_value=10.0, value=3.0, step=0.5)
        en_wick = st.checkbox("Rule1: Leg-in closing wick guard", value=True)
        en_cover = st.checkbox("Rule2: Leg-out 90% coverage guard", value=True)
        en_hq = st.checkbox("Rule3: Boring-colour HQ flag", value=True)
        en_white = st.checkbox("Rule4: White-area tag", value=True)

    with st.expander("🗄️ Cache / Refresh", expanded=False):
        force_rescan = st.button("🔄 Force Rescan (bypass cache)", width="stretch")
        st.caption(
            "Scan sirf tab dobara chalta hai jab us timeframe ki candle actually "
            "CLOSE hoti hai (NSE session + holidays aware)."
        )

# -----------------------------------------------------------------------------
# Cached raw data fetchers
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


params = dict(
    targetRR=float(target_rr),
    eodHighBufferPct=float(eod_high_pct),
    eodLowBufferPct=float(eod_low_pct),
    enableClosingWickCheck=bool(en_wick),
    enableLegOutCoverCheck=bool(en_cover),
    enableHQBaseColourCheck=bool(en_hq),
    enableWhiteAreaCheck=bool(en_white),
)
params_tuple = tuple(sorted(params.items()))
states_tuple = tuple(state_filter) if state_filter else ("Fresh", "Tested")

if force_rescan:
    cached_scan.clear()
    cached_fetch_1m.clear()
    cached_fetch_5m.clear()
    cached_fetch_15m.clear()
    cached_fetch_60m.clear()
    cached_fetch_daily.clear()
    cached_market_watch.clear()
    st.toast("Cache cleared - fresh scan chal raha hai...", icon="🔄")

# -----------------------------------------------------------------------------
# Live Market Watch ticker-tape
# -----------------------------------------------------------------------------
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
    if hq_only:
        out = out[out["HQ Zone (Rule3 Boring-Colour)"] == True]  # noqa: E712
    return out


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_nifty_daily(bucket_key):
    raw = data_fetch.fetch_daily(["^NSEI"])
    return raw.get("^NSEI")


# ---- NEW: Breadth calculation for NSE F&O 213 ----
@st.cache_data(show_spinner=False, ttl=300)
def cached_breadth_for_all(bucket_key, tick_tuple):
    """Daily data se up/down breadth nikalta hai - 213 stocks ke liye"""
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


def render_table(df: pd.DataFrame, file_label: str):
    df = apply_display_filters(df)

    badges = []
    if not df.empty:
        badges.append(_badge("Total Zones", str(len(df)), "#8b8b8b"))
        badges.append(_badge("Demand", str(int(df["Direction"].str.contains("DEMAND").sum())), "#16c784"))
        badges.append(_badge("Supply", str(int(df["Direction"].str.contains("SUPPLY").sum())), "#ea3943"))
        badges.append(_badge("HQ (Rule3)", str(int(df["HQ Zone (Rule3 Boring-Colour)"].sum())), "#f0b90b"))

    # ---- NEW Requirement 1: NSE F&O 213 me kitna up/down ----
    # Ye badge usi line me ayega jahan Total/Demand/Supply/HQ hai - screenshot ke pehle circle wali jagah
    if scan_mode == "📊 NSE F&O Universe":
        try:
            # Breadth hamesha All (213) ke liye dikhana hai, chahe user Top 50 select kare
            breadth_tickers = tuple(all_tickers) if 'all_tickers' in globals() and len(all_tickers) > 0 else tickers
            if len(breadth_tickers) > 0:
                daily_bucket = cc.last_closed_bucket("Daily")
                up, down, flat, _details = cached_breadth_for_all(daily_bucket, breadth_tickers)
                total_b = up + down + flat
                if total_b > 0:
                    up_pct = up / total_b * 100
                    down_pct = down / total_b * 100
                    # Color logic: agar up jyada to green border, down jyada to red
                    breadth_color = "#16c784" if up >= down else "#ea3943"
                    breadth_value = (
                        f"<span style='color:#16c784'>▲ Up: {up} ({up_pct:.1f}%)</span> "
                        f"<span style='color:#ea3943'>▼ Down: {down} ({down_pct:.1f}%)</span> "
                        f"<span style='color:#8b8b8b'>- Flat: {flat}</span>"
                    )
                    badges.append(_badge(f"NSE F&O Breadth ({total_b})", breadth_value, breadth_color))
        except Exception as e:
            # Fail silently, breadth optional hai
            pass

    nifty_df = cached_nifty_daily(cc.last_closed_bucket("Daily"))
    nifty_zone = scanner.nearest_zone_for_symbol(nifty_df, params, states=["Fresh", "Tested"])
    if nifty_zone:
        color = "#16c784" if nifty_zone["direction"] == "DEMAND" else "#ea3943"
        nifty_url = f"https://www.tradingview.com/chart/?symbol=NSE%3ANIFTY"
        badges.append(
            f'<a href="{nifty_url}" target="_blank" style="text-decoration:none;">'
            + _badge("📍 NIFTY50 nearest zone (Daily)",
                     f'{nifty_zone["direction"]} @ {nifty_zone["entry"]:,} '
                     f'({nifty_zone["distance_pct"]:+.2f}% away, {nifty_zone["state"]})', color)
            + "</a>"
        )
    if badges:
        st.markdown("".join(badges), unsafe_allow_html=True)

    if df.empty:
        st.info("Is filter ke sath koi live zone nahi mili.")
        return

    st.dataframe(
        df.drop(columns=["Ticker"]),
        width="stretch",
        hide_index=True,
        column_config={
            "Symbol": st.column_config.LinkColumn(
                "Symbol (TradingView Chart)",
                display_text=r"symbol=(?:[^%]+%3A)?([^&]+)",
            ),
            "Timeframe": st.column_config.TextColumn("Timeframe", width="small"),
            "HQ Zone (Rule3 Boring-Colour)": st.column_config.CheckboxColumn("HQ Zone (Rule3)"),
            "White Area OK (Rule4)": st.column_config.CheckboxColumn("White Area OK (Rule4)"),
            "Entry (Proximal)": st.column_config.NumberColumn(format="%.2f"),
            "Stop Loss (Distal+Buffer)": st.column_config.NumberColumn(format="%.2f"),
            "Target (RR set)": st.column_config.NumberColumn(format="%.2f"),
            "Current Price": st.column_config.NumberColumn(format="%.2f"),
            "Distance from Entry": st.column_config.NumberColumn(format="%.2f"),
            "Distance %": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    csv = df.drop(columns=["Ticker"]).to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Download {file_label} zones as CSV", csv, file_name=f"zones_{file_label}.csv",
                        mime="text/csv")


# -----------------------------------------------------------------------------
# Main scan
# -----------------------------------------------------------------------------
if not tickers:
    st.error("❌ Koi ticker select nahi hai. Settings (⚙️) me jaake NSE Universe ya Global Instruments select karo.")
    st.stop()

needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}

with st.status("Data fetch + scan chal raha hai...", expanded=True) as status_box:
    st.write(f"🔹 Mode: {scan_mode} | Tickers: {len(tickers)} | TFs: {', '.join(tf_selected)}")
    for base in BASE_ORDER:
        if base not in needed_bases:
            continue
        st.write(f"⏳ {BASE_LABELS[base]} data fetch ho raha hai...")
        _fetched = BASE_FETCHERS[base](cc.last_closed_bucket(BASE_BUCKET_TF[base]), tickers)
        st.write(f"✅ {BASE_LABELS[base]} data mila: {len(_fetched)} / {len(tickers)} symbols")

    results = {}
    for tf in tf_selected:
        st.write(f"🔎 Scanning {tf} ...")
        bucket = cc.last_closed_bucket(tf)
        results[tf] = cached_scan(tf, bucket, params_tuple, tickers, states_tuple)
    status_box.update(label="✅ Scan complete", state="complete", expanded=False)

# ---- Combine ALL selected timeframes' zones into ONE unified table --------
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

# ---- NEW Requirement 2: Symbol sorting / grouping (bina anya logic change ke) ----
# UPDATED: Distance % (Nearest First) me ab same stock ke saare zones ek saath ayenge
if not combined.empty:
    st.markdown("#### 🔃 Table Sorting / Grouping (Display Only)")
    sort_option = st.radio(
        "Symbol ko kaise dikhana hai?",
        ["Distance % (Default - Nearest First + Same Stock Grouped)", "Symbol A→Z ↑ (Ascending)", "Symbol Z→A ↓ (Descending)", "Symbol Grouped (ek Symbol ke saare TF ek saath, A-Z)"],
        index=0,
        horizontal=True,
        help="Distance % me ab nearest stock pehle, uske saare zones ek saath, phir second nearest stock ke saare zones - aise क्रम me. Baki options sirf display order badlenge, scan logic same rahega."
    )

    # Sorting logic - sirf display ke liye, koi filter/scan logic change nahi
    if sort_option == "Symbol A→Z ↑ (Ascending)":
        combined = combined.sort_values("Ticker", ascending=True)
    elif sort_option == "Symbol Z→A ↓ (Descending)":
        combined = combined.sort_values("Ticker", ascending=False)
    elif "Grouped" in sort_option and "A-Z" in sort_option:
        # Symbol wise group + uske andar TF chhote se bade
        combined["_tf_min"] = combined["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
        combined = combined.sort_values(["Ticker", "_tf_min"], ascending=[True, True])
        combined = combined.drop(columns=["_tf_min"])
    else:
        # NEW LOGIC: Distance % (Nearest First) + Same Stock ke saare zones ek saath
        # Step 1: har row ka abs distance
        # Step 2: har Ticker ka minimum abs distance nikalo (us stock ka nearest zone)
        # Step 3: Ticker ko uske min distance se sort karo, phir same Ticker ke andar distance se sort
        if "Distance %" in combined.columns and "Ticker" in combined.columns:
            combined["_abs_dist"] = combined["Distance %"].abs()
            # Har ticker ka sabse nearest zone ka distance
            ticker_min_dist = combined.groupby("Ticker")["_abs_dist"].min()
            combined["_ticker_min"] = combined["Ticker"].map(ticker_min_dist)
            # TF order bhi andar sorted rakhe taaki same stock me 15m, 30m, 1H क्रम me aaye
            combined["_tf_min"] = combined["Timeframe"].apply(lambda x: scanner.tf_minutes(x))
            combined = combined.sort_values(
                ["_ticker_min", "Ticker", "_abs_dist", "_tf_min"],
                ascending=[True, True, True, True]
            )
            combined = combined.drop(columns=["_abs_dist", "_ticker_min", "_tf_min"])
        elif "Distance %" in combined.columns:
            combined = combined.sort_values("Distance %", key=lambda s: s.abs())

render_table(combined, "all_selected_timeframes" if len(tf_selected) > 1 else tf_selected[0])

st.markdown("---")
with st.expander("ℹ️ Methodology / Limitations"):
    st.markdown("""
- **Data source**: Yahoo Finance.
- **NSE F&O Breadth**: All 213 NSE F&O stocks ka daily close vs previous close se Up/Down count nikala jata hai (0.05% se jyada change ko Up/Down mana jata hai). Ye badge Total Zones ke saath dikhta hai.
- **Symbol Sorting (NEW)**: 
  - **Distance % (Default - Nearest First + Same Stock Grouped)**: Sabse nearest zone wala stock pehle, uske saare TF zones ek saath (15m,30m,1H...), phir second nearest stock ke saare zones, aise क्रम me. Aapke screenshot ke requirement ke hisab se.
  - **Symbol A-Z / Z-A / Grouped A-Z**: Sirf display order hai, scan logic same hai.
- **Low TF (3m/5m/10m)**: 1m data se bante hain, toggle se enable hote hain.
- **Universe Type**: NSE F&O ya Global - exclusive selection.
- **Universe default All**: NSE mode me by default All selected.
    """)
