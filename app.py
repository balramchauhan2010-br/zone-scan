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

    raw_tf_selected = st.multiselect(
        "Timeframes (custom bhi type kar sakte hain - jaise 5m, 3m, 45m, 3H)",
        scanner.TF_LIST, default=scanner.TF_LIST, accept_new_options=True,
        help="Preset TFs ke alawa apna khud ka timeframe type karke Enter dabayein - "
             "format '<number>m' (minutes) ya '<number>H' (hours), jaise '5m', '3m', '45m', '3H', '8H'.",
    )
    tf_selected, invalid_tfs = [], []
    for _raw in (raw_tf_selected or []):
        _norm = scanner.normalize_tf(_raw)
        if _norm:
            tf_selected.append(_norm)
        else:
            invalid_tfs.append(_raw)
    tf_selected = list(dict.fromkeys(tf_selected))
    if invalid_tfs:
        st.warning(f"Samajh nahi aaya, ignore kiya: {', '.join(invalid_tfs)} "
                    f"(format '5m' / '45m' / '3H' jaisa hona chahiye)")
    if not tf_selected:
        tf_selected = list(scanner.TF_LIST)
    tf_selected = sorted(tf_selected, key=scanner.tf_minutes)

    # ---- Universe size: single clean slider instead of tier chips ----
    @st.cache_data(show_spinner=False, ttl=24 * 3600)
    def cached_universe():
        return get_fno_symbols(try_live=True)

    symbols, universe_source = cached_universe()
    all_tickers = to_yahoo_tickers(symbols)
    total_n = len(all_tickers)

    _size_options = sorted({n for n in [25, 50, 75, 100, 150, 200, total_n] if n <= total_n})
    _size_labels = [f"All ({total_n})" if n == total_n else f"Top {n}" for n in _size_options]
    _default_label = "Top 50" if "Top 50" in _size_labels else _size_labels[len(_size_labels) // 2]
    universe_label = st.select_slider(
        "Universe (Market-Cap size)", options=_size_labels, value=_default_label,
        help="Market cap (capital size) ke hisaab se top-N NSE F&O stocks scan honge.",
    )
    _n_selected = total_n if universe_label.startswith("All") else int(universe_label.replace("Top ", ""))
    tickers = list(mc.top_n_tickers(all_tickers, _n_selected))

    global_labels_selected = st.multiselect(
        "🌍 + Top Global Instruments (optional add-on)", gi.labels(), default=[],
        help="NSE F&O stocks ke alawa in global instruments ko bhi scan me add karein "
             "(DXY, USDINR, Gold, Crude, world indices, GIFT/Nifty futures proxy, etc). "
             "Data quality/availability Yahoo Finance par depend karti hai.",
    )
    global_tickers = [gi.label_to_yahoo(lbl) for lbl in global_labels_selected]
    global_tickers = [t for t in global_tickers if t]
    tickers = list(dict.fromkeys(tickers + global_tickers))
    st.caption(f"{len(tickers)} tickers selected ({universe_source}"
               f"{f' + {len(global_tickers)} global' if global_tickers else ''})")
    tickers = tuple(tickers)

    st.markdown("---")
    st.subheader("🔍 Filters")
    c1, c2 = st.columns(2)
    state_filter = c1.multiselect("State", ["Fresh", "Tested"], default=["Fresh", "Tested"],
                                   label_visibility="collapsed", placeholder="Zone State")
    direction_filter = c2.selectbox("Direction", ["Both", "Demand only", "Supply only"],
                                     label_visibility="collapsed")
    hq_only = st.checkbox("⭐ HQ zones only (Rule3)", value=False)

    # ---- Everything else: tucked away, clean & small ----
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
            "CLOSE hoti hai (NSE session + holidays aware) - bade timeframes par load nahi badhta."
        )

# -----------------------------------------------------------------------------
# Cached raw data fetchers - keyed to each dataset's OWN candle-close bucket.
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
# Live Market Watch ticker-tape (replaces the old Universe/Market/TF metrics
# row - small clickable badges: GIFT NIFTY, NIFTY 50, BANK NIFTY, USD/INR,
# XAUUSD, SPOTCRUDE, each with live price + %change).
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


def render_table(df: pd.DataFrame, file_label: str):
    df = apply_display_filters(df)

    # ---- Small tag/badge summary row (instead of big st.metric numbers) ----
    badges = []
    if not df.empty:
        badges.append(_badge("Total Zones", str(len(df)), "#8b8b8b"))
        badges.append(_badge("Demand", str(int(df["Direction"].str.contains("DEMAND").sum())), "#16c784"))
        badges.append(_badge("Supply", str(int(df["Direction"].str.contains("SUPPLY").sum())), "#ea3943"))
        badges.append(_badge("HQ (Rule3)", str(int(df["HQ Zone (Rule3 Boring-Colour)"].sum())), "#f0b90b"))

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
# Main scan - staged status feedback so it never LOOKS frozen, even on a
# slow/blocked network (a common issue on free cloud hosting with Yahoo).
# -----------------------------------------------------------------------------
needed_bases = {scanner.base_dataset_for_tf(tf) for tf in tf_selected}

with st.status("Data fetch + scan chal raha hai...", expanded=True) as status_box:
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
# (every timeframe above IS scanned every time regardless of how many are
# selected - this just changes how the results are DISPLAYED: together in
# one table instead of separate tabs.)
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

render_table(combined, "all_selected_timeframes" if len(tf_selected) > 1 else tf_selected[0])

st.markdown("---")
with st.expander("ℹ️ Methodology / Limitations"):
    st.markdown("""
- **Data source**: Yahoo Finance (`yfinance`, with a Chrome-impersonating `curl_cffi` session and
  fast-fail timeouts to avoid hanging on cloud hosting where Yahoo can throttle requests).
  15m/5m/1m are Yahoo's own native intraday granularities (60-day / 60-day / ~7-day lookback
  limits respectively - a Yahoo limitation, fine for a *live* scanner).
- **Custom timeframes** (e.g. '5m', '3m', '45m', '3H', '8H') are built by grouping native
  1m/5m/15m/60m bars **per trading day starting at 09:15 IST** - the exact same session-aware
  logic used for the built-in 30m/75m/2H/4H/6H presets. Type any `<number>m` or `<number>H`
  value into the Timeframes box and press Enter to add it.
- **Weekly/Monthly** are resampled from Daily bars.
- **Entry = Proximal line**, **Stop Loss = Distal line + ATR buffer**, **Target = Entry +/- Risk x targetRR**
  exactly as computed by `zone_core.py` (rules/logic unchanged - only a pure performance fix was
  applied, verified zone-for-zone identical to the original).
- **All selected timeframes are always scanned together** - results from every selected timeframe
  are shown in ONE combined table (use "View Timeframe(s)" above the table to narrow the display
  without re-scanning). Symbol & Timeframe both encode the correct TradingView interval.
- **Universe size** is a Top-N by market-cap slider (bundled rank snapshot, refreshed offline via
  `build_market_cap_tiers.py`) - plus an optional **Top Global Instruments** add-on (DXY, USDINR,
  Gold, Crude, world indices, GIFT/Nifty futures proxy, etc). GIFT NIFTY uses the regular Nifty 50
  spot index as a proxy since a live GIFT Nifty feed isn't available via Yahoo Finance.
- **Market Watch ticker-tape** (top of page) shows live price + %change for 6 key instruments -
  cached for 3 minutes, independent of the main scan/candle-close cache.
- **NIFTY50 nearest-zone badge**: a lightweight Daily-timeframe zone_core scan on the Nifty 50
  index itself, always shown next to each results summary, highlighting the single zone closest
  to the current price - purely informational, uses the exact same rule toggles/target RR set above.
- **Refresh-on-candle-close**: every timeframe's scan is cached against a session-aware "candle
  bucket" key (NSE holidays included) - switching filters or reloading does **not** re-hit Yahoo
  or re-scan unless that timeframe's own candle has actually closed. Use "Force Rescan" to bypass.
- **F&O universe list**: fetched live from `nseindia.com` when possible, falls back to a bundled
  snapshot automatically when NSE blocks the request (common on cloud IPs).
    """)
