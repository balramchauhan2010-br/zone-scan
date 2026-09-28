import pandas as pd
import streamlit as st

import data_fetch
import scanner
import candle_clock as cc
import market_cap as mc
from fno_universe import get_fno_symbols, to_yahoo_tickers

st.set_page_config(page_title="NSE F&O Supply/Demand Zone Scanner", layout="wide", page_icon="📈")

# -----------------------------------------------------------------------------
# Sidebar - CLEAN layout: only the most-used controls are visible up top,
# everything else lives inside collapsed expanders.
# -----------------------------------------------------------------------------
st.sidebar.title("⚙️ Scanner Settings")

tf_selected = st.sidebar.multiselect(
    "Timeframes", scanner.TF_LIST, default=scanner.TF_LIST,
    help="Sabhi timeframes default me selected hain - jitne kam chunenge utna fast scan hoga.",
)
if not tf_selected:
    tf_selected = scanner.TF_LIST

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
universe_label = st.sidebar.select_slider(
    "Universe (Market-Cap size)", options=_size_labels, value=_default_label,
    help="Market cap (capital size) ke hisaab se top-N stocks scan honge - chhota N = fast scan.",
)
_n_selected = total_n if universe_label.startswith("All") else int(universe_label.replace("Top ", ""))
tickers = tuple(mc.top_n_tickers(all_tickers, _n_selected))

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Filters")
c1, c2 = st.sidebar.columns(2)
state_filter = c1.multiselect("State", ["Fresh", "Tested"], default=["Fresh", "Tested"], label_visibility="collapsed",
                               placeholder="Zone State")
direction_filter = c2.selectbox("Direction", ["Both", "Demand only", "Supply only"], label_visibility="collapsed")
hq_only = st.sidebar.checkbox("⭐ HQ zones only (Rule3)", value=False)

# ---- Everything else: tucked away, clean & small ----
with st.sidebar.expander("📐 EOD Range Filter", expanded=False):
    eod_advanced = st.checkbox("Advanced: alag High/Low %", value=False)
    if eod_advanced:
        eod_high_pct = st.slider("High Buffer % (+)", 0.0, 50.0, 10.0, 0.5)
        eod_low_pct = st.slider("Low Buffer % (-)", 0.0, 50.0, 10.0, 0.5)
    else:
        eod_pct = st.slider("EOD Buffer % (+High / -Low, dono saath)", 0.0, 50.0, 10.0, 0.5)
        eod_high_pct = eod_pct
        eod_low_pct = eod_pct

with st.sidebar.expander("🔧 Rule Toggles & Target", expanded=False):
    target_rr = st.number_input("Target RR (min 1:3)", min_value=3.0, max_value=10.0, value=3.0, step=0.5)
    en_wick = st.checkbox("Rule1: Leg-in closing wick guard", value=True)
    en_cover = st.checkbox("Rule2: Leg-out 90% coverage guard", value=True)
    en_hq = st.checkbox("Rule3: Boring-colour HQ flag", value=True)
    en_white = st.checkbox("Rule4: White-area tag", value=True)

with st.sidebar.expander("🗄️ Cache / Refresh", expanded=False):
    force_rescan = st.button("🔄 Force Rescan (bypass cache)", use_container_width=True)
    st.caption(
        "Scan sirf tab dobara chalta hai jab us timeframe ki candle actually "
        "CLOSE hoti hai (NSE session + holidays aware) - bade timeframes par load nahi badhta."
    )

# -----------------------------------------------------------------------------
# Cached raw data fetchers - keyed to each dataset's OWN candle-close bucket
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_15m(bucket_key, tick_tuple):
    return data_fetch.fetch_15m(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_60m(bucket_key, tick_tuple):
    return data_fetch.fetch_60m(list(tick_tuple))

@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_fetch_daily(bucket_key, tick_tuple):
    return data_fetch.fetch_daily(list(tick_tuple))


def relevant_bucket_key(tf: str):
    if tf in ("15m", "30m", "75m"):
        return ("15m", cc.last_closed_bucket("15m"))
    if tf in ("1H", "2H", "4H", "6H"):
        return ("1H", cc.last_closed_bucket("1H"))
    return ("Daily", cc.last_closed_bucket("Daily"))


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def cached_scan(tf, bucket_key, params_tuple, tick_tuple, states_tuple):
    params = dict(params_tuple)
    raw15 = cached_fetch_15m(cc.last_closed_bucket("15m"), tick_tuple) if tf in ("15m", "30m", "75m") else {}
    raw60 = cached_fetch_60m(cc.last_closed_bucket("1H"), tick_tuple) if tf in ("1H", "2H", "4H", "6H") else {}
    rawd = cached_fetch_daily(cc.last_closed_bucket("Daily"), tick_tuple) if tf in ("Daily", "Weekly", "Monthly") else {}
    frames = scanner.build_timeframe_frames(tf, raw15, raw60, rawd)
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
    cached_fetch_15m.clear()
    cached_fetch_60m.clear()
    cached_fetch_daily.clear()
    st.sidebar.success("Cache cleared - fresh scan chal raha hai...")

# -----------------------------------------------------------------------------
# Header / status bar
# -----------------------------------------------------------------------------
st.title("📈 NSE F&O Supply/Demand Zone Scanner")
status = cc.market_status()
col1, col2, col3 = st.columns(3)
col1.metric("Universe", f"{len(tickers)} / {total_n} stocks", universe_source)
col2.metric("Market", "🟢 OPEN" if status["open"] else "🔴 CLOSED")
col3.metric("Timeframes selected", f"{len(tf_selected)} / {len(scanner.TF_LIST)}")

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


def render_table(df: pd.DataFrame, tf_label: str):
    df = apply_display_filters(df)
    if df.empty:
        st.info(f"[{tf_label}] Is filter ke sath koi live zone nahi mili.")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Zones", len(df))
    m2.metric("Demand", int(df["Direction"].str.contains("DEMAND").sum()))
    m3.metric("Supply", int(df["Direction"].str.contains("SUPPLY").sum()))
    m4.metric("HQ (Rule3)", int(df["HQ Zone (Rule3 Boring-Colour)"].sum()))

    st.dataframe(
        df.drop(columns=["Ticker"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Symbol": st.column_config.LinkColumn(
                "Symbol (TradingView Chart)",
                display_text=r".*symbol=NSE%3A(.*)",
            ),
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
    st.download_button(f"⬇️ Download {tf_label} zones as CSV", csv, file_name=f"zones_{tf_label}.csv",
                        mime="text/csv")


# -----------------------------------------------------------------------------
# Main scan - staged status feedback so it never LOOKS frozen, even on a
# slow/blocked network (a common issue on free cloud hosting with Yahoo).
# -----------------------------------------------------------------------------
needs_15m = any(tf in ("15m", "30m", "75m") for tf in tf_selected)
needs_60m = any(tf in ("1H", "2H", "4H", "6H") for tf in tf_selected)
needs_daily = any(tf in ("Daily", "Weekly", "Monthly") for tf in tf_selected)

with st.status("Data fetch + scan chal raha hai...", expanded=True) as status_box:
    if needs_15m:
        st.write("⏳ 15m data fetch ho raha hai (Yahoo, last ~60 din)...")
        _ = cached_fetch_15m(cc.last_closed_bucket("15m"), tickers)
        st.write(f"✅ 15m data mila: {len(_)} / {len(tickers)} symbols")
    if needs_60m:
        st.write("⏳ 1H (60m) data fetch ho raha hai...")
        _ = cached_fetch_60m(cc.last_closed_bucket("1H"), tickers)
        st.write(f"✅ 1H data mila: {len(_)} / {len(tickers)} symbols")
    if needs_daily:
        st.write("⏳ Daily data fetch ho raha hai...")
        _ = cached_fetch_daily(cc.last_closed_bucket("Daily"), tickers)
        st.write(f"✅ Daily data mila: {len(_)} / {len(tickers)} symbols")

    results = {}
    for tf in tf_selected:
        st.write(f"🔎 Scanning {tf} ...")
        bkt = relevant_bucket_key(tf)
        results[tf] = cached_scan(tf, bkt[1], params_tuple, tickers, states_tuple)
    status_box.update(label="✅ Scan complete", state="complete", expanded=False)

if len(tf_selected) == 1:
    render_table(results[tf_selected[0]], tf_selected[0])
else:
    tabs = st.tabs(tf_selected)
    for tf, tab in zip(tf_selected, tabs):
        with tab:
            render_table(results[tf], tf)

st.markdown("---")
with st.expander("ℹ️ Methodology / Limitations"):
    st.markdown("""
- **Data source**: Yahoo Finance (`yfinance`, with a Chrome-impersonating `curl_cffi` session and
  fast-fail timeouts to avoid hanging on cloud hosting where Yahoo can throttle requests).
  15m/30m/75m are built from Yahoo's 15-minute candles (last ~60 days - Yahoo's hard limit; fine
  for a *live* scanner, unlike a multi-year backtest).
- **2H/4H/6H** are built by grouping 1H (60m) bars **per trading day starting at 09:15 IST**
  (not naive clock-resampling, since the session doesn't divide evenly). **75m** groups 5
  consecutive 15m bars per day (25 slots/day -> 5 clean 75-minute bars).
- **Weekly/Monthly** are resampled from Daily bars.
- **Entry = Proximal line**, **Stop Loss = Distal line + ATR buffer**, **Target = Entry +/- Risk x targetRR**
  exactly as computed by `zone_core.py` (rules/logic unchanged - only a pure performance fix was
  applied, verified zone-for-zone identical to the original).
- **Universe size** is a Top-N by market-cap slider (bundled rank snapshot, refreshed offline via
  `build_market_cap_tiers.py` - no live dependency at runtime, so it's always instant).
- **Refresh-on-candle-close**: every timeframe's scan is cached against a session-aware "candle
  bucket" key (NSE holidays included) - switching filters or reloading does **not** re-hit Yahoo
  or re-scan unless that timeframe's own candle has actually closed. Use "Force Rescan" to bypass.
- **F&O universe list**: fetched live from `nseindia.com` when possible, falls back to a bundled
  snapshot automatically when NSE blocks the request (common on cloud IPs).
    """)
