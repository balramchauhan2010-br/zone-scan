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

## Features

- **Clean, collapsible sidebar**: Timeframes and Universe-size are the only
  always-visible controls; EOD Range Filter, Rule Toggles/Target RR, and
  Cache/Force-Rescan are tucked into small collapsed expanders so the
  sidebar stays compact.
- **Timeframes multiselect** - all 10 selected by default (short labels:
  15m/30m/75m/1H/2H/4H/6H/Daily/Weekly/Monthly); deselect any you don't need
  for a faster scan. Results render as tabs (or directly if only one is
  picked).
- **Market-Cap universe slider**: a single clean "Top N by Market Cap"
  control (Top 25/50/75/100/150/200/All) instead of tier checkboxes/chips -
  smaller N = faster scan. Backed by a bundled rank snapshot
  (`market_cap_tiers.json`, built offline via `build_market_cap_tiers.py`,
  no live dependency at runtime so it's always instant).
- **EOD-Range filter** (day-candle-close High +X% / Low -X%) is a single
  combined slider by default (applies the same % to both High and Low) -
  toggle "Advanced" inside the expander if you want them independent.
- **TradingView chart links** built directly into the Symbol column.
- CSV export of the table shown.
- **Refresh only on candle close.** Every timeframe's scan result is cached
  against a session-aware "candle bucket" (NSE holidays included) - so a
  Daily/Weekly/Monthly scan is *not* re-run on every page reload, only when
  that timeframe's own candle actually closes. This keeps load low on
  bigger timeframes as requested. A "Force Rescan Now" button is available
  to bypass the cache deliberately.
- **TradingView chart links** are built directly into the Symbol column.
- Sidebar toggles for all 4 extra rules, target R:R (>= 1:3 enforced),
  zone state (Fresh/Tested), direction (Demand/Supply), and an HQ-only
  filter.
- CSV export of the table shown.

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
data_fetch.py            - chunked yfinance downloads (with request timeouts)
scanner.py               - builds timeframe frames + runs zone_core + tidy table
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
was used in the "Universe" metric at the top of the app.

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
- The NSE holiday calendar baked into `candle_clock.py` is a best-effort
  list (2025-2026); update it for future years.
