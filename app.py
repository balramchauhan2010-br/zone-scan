import time

import pandas as pd
import streamlit as st

import zone_core as zc
import data_fetch
import scanner
import candle_clock as cc
import market_cap as mc
from fno_universe import get_fno_symbols, to_yahoo_tickers

st.set_page_config(page_title="NSE F&O Supply/Demand Zone Scanner", layout="wide", page_icon="📈")

# -----------------------------------------------------------------------------
# Sidebar - controls
# -----------------------------------------------------------------------------
st.sidebar.title("⚙️ Scanner Settings")

tf_choice = st.sidebar.selectbox(
    "Timeframe", scanner.TF_LIST + ["🔎 Scan ALL timeframes (heavy)"], index=3,
)

st.sidebar.markdown("---")
st.sidebar.subheader("Stock Universe (Market-Cap based)")
st.sidebar.caption("Kam stocks scan karne ke liye chhote tier chunein - scan utna hi fast hoga.")
_all_tiers_counts = mc.tier_counts(to_yahoo_tickers(get_fno_symbols(try_live=False)[0]))
tier_labels = [f"{t} - {_all_tiers_counts.get(t, 0)} stocks" for t in mc.TIER_ORDER if _all_tiers_counts.get(t, 0) > 0]
tier_label_to_key = {lbl: t for lbl, t in zip(tier_labels, [t for t in mc.TIER_ORDER if _all_tiers_counts.get(t, 0) > 0])}
selected_tier_labels = st.sidebar.multiselect(
    "Market Cap Tiers", tier_labels, default=tier_labels,
)
selected_tiers = [tier_label_to_key[l] for l in selected_tier_labels] or list(tier_label_to_key.values())

st.sidebar.markdown("---")
st.sidebar.subheader("EOD Range Filter (Day-Close +X% / -X%)")
eod_advanced = st.sidebar.checkbox("Advanced: alag High/Low % set karein", value=False)
if eod_advanced:
    eod_high_pct = st.sidebar.slider("High Buffer % (+)", 0.0, 50.0, 10.0, 0.5,
                                      help="Din ke EOD High se kitna % upar tak zone valid maana jaaye")
    eod_low_pct = st.sidebar.slider("Low Buffer % (-)", 0.0, 50.0, 10.0, 0.5,
                                     help="Din ke EOD Low se kitna % neeche tak zone valid maana jaaye")
else:
    eod_pct = st.sidebar.slider(
        "EOD Range Buffer % (+High / -Low, dono ek saath)", 0.0, 50.0, 10.0, 0.5,
        help="Zone sirf tab valid maani jaayegi jab woh Din ke EOD High+X% aur Low-X% ke range ke andar ho.",
    )
    eod_high_pct = eod_pct
    eod_low_pct = eod_pct

st.sidebar.markdown("---")
st.sidebar.subheader("Target Risk:Reward")
target_rr = st.sidebar.number_input("Target RR (minimum 1:3 enforced)", min_value=3.0, max_value=10.0,
                                     value=3.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.subheader("Rule Toggles (Rules 1-4)")
en_wick = st.sidebar.checkbox("Rule1: Leg-in closing wick guard", value=True)
en_cover = st.sidebar.checkbox("Rule2: Leg-out 90% coverage guard", value=True)
en_hq = st.sidebar.checkbox("Rule3: Boring-colour HQ flag", value=True)
en_white = st.sidebar.checkbox("Rule4: White-area tag", value=True)

st.sidebar.markdown("---")
state_filter = st.sidebar.multiselect("Zone State", ["Fresh", "Tested"], default=["Fresh", "Tested"])
direction_filter = st.sidebar.radio("Direction", ["Both", "Demand only", "Supply only"], index=0)
hq_only = st.sidebar.checkbox("Show HQ zones only (Rule3)", value=False)

force_rescan = st.sidebar.button("🔄 Force Rescan Now (bypass cache)")

st.sidebar.markdown("---")
st.sidebar.caption(
    "Refresh policy: scan sirf tab dobara chalta hai jab us timeframe ki candle "
    "actually CLOSE hoti hai (session-aware, NSE holidays included) - isse bade "
    "timeframes (Daily/Weekly/Monthly) par load nahi badhta."
)

# -----------------------------------------------------------------------------
# Universe
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=24 * 3600)
def cached_universe():
    return get_fno_symbols(try_live=True)

symbols, universe_source = cached_universe()
all_tickers = to_yahoo_tickers(symbols)
tickers = tuple(mc.filter_tickers_by_tier(all_tickers, selected_tiers))


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
col1, col2, col3, col4 = st.columns(4)
col1.metric("Universe (selected tiers)", f"{len(tickers)} / {len(symbols)} stocks", universe_source)
col2.metric("Market", "🟢 OPEN" if status["open"] else "🔴 CLOSED")
if tf_choice != "🔎 Scan ALL timeframes (heavy)":
    col3.metric("Next candle close", cc.next_close_eta(tf_choice))
    bkt = relevant_bucket_key(tf_choice)
    col4.metric("Cache bucket (this TF)", str(bkt[1]))
else:
    col3.metric("Mode", "All timeframes")
    col4.metric("Note", "Har TF apni candle-close par refresh hoti hai")

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
# Main scan
# -----------------------------------------------------------------------------
if tf_choice == "🔎 Scan ALL timeframes (heavy)":
    st.warning("Yeh sabhi 9 timeframes ko scan karega - pehli baar (cold cache) mein kaafi time lag sakta hai.")
    tabs = st.tabs(scanner.TF_LIST)
    for tf, tab in zip(scanner.TF_LIST, tabs):
        with tab:
            with st.spinner(f"Scanning {tf} ..."):
                bkt = relevant_bucket_key(tf)
                df = cached_scan(tf, bkt[1], params_tuple, tickers, states_tuple)
            render_table(df, tf)
else:
    with st.spinner(f"Scanning {tf_choice} ..."):
        bkt = relevant_bucket_key(tf_choice)
        df = cached_scan(tf_choice, bkt[1], params_tuple, tickers, states_tuple)
    render_table(df, tf_choice)

st.markdown("---")
with st.expander("ℹ️ Methodology / Limitations"):
    st.markdown("""
- **Data source**: Yahoo Finance (`yfinance`). 15m/30m/75m are built from Yahoo's 15-minute
  candles, which are only available for the **last ~60 days** (a hard Yahoo limit) - this is a
  live scanner, so that's enough context, unlike a multi-year historical backtest.
- **2H/4H/6H** are built by grouping 1H (60m) bars **per trading day starting at 09:15 IST**
  (not naive clock-resampling, since the session doesn't divide evenly).
- **75m** is built by grouping 5 consecutive 15m bars per day (5 x 15 = 75), which divides the
  09:15-15:30 session evenly (25 fifteen-minute slots -> 5 clean 75-minute bars/day).
- **Weekly/Monthly** are resampled from Daily bars.
- **Entry = Proximal line**, **Stop Loss = Distal line + ATR buffer**, **Target = Entry +/- Risk x targetRR**
  exactly as computed by `zone_core.py` (all 4 extra rules configurable in the sidebar).
- **Refresh-on-candle-close**: every timeframe's scan is cached against a session-aware
  "candle bucket" key (NSE holidays included) - so switching tabs/filters or reloading the page
  does **not** re-hit Yahoo or re-scan unless that timeframe's own candle has actually closed.
  Use "Force Rescan Now" to bypass this deliberately.
- **F&O universe list**: fetched live from `nseindia.com` when possible; NSE often blocks
  datacenter IPs (incl. Streamlit Cloud), so a bundled fallback snapshot is used automatically
  when the live call fails. Refresh it periodically by running `python fno_universe.py --refresh`
  from a normal (non-cloud) connection and committing the updated JSON.
    """)
