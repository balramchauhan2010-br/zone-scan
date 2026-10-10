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
nse_mcp_client.py          - NEW: official NSE MCP client (persistent session, parallel calls,
                           TTL cache, circuit breaker) - keyless live-LTP fallback + market data
test_nse_mcp_client.py  - NEW: 14 tests (local mock NSE MCP server, no internet needed)
nse_fno_context.py       - NEW: F&O live context panel (breadth, movers, volume spikes, OI top-10, index movers, corp actions)
test_nse_fno_context.py  - NEW: panel logic + Streamlit render smoke tests (no internet)
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

## NSE MCP integration (keyless, official NSE data server)

NSE publishes two public MCP servers (Streamable HTTP, no login, no API key):

| Server | Endpoint | Use in this app |
| --- | --- | --- |
| `cm-market` (live) | `https://mcp.nseindia.in/cmmkt/mcp` | Live quote fallback for LTP tape / table (`cm_get_stock_quote`), live gainers/losers (`nse_get_market_movers`), data freshness (`cm_get_data_status`) |
| `nse-bhavcopy` (EOD) | `https://mcp.nseindia.in/bhavcopy/cm/mcp` | 52-week high/low, market breadth, corporate actions, top-by-volume |

### Latency: what is fast and what is not

- **Live LTP priority is unchanged for speed:** Dhan (real-time, 5s cache) > Yahoo
  (20s cache) > **NSE MCP** (new, last fallback, only for NSE stocks that Dhan and
  Yahoo both missed). NSE's own live feed is 1-3 min behind and refreshes about every
  5 min, so putting it first would make the tape *slower*.
- **NSE MCP has no intraday candles** (no 15m/1H/etc. bars for any tool). The zone
  scanner's candles therefore still come from Dhan intraday / Yahoo. Zone rules
  (`zone_core.py`, `scanner.py`) are not touched.
- **Latency controls in `nse_mcp_client.py`:**
  1. one persistent MCP session reused for the whole app (no handshake per call),
  2. batch quotes run in parallel (max 8 in flight),
  3. TTL cache: quote 10s, movers 60s, breadth/top-volume 15 min, corporate actions 30 min, 52W 1h,
  4. circuit breaker: if NSE is unreachable, it is skipped for 60s, so the UI never hangs
     (connect timeout 5s, call timeout 6s),
  5. tool arguments are filtered against each tool's JSON schema, so a small NSE
     signature change does not crash the app.

### Configuration

| Env var | Default | Effect |
| --- | --- | --- |
| `NSE_MCP_ENABLED` | `1` | `0` disables NSE MCP completely |
| `NSE_MCP_LIVE_URL` | `https://mcp.nseindia.in/cmmkt/mcp` | override live endpoint |
| `NSE_MCP_BHAVCOPY_URL` | `https://mcp.nseindia.in/bhavcopy/cm/mcp` | override EOD endpoint |

`mcp>=1.20,<2` is in `requirements.txt` (the `mcp` 2.x SDK has a different API).

### F&O Live Context panel (NSE MCP) - new

Ek naya section (app me AI Trader Pulse ke neeche) sirf **NSE F&O stocks** ke liye:

| Tab / block | Data source | Kya dikhata hai |
| --- | --- | --- |
| Breadth + mood (top cards) | NSE MCP live snapshot (F&O only) | F&O me kitne stocks up/down, average move, mood |
| 📈 Top 10 Gainers / Losers | NSE MCP live | F&O stocks ka live % move |
| ⚡ Volume Spikes | NSE MCP live volume + 20-din average (bhavcopy server, 6h cache) | Time-adjusted volume ratio (session ke hisaab se) |
| 🔼 / 🔽 Top 10 OI Increase / Decrease | **Live futures OI** (Dhan → NSE fallback → EOD) + live price + live spike + zone | Futures OI change vs pichhla close, `OI Source` (Dhan / NSE / EOD), OI signal, 'Read' verdict |
| 🧭 Index Movers (F&O) | NSE MCP `cm_get_live_gainers/losers` (index-wise) filtered to F&O | NIFTY / BANK NIFTY etc. ke andar F&O movers |
| 🏢 Corporate Actions | NSE MCP `get_corporate_actions` | Zone/OI stocks ke liye ±14 din me ex-date, bonus/split warning |

Important limits:
- **NSE MCP me OI / derivatives tool nahi hai.** Isliye live OI `live_oi.py` se aata hai (neeche dekhein).
  Jab live OI na mile, to panel EOD bhavcopy OI dikhata hai aur `OI Source` column me `EOD` likhta hai.
- Time-adjusted volume ek approximation hai (volume din me U-shape chalta hai; subah spike zyada dikhta hai).
- Pre-market me volume spike nahi dikhta. Post-market/holiday me poore din ka volume dikhta hai.
- Pehli baar 20-din average volume ke liye ~210 calls chalti hain (parallel), phir 6 ghante cache.
- Zone scanner (`zone_core.py`, `scanner.py`) is panel se prabhavit nahi hota; ye context hai.


### Verify the field names on your network (recommended once)

NSE endpoints are not reachable from every network (the build sandbox used for
this change could not reach them). Run this once from a normal internet connection:

```bash
python nse_mcp_client.py --probe RELIANCE
```

It prints the tool list, the schema of each tool, and the raw JSON of
`cm_get_stock_quote` and `get_52_week_high_low`. The quote parser looks for keys like
`lastPrice`/`last_price`/`ltp` and `pChange`/`change_pct` anywhere in the JSON. If your
output uses other names, add them to `_LTP_KEYS` / `_CHG_PCT_KEYS` in `nse_mcp_client.py`.

#### Live futures OI (`live_oi.py`)

OI ka baseline **pichhla session ka close OI** hai (EOD bhavcopy). Live OI usse compare hokar
"aaj ab tak OI kitna badha/ghata" dikhata hai. Source chain (sabse tez pehle):

1. **Dhan batch quote** (Dhan linked ho to): front-month FUTSTK security IDs ki ek batch call
   (500 IDs per call). Dhan scrip-master CSV se IDs milte hain (24 ghante cache).
2. **NSE `quote-derivative` fallback** (Dhan nahi hai): sirf priority stocks (zone wale + top OI movers),
   max 30, har call ke beech 0.35s gap; 3 lagatar failure par ruk jaata hai. Latency zyada hoti hai,
   isliye ye "thoda latency wala live" hai.
3. **EOD bhavcopy OI** (dono fail): label `EOD` ke saath.

Guards: live OI sirf tab use hota hai jab bhavcopy aaj ka nahi hai; live/baseline ratio 0.2–5.0 ke bahar
ho to us row ke liye EOD dikhata hai (expiry rollover ki galti se bachne ke liye). Cache 30 sec.

Dhan ke liye `secure_config` me Dhan creds hone chahiye (`dhan_api_helper` wala setup). Field names
(`oi`, `last_price`, master CSV columns) sandbox me verify nahi ho sake; apne network par check karein:

```bash
python live_oi.py --probe
```

Tests (run without internet, against a local mock MCP server and fakes):

```bash
pytest -q test_nse_mcp_client.py test_nse_fno_context.py test_live_oi.py
```

- **Dhan equity fix (latency):** `fast_live_price.py` never imported
  `load_dhan_master_fast`, so the Dhan batch path silently resolved zero NSE stocks and
  every stock fell through to Yahoo. The import is fixed and covered by a regression test.

### Terms and limits (please read)

- NSE states that MCP data is for **informational and educational use**, not for
  real-time trading, commercial deployment, or training AI models. Treat NSE MCP
  values as a fallback/context source. Do not rely on them as the only input for
  live trade decisions.
- Live NSE data is delayed by NSE's own crawl (about 1-3 minutes, refresh about 5 minutes).
- Daily history from `get_stock_history` is not split/bonus adjusted; use
  `get_corporate_actions` before computing long-range returns.

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
