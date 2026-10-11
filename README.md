# NSE F&O Supply/Demand Zone Scanner (Streamlit)

A live scanner that runs the `zone_core.py` Supply/Demand zone-detection engine
(RBR / DBR / DBD / RBD patterns, with the 4 extra rules: leg-in closing-wick
guard, leg-out 90% coverage guard, boring-colour HQ flag, white-area tag)
across the entire **NSE F&O stock universe**, on **15m, 30m, 75m, 1H, 2H, 4H,
6H, Daily, Weekly and Monthly** timeframes, and shows every currently-live
zone in one table: **Symbol (clickable TradingView chart link), Entry
(Proximal), Stop Loss (Distal+buffer), Target, and live distance from the
current price.**

## Performance

Two separate problems were found and fixed - **zero changes to `zone_core.py`'s
rules/trading-logic**, both are pure engineering/robustness fixes:

1. **Compute bug (O(n²)):** `get_eod_range()` recomputed `df.index.date`
   (converts the WHOLE index to python date objects) and re-filtered the
   WHOLE dataframe **on every single bar**. Fixed by precomputing the
   per-day High/Low **once** (vectorized) and doing an O(1) lookup per bar -
   **mathematically identical results**, verified zone-for-zone against the
   old engine with zero mismatches, up to **~50x faster** (1H full-universe:
   575s -> ~11s).
2. **Network hangs on cloud hosting:** Yahoo Finance is known to
   throttle/block requests from datacenter IP ranges (exactly what
   Streamlit Community Cloud runs on) much more than a home connection. The
   old fetch code could retry for minutes before giving up. Fixed by:
   - Using a `curl_cffi` session with **Chrome TLS/browser impersonation**
     (the standard community fix for yfinance requests being silently
     blocked) instead of a plain `requests` session.
   - **Fast-fail timeouts** (10s) and only 1 retry (was up to 3x20s), so a
     blocked request fails in seconds instead of hanging.
   - A **staged `st.status()` progress panel** in the UI ("fetching 15m...",
     "scanning 4H...", etc.) so the app never *looks* frozen even if one
     stage is genuinely slow.
   - A smaller **default universe (Top 50 by market cap)** so the first
     load is light; scan more via the sidebar slider once you're happy with
     the speed.

With these fixes, a full default scan (all 9 timeframes, Top-50 universe)
completes in **under 20 seconds** end-to-end in testing.

**Note:** `zone_core.py` has NOT been touched again since the original perf
fix - every change above and in the "UI cleanup" round is either a network/
robustness fix (`data_fetch.py`) or a pure display/layout change (`app.py`).
The rules, conditions, and trading logic are byte-for-byte the same file.

## Features

- **No permanent sidebar** - all Scanner Settings live behind a small **⚙️
  gear icon in the top-left corner** (a `st.popover`). Opening it reveals
  Timeframes, Universe size, Filters, and the 3 expanders below; closing it
  gives the results table the FULL page width. Nothing is lost, it's just
  tucked away until needed.
- **Timeframes multiselect** - all 10 selected by default (short labels:
  15m/30m/75m/1H/2H/4H/6H/Daily/Weekly/Monthly); deselect any you don't need
  for a faster scan.
- **Every selected timeframe is scanned AND shown together in ONE combined
  table** (Symbol still links to the right TradingView chart, a new
  "Timeframe" column - right after Symbol - tells you which timeframe each
  row came from). A "View Timeframe(s)" filter above the table lets you
  narrow the *display* to specific timeframes instantly, without
  re-scanning anything.
- **Market-Cap universe slider**: a single clean "Top N by Market Cap"
  control (Top 25/50/75/100/150/200/All) instead of tier checkboxes/chips -
  smaller N = faster scan. Backed by a bundled rank snapshot
  (`market_cap_tiers.json`, built offline via `build_market_cap_tiers.py`,
  no live dependency at runtime so it's always instant).
- **EOD-Range filter** (day-candle-close High +X% / Low -X%) is a single
  combined slider by default (applies the same % to both High and Low) -
  toggle "Advanced" inside the expander if you want them independent.
- **TradingView chart links with the correct timeframe pre-selected**: the
  Symbol column's link now embeds the row's own timeframe as a TradingView
  `interval` param, so the chart opens directly on the SAME timeframe as
  the scanned zone (15m row -> chart opens on 15m, Daily row -> opens on
  Daily, etc.) instead of TradingView's default/last-used interval.
- **Refresh only on candle close.** Every timeframe's scan result is cached
  against a session-aware "candle bucket" (NSE holidays included) - so a
  Daily/Weekly/Monthly scan is *not* re-run on every page reload, only when
  that timeframe's own candle actually closes. This keeps load low on
  bigger timeframes as requested. A "Force Rescan Now" button is available
  to bypass the cache deliberately.
- Toggles for all 4 extra rules, target R:R (>= 1:3 enforced), zone state
  (Fresh/Tested), direction (Demand/Supply), and an HQ-only filter.
- CSV export of the table shown.
- **Custom timeframes**: beyond the 10 presets, type any `<number>m` or
  `<number>H` value into the Timeframes box (e.g. `5m`, `3m`, `45m`, `3H`)
  and press Enter to add/remove it. Built the exact same session-aware way
  as the existing 30m/75m/2H/4H/6H presets (grouping native 1m/5m/15m/60m
  Yahoo bars per trading day) - `zone_core.py` is never touched.
- **🌍 Top Global Instruments (optional universe add-on)**: add any of 15
  major global benchmarks - DXY, USD/INR, TLT, US 10Y Yield, Gold, Silver,
  WTI Crude, Dow/S&P500, Shanghai Composite, FTSE China A50, Nikkei 225,
  Nifty/GIFT-Nifty futures (proxy), FTSE 100, DAX - on top of the normal
  NSE stock universe. Same unchanged zone_core.py engine runs on them; thin
  Yahoo data for some asset classes is skipped gracefully like any stock
  with too few bars.
- **🧠 AI Trader Pulse (NEW, senior D&S trader briefing)**: a compact top strip
  (market phase + NIFTY PCR + FII/DII + global cues + one-line AI bias) and a
  full **Pre-Market / Post-Market briefing** section with:
  - **Delivery %** (today vs previous day), **% of F&O futures stocks
    increased** (breadth), **Option OI signals** (PCR, max pain,
    support/resistance, long/short buildup), **FII/DII**, **volume vs
    yesterday** — all from free NSE sources (bhavcopy + option chain), no API
    key needed
  - **4 new columns in the zone table** on both pages: `Delivery %`,
    `ΔDeliv pp`, `Vol ×Yday`, `OI Signal`
  - **🤖 AI short summary** (Hinglish, rule-based, works without any key;
    Gemini key ho to ek button se aur gehri ho sakti hai) — sab data ka fusion
    with **matlab (meaning)** and **forecast** for the next session
  - **Top 10 BUY / Top 10 SELL** forecast — zone proximity + freshness/HQ +
    delivery + volume + OI + PCR + FII/DII + global + news ka composite score,
    with a Hinglish reason for every pick
  - Market phase ke hisaab se **default section auto-select** hota hai
    (🌅 Pre-Market Setup / 🌇 Post-Market Review)
  - See `TRADER_PULSE_ANALYSIS.md` for the full gap analysis (kya kami thi,
    kya add hua, trader ko har column ka kya matlab hai) and the daily workflow.
- **Live Market Watch ticker-tape** at the top of the page: 6 small
  clickable badges (GIFT NIFTY, NIFTY 50, BANK NIFTY, USD/INR, XAUUSD,
  SPOTCRUDE) with live price + %-change, refreshed every 3 minutes -
  replaces the old Universe/Market/Timeframes metrics row.
- **Small "tag" style summary** (Total Zones / Demand / Supply / HQ) instead
  of large metric numbers, plus a **📍 NIFTY50 nearest-zone badge** showing
  the single Daily-timeframe zone closest to the current Nifty 50 price.

## Project layout

```
zone_core.py             - the zone-detection engine (unchanged core logic + 4 rules, perf-fixed)
resample_utils.py        - session-aware resampling (2H/4H/6H/30m/75m/Weekly/Monthly)
candle_clock.py          - NSE-session-aware "has this candle closed yet" clock
fno_universe.py          - NSE F&O stock list (live fetch + bundled fallback)
fno_stocks_fallback.json - bundled snapshot used when the live NSE call is blocked
market_cap.py            - market-cap tier lookup (reads market_cap_tiers.json)
market_cap_tiers.json    - bundled rank-based market-cap tiers (offline, instant)
build_market_cap_tiers.py- offline script to refresh market_cap_tiers.json
global_instruments.py    - optional Top-Global-Instruments universe add-on + Market Watch ticker-tape list
data_fetch.py            - chunked yfinance downloads (with request timeouts)
scanner.py               - builds timeframe frames (incl. custom TFs) + runs zone_core + tidy table
market_pulse.py          - NEW: AI Trader Pulse (delivery %, F&O breadth %, option OI/PCR,
                           FII/DII, volume, global+news AI summary, Top 10, pre/post-market)
indicators_hypothesis.py - NEW: RSI/EMA/Supertrend/MACD + rule-based Hinglish hypothesis
                           (app.py already imported this optionally — file was missing)
app.py                   - the Streamlit UI
requirements.txt
```

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repo (public or private).
2. Go to https://share.streamlit.io -> "New app" -> pick the repo/branch and
   set the main file to `app.py`.
3. Deploy. No secrets are required (yfinance and the NSE API are both public).

### Important note about the NSE F&O list on Streamlit Cloud

NSE's website frequently blocks requests coming from datacenter IPs
(AWS/GCP/etc., which is exactly what Streamlit Cloud runs on). The app tries
a live fetch first and **automatically falls back** to the bundled
`fno_stocks_fallback.json` snapshot if that fails - you'll see which source
was used in the small caption under "Universe (Market-Cap size)" inside the
⚙️ Settings popover.

To refresh the bundled snapshot (recommended every 1-2 months, since NSE
adds/removes F&O stocks periodically), run this from a normal (non-cloud)
internet connection and commit the updated file:

```bash
python fno_universe.py --refresh
```

## Data limitations (please read)

- 15m/30m/75m candles: Yahoo Finance only serves the **last ~60 days** of
  intraday history. That's plenty of context for a *live* scanner (unlike a
  multi-year historical backtest), but don't expect older intraday zones.
- 2H/4H/6H/75m are **not native Yahoo intervals** - they are built by
  grouping 1H or 15m bars **per NSE trading day starting at 09:15 IST**
  (not naive clock-resampling), since the 09:15-15:30 session doesn't divide
  evenly on the clock.
- No brokerage/slippage/position-sizing is modelled - this is a zone
  scanner, not a full trading/execution system.
- AI Trader Pulse EOD data (delivery %, OI, breadth) comes from NSE bhavcopy
  files, which NSE publishes only **after ~18:30-19:00 IST**. Before that,
  the pulse shows the latest available trading day (clearly date-labelled).
  Intraday, live signals (option chain OI, live breadth) still work.
- `python market_pulse.py` runs a fixture-based self-test (no network) against
  the real NSE file formats; `python indicators_hypothesis.py` likewise.
- The NSE holiday calendar baked into `candle_clock.py` is a best-effort
  list (2025-2026); update it for future years.


---

## 🆕 Recent updates (performance + UI polish)

### 🐛 Fix: "502 Bad Gateway" (Render free OOM)
`data_fetch.py` me chunk chhota, `float32` downcast, `KEEP_BARS` trim aur
`gc.collect()` — memory ~700 MB se ghat kar **~200 MB**.
Poora detail: **[`PERFORMANCE.md`](PERFORMANCE.md)**

### 🐛 Fix: "All (0)" — universe load nahi hota tha
`fno_universe.py` me **210 symbols embedded** safety-net — JSON file
missing ho to bhi universe poora rahta hai.

### ✨ UI
- **Circular logo** + **round ⚙️ settings button** (clean header)
- **🧪 Diagnostics** expander — live memory + Render limits
- **📏 Full column names** toggle (Settings ⚙️) — `TF/Dir/SL/LTP` ki jagah
  `Timeframe / Direction / Stop Loss (Distal+Buffer) / Current Price`

### 🔒 Guarantee
`python3 verify_zone_source.py` — 4/4 checks pass. Zones sirf
`zone_core.py` / `zone_core_validation.py` se aate hain.

### 🗺️ Aage kya
**[`ROADMAP.md`](ROADMAP.md)** — Tier 1 (forward-test journal) se shuru karo.
