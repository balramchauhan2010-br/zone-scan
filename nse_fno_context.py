"""
nse_fno_context.py - F&O stocks ke liye NSE MCP live market context panel
========================================================================

Sirf NSE F&O STOCK-FUTURES universe (index hata kar) par ye panel:

  1. F&O Breadth + Market Mood   - live snapshot se: kitne stocks up/down, average % move
  2. Top 10 Gainers / Losers     - live % change (F&O only)
  3. Volume Spikes               - live volume vs 20-din average, SESSION KE HISAAB SE
                                   (time-adjusted: subah 10 baje 2x ka matlab alag hai)
  4. Top 10 OI Increase/Decrease - futures OI change (EOD F&O bhavcopy, existing pipeline)
                                   + live price % + live volume spike + zone context
                                   + ek "Read" (expert verdict, Hinglish)
  5. Index Movers (F&O)          - NIFTY/BANKNIFTY etc. ke live gainers/losers, F&O me chhante hue
  6. Corporate Actions           - zone/OI stocks ke liye ±14 din me ex-date (bonus/split warning)

DATA SOURCES (aur kya NAHI hai):
  - Live price/volume/index movers  -> NSE MCP (cm-market server), 1-3 min delay
  - 20-din average volume           -> NSE MCP (bhavcopy server), 6 ghante cache
  - Futures OI change               -> EOD F&O bhavcopy (market_pulse.py), sham ~18:30 ke baad
    NSE MCP me koi OI/derivatives tool nahi hai (26 tools me nahi). Isliye OI "previous
    session" ka hai; intraday OI nahi. Live context (price + volume) se ise tazaa karte hain.
  - Market-wide breadth (NSE tool) F&O filter nahi karta -> hum F&O snapshot se breadth nikalte hain.

Ye context hai, trading signal nahi. NSE ki shart: MCP data educational/informational use ke liye.
Zone rules (zone_core.py / scanner.py) is panel se bilkul prabhavit nahi hote.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
from dateutil import parser as _dtparser

import candle_clock as cc
import market_pulse as mp
import nse_mcp_client as nmc

INDEX_NAMES = {"NIFTY", "NIFTY50", "NIFTY 50", "BANKNIFTY", "BANK NIFTY", "NIFTYBANK", "FINNIFTY",
               "FIN NIFTY", "MIDCPNIFTY", "MIDCAP NIFTY", "NIFTYNXT50", "NIFTY NEXT 50", "SENSEX",
               "BANKEX", "INDIAVIX", "NIFTYIT"}

MIN_FUT_OI = 100_000       # contracts: is se kam OI wale futures par % change bahut shor karta hai
SESSION_MIN = 375          # NSE 09:15-15:30
SPIKE_MIN = 1.5            # time-adjusted volume >= 1.5x  -> spike
SPIKE_STRONG = 2.0         # >= 2.0x -> strong spike
TOP_N = 10

COLS_LIVE = ["Symbol", "LTP", "Chg %", "Volume"]

# ============================================================ helpers (pure)

def clean_fno(symbols: Iterable[str]) -> Tuple[str, ...]:
    """Clean symbols, duplicates hatao, index names hatao -> sirf F&O STOCKS."""
    out = []
    for s in symbols or ():
        c = str(s).strip().upper().replace(".NS", "")
        if not c or c in INDEX_NAMES or c in out:
            continue
        out.append(c)
    return tuple(out)


def session_fraction(now: Optional[pd.Timestamp] = None) -> Optional[float]:
    """Aaj ka kitna session beet chuka hai (0..1).
    open   -> beete minute / 375   (volume ki 'kitna hona chahiye tha' ke liye)
    closed/post -> 1.0 (poora din; live snapshot = last session)
    pre_market -> None (abhi volume bana hi nahi)."""
    ph = mp.get_market_phase(now)
    if ph["phase"] == "pre_market":
        return None
    if ph["phase"] == "open":
        t = ph["now"]
        start = t.normalize() + pd.Timedelta(hours=9, minutes=15)
        elapsed = (t - start).total_seconds() / 60.0
        return float(min(1.0, max(1.0 / SESSION_MIN, elapsed / SESSION_MIN)))
    return 1.0


def live_frame(snapshot: Dict[str, dict], fno: Iterable[str]) -> pd.DataFrame:
    fno_set = set(fno)
    rows = [{"Symbol": s, "LTP": q.get("ltp"), "Chg %": q.get("change_pct"), "Volume": q.get("volume")}
            for s, q in (snapshot or {}).items() if s in fno_set]
    df = pd.DataFrame(rows, columns=COLS_LIVE)
    for c in ("LTP", "Chg %", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def breadth(df: pd.DataFrame) -> dict:
    """F&O breadth: up / down / flat + mood."""
    if df is None or df.empty or df["Chg %"].dropna().empty:
        return {"up": 0, "down": 0, "flat": 0, "total": 0, "pct_up": None, "avg_chg": None, "mood": "—"}
    c = df["Chg %"].dropna()
    up = int((c > 0.05).sum())
    down = int((c < -0.05).sum())
    total = int(len(c))
    flat = total - up - down
    pct_up = up / total * 100.0
    avg = float(c.mean())
    if pct_up >= 60 and avg > 0.3:
        mood = "Bullish 🟢"
    elif pct_up <= 40 and avg < -0.3:
        mood = "Bearish 🔴"
    else:
        mood = "Mixed ⚪"
    return {"up": up, "down": down, "flat": flat, "total": total,
            "pct_up": round(pct_up, 1), "avg_chg": round(avg, 2), "mood": mood}


def movers(df: pd.DataFrame, side: str = "gain", n: int = TOP_N) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=COLS_LIVE)
    d = df.dropna(subset=["Chg %"])
    d = d.sort_values("Chg %", ascending=(side == "loss")).head(n)
    return d[COLS_LIVE].reset_index(drop=True)


def ratio_frame(df: pd.DataFrame, baseline: Dict[str, float], frac: Optional[float]) -> pd.DataFrame:
    """Har F&O stock ke liye: avg (20d), expected-by-now, time-adjusted volume ratio."""
    d = df.copy()
    d["Avg Vol (20d)"] = d["Symbol"].map(baseline) if baseline else np.nan
    if frac is None or d.empty:
        d["Vol x (time-adj)"] = np.nan
        d["Expected by now"] = np.nan
        return d
    d["Expected by now"] = d["Avg Vol (20d)"] * frac
    with np.errstate(divide="ignore", invalid="ignore"):
        d["Vol x (time-adj)"] = d["Volume"] / d["Expected by now"]
    d.loc[~np.isfinite(d["Vol x (time-adj)"]), "Vol x (time-adj)"] = np.nan
    return d


def spikes(ratio_df: pd.DataFrame, n: int = TOP_N, min_ratio: float = SPIKE_MIN) -> pd.DataFrame:
    cols = ["Symbol", "LTP", "Chg %", "Volume", "Avg Vol (20d)", "Vol x (time-adj)"]
    if ratio_df is None or ratio_df.empty:
        return pd.DataFrame(columns=cols)
    d = ratio_df.dropna(subset=["Vol x (time-adj)"])
    d = d[d["Vol x (time-adj)"] >= min_ratio]
    d = d.sort_values("Vol x (time-adj)", ascending=False).head(n)
    return d[cols].reset_index(drop=True)


def zone_map(zones_df: Optional[pd.DataFrame]) -> Dict[str, str]:
    """Har symbol ka sabse paas wala active zone: {SYM: 'Demand · 0.8% door'}."""
    if zones_df is None or getattr(zones_df, "empty", True):
        return {}
    if not {"Ticker", "Direction", "Distance %"}.issubset(zones_df.columns):
        return {}
    out: Dict[str, Tuple[float, str]] = {}
    for _, r in zones_df.iterrows():
        sym = str(r["Ticker"]).upper().replace(".NS", "")
        try:
            dist = abs(float(r["Distance %"]))
        except (TypeError, ValueError):
            continue
        label = "Demand" if "DEMAND" in str(r["Direction"]).upper() else "Supply"
        if sym not in out or dist < out[sym][0]:
            out[sym] = (dist, f"{label} · {dist:.1f}% door")
    return {k: v[1] for k, v in out.items()}


_OI_LABEL = {
    "long_buildup": "Long build-up",
    "short_buildup": "Short build-up",
    "short_covering": "Short covering",
    "long_unwinding": "Long unwinding",
}


def verdict(sig_en: str, live_chg: Optional[float], ratio: Optional[float], zone_txt: str = "") -> str:
    """Expert 'Read': OI signal + live price direction + volume + zone -> ek line (Hinglish)."""
    if sig_en not in _OI_LABEL:
        return "—"
    lc = live_chg if (live_chg is not None and not np.isnan(live_chg)) else None
    if sig_en == "long_buildup":
        base = ("Fresh long build-up ✅ (price + OI dono badhe)" if lc is None or lc >= 0
                else "Long build-up par live price gir raha ⚠️ (divergence)")
    elif sig_en == "short_buildup":
        base = ("Fresh short build-up 🔻 (price gira, OI badha)" if lc is None or lc <= 0
                else "Short build-up par live price upar ⚠️ (squeeze risk)")
    elif sig_en == "short_covering":
        base = "Short covering 🟢 - rally naye long se nahi, kamzor ho sakti hai"
    else:  # long_unwinding
        base = "Long unwinding 🔴 - log positions chhod rahe hain"
    if ratio is not None and not np.isnan(ratio):
        if ratio >= SPIKE_STRONG:
            base += f" | 🔥 volume {ratio:.1f}x"
        elif ratio >= SPIKE_MIN:
            base += f" | ⚡ volume {ratio:.1f}x"
        else:
            base += " | volume normal"
    if zone_txt:
        base += f" | 📍 {zone_txt}"
    return base


def oi_table(fo_map: Dict[str, dict], ratio_df: pd.DataFrame, zones: Dict[str, str],
             fno: Iterable[str], direction: str = "inc", n: int = TOP_N) -> pd.DataFrame:
    """Top N futures OI increase (direction='inc') ya decrease ('dec') + live context."""
    cols = ["Symbol", "Fut OI Δ %", "Fut OI Δ (contracts)", "Fut OI (lakh)", "EOD Price %",
            "OI Signal (EOD)", "Live Price %", "Vol x (time-adj)", "Zone", "Read"]
    fno_set = set(fno)
    live = {}
    if ratio_df is not None and not ratio_df.empty:
        live = {r["Symbol"]: r for _, r in ratio_df.iterrows()}
    rows = []
    for sym, f in (fo_map or {}).items():
        if sym not in fno_set:
            continue
        pct = f.get("fut_oi_chg_pct")
        if pct is None or (isinstance(pct, float) and np.isnan(pct)):
            continue
        oi_now = f.get("fut_oi")
        if oi_now is None or oi_now < MIN_FUT_OI:
            continue  # bahut patla OI: % move meaningless
        if direction == "inc" and pct <= 0:
            continue
        if direction == "dec" and pct >= 0:
            continue
        lr = live.get(sym)
        live_chg = float(lr["Chg %"]) if lr is not None and pd.notna(lr["Chg %"]) else None
        ratio = float(lr["Vol x (time-adj)"]) if lr is not None and pd.notna(lr["Vol x (time-adj)"]) else None
        zt = zones.get(sym, "")
        sig = f.get("oi_signal_en", "neutral")
        oi = f.get("fut_oi")
        rows.append({
            "Symbol": sym,
            "Fut OI Δ %": round(float(pct), 2),
            "Fut OI Δ (contracts)": f.get("fut_oi_chg"),
            "Fut OI (lakh)": round(float(oi) / 1e5, 2) if oi else None,
            "EOD Price %": round(float(f["chg_pct"]), 2) if f.get("chg_pct") is not None else None,
            "OI Signal (EOD)": f.get("oi_signal", "—"),
            "Live Price %": round(live_chg, 2) if live_chg is not None else None,
            "Vol x (time-adj)": round(ratio, 2) if ratio is not None else None,
            "Zone": zt or "—",
            "Read": verdict(sig, live_chg, ratio, zt),
        })
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df = df.sort_values("Fut OI Δ %", ascending=(direction == "dec")).head(n)
    return df.reset_index(drop=True)


def market_mood(br: dict, oi_inc: pd.DataFrame, oi_dec: pd.DataFrame, n_spikes: int) -> Tuple[str, str]:
    """F&O overall mood: breadth + OI buildup ka balance + spikes."""
    b = br.get("mood", "—")
    lb = int((oi_inc["OI Signal (EOD)"] == "Long Buildup 🟢").sum()) if not oi_inc.empty else 0
    sb = int((oi_dec["OI Signal (EOD)"] == "Short Buildup 🔴").sum()) if not oi_dec.empty else 0
    if b.startswith("Bullish") and lb >= sb:
        mood = "Bullish 🟢"
    elif b.startswith("Bearish") and sb >= lb:
        mood = "Bearish 🔴"
    else:
        mood = "Mixed ⚪"
    reason = (f"breadth: {b} · OI top-10 me long build-up {lb} vs short build-up {sb} · "
              f"time-adj volume spikes: {n_spikes}")
    return mood, reason


def index_movers_table(groups: Dict[str, List[dict]], fno: Iterable[str], side: str = "gain",
                       n: int = 5) -> pd.DataFrame:
    fno_set = set(fno)
    rows = []
    for idx, recs in (groups or {}).items():
        cand = []
        for r in recs:
            sym = nmc._sym_of(r)
            if sym not in fno_set:
                continue
            q = nmc._quote_from(sym, r)
            if q:
                cand.append({"Index": idx, "Symbol": sym, "LTP": q["ltp"],
                             "Chg %": q["change_pct"], "Volume": q.get("volume")})
        cand.sort(key=lambda x: x["Chg %"], reverse=(side == "gain"))
        rows.extend(cand[:n])
    return pd.DataFrame(rows, columns=["Index"] + COLS_LIVE)


_EX_KEYS = ("exDate", "ex_date", "exdate", "exDt", "ex_dt", "ExDate", "Ex-Date", "exdt")
_PURPOSE_KEYS = ("purpose", "subject", "action", "series", "type", "description", "Purpose")


def _action_note(purpose: str) -> str:
    p = purpose.lower()
    if "bonus" in p or "split" in p or "face value" in p:
        return "⚠️ Bonus/Split: purane zone levels price adjust hue - re-check"
    if "dividend" in p:
        return "Dividend: chhota ex-date gap possible"
    if "right" in p:
        return "Rights: price/entitlement adjust ho sakta hai"
    return "—"


def corp_actions_table(raw_by_sym: Dict[str, object], today: Optional[dt.date] = None,
                       window: Tuple[int, int] = (-2, 14)) -> pd.DataFrame:
    today = today or cc.now_ist().date()
    cols = ["Symbol", "Action", "Ex-date", "Days to ex", "Note"]
    rows = []
    for sym, raw in (raw_by_sym or {}).items():
        recs = nmc.extract_records(raw, require_symbol=False)
        if not recs and isinstance(raw, dict) and nmc._first(raw, _EX_KEYS):
            recs = [raw]  # single record response
        for r in recs:
            ex_raw = nmc._first(r, _EX_KEYS)
            if not ex_raw:
                continue
            try:
                ex = _dtparser.parse(str(ex_raw), dayfirst=True, fuzzy=True).date()
            except (ValueError, OverflowError, TypeError):
                continue
            days = (ex - today).days
            if not (window[0] <= days <= window[1]):
                continue
            purpose = str(nmc._first(r, _PURPOSE_KEYS) or "—")
            rows.append({"Symbol": sym, "Action": purpose[:80], "Ex-date": ex.isoformat(),
                         "Days to ex": days, "Note": _action_note(purpose)})
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("Days to ex").reset_index(drop=True) if not df.empty else df


# ============================================================ cached fetchers

@st.cache_data(show_spinner=False, ttl=15)
def fetch_live(fno: tuple) -> dict:
    return nmc.get_client().live_snapshot(fno)


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def fetch_baselines(fno: tuple) -> dict:
    return nmc.get_client().avg_volumes(fno, days=20)


@st.cache_data(show_spinner=False, ttl=60)
def fetch_index_groups(side: str) -> dict:
    return nmc.get_client().index_movers("gainers" if side == "gain" else "losers")


@st.cache_data(show_spinner=False, ttl=1800)
def fetch_corp(syms: tuple) -> dict:
    return nmc.get_client().corporate_actions_many(syms)


def _fo_eod() -> dict:
    """EOD F&O bhavcopy (existing pipeline): {'map': {SYM: {...fut_oi...}}, 'date': iso}."""
    try:
        return mp._fo_auto() or {}
    except Exception as e:  # pragma: no cover - network
        print(f"fno context: EOD OI error: {e}")
        return {}


# ============================================================ UI

def _fmt_table(df: pd.DataFrame, empty_msg: str):
    if df is None or df.empty:
        st.caption(empty_msg)
        return
    st.dataframe(df, width="stretch", hide_index=True)


def render_nse_fno_panel(zones_df: Optional[pd.DataFrame], fno_symbols) -> None:
    """Main panel. Koi bhi data fail ho to bas khaali/caption dikhata hai - app kabhi nahi rukti."""
    try:
        _render(zones_df, fno_symbols)
    except Exception as e:
        print(f"NSE F&O context panel error (safe): {e}")
        st.caption("⚠️ NSE MCP F&O panel abhi load nahi hua - scanner aur baaki sections unaffected hain.")


def _render(zones_df, fno_symbols) -> None:
    fno = clean_fno(fno_symbols)
    st.markdown("---")
    st.header("📡 NSE MCP — F&O Stocks: Live Market Context")
    st.caption("Sirf NSE F&O stocks (index hata ke). Live data NSE MCP se (1-3 min delay). "
               "OI = futures OI, EOD bhavcopy se (NSE MCP me OI tool nahi hai). "
               "Ye context hai, trading signal nahi - NSE ki shart: educational use.")

    client = nmc.get_client()
    if not client.enabled:
        st.info("NSE MCP band hai (NSE_MCP_ENABLED=0 ya `mcp` package installed nahi). Scanner chalta rahega.")
        return
    if not fno:
        st.caption("F&O universe khaali hai.")
        return

    phase = mp.get_market_phase()
    frac = session_fraction()
    eod = _fo_eod()
    eod_date = eod.get("date", "—")

    with st.spinner("NSE MCP se F&O live snapshot..."):
        snap = fetch_live(fno)
    df = live_frame(snap, fno)
    st.caption(f"{phase['label']} · {len(df)}/{len(fno)} F&O stocks ka live data mila · "
               f"EOD OI date: {eod_date} · Volume baseline: 20-din average (6h cache)")

    if df.empty:
        st.warning("NSE MCP se F&O live data nahi aaya. Ye NSE endpoint ki reachability ya tool "
                   "signature ki wajah se ho sakta hai - `python nse_mcp_client.py --probe RELIANCE` chalayein.")
        with st.expander("🔧 NSE MCP status (debug)"):
            st.json(client.status())
        return

    baseline = {}
    if frac is not None:
        with st.spinner("20-din average volume (pehli baar ~1 min, phir cache)..."):
            baseline = fetch_baselines(fno)
    ratio_df = ratio_frame(df, baseline, frac)
    br = breadth(df)
    zones = zone_map(zones_df)
    sp = spikes(ratio_df)
    oi_inc = oi_table(eod.get("map") or {}, ratio_df, zones, fno, "inc")
    oi_dec = oi_table(eod.get("map") or {}, ratio_df, zones, fno, "dec")
    mood, mood_reason = market_mood(br, oi_inc, oi_dec, len(sp))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("F&O breadth (up / total)",
              f"{br['up']} / {br['total']}" if br["total"] else "—",
              f"{br['pct_up']}% up" if br["pct_up"] is not None else None)
    m2.metric("F&O average move", f"{br['avg_chg']}%" if br["avg_chg"] is not None else "—")
    m3.metric("Volume spikes (≥1.5x)", str(len(sp)) if frac is not None else "—",
              help="Time-adjusted: aaj ka volume / (20-din avg × session ka beeta hissa)")
    m4.metric("F&O mood", mood, help=mood_reason)
    st.caption(f"Mood ka hisaab: {mood_reason}")

    if frac is None:
        st.info("Pre-market: aaj ka volume abhi bana nahi hai - volume spike tab dikhega jab market khulega.")

    t1, t2, t3, t4, t5, t6 = st.tabs([
        "📈 Top 10 Gainers / Losers", "⚡ Volume Spikes", "🔼 Top 10 OI Increase",
        "🔽 Top 10 OI Decrease", "🧭 Index Movers (F&O)", "🏢 Corporate Actions"])

    with t1:
        g, l = st.columns(2)
        with g:
            st.markdown("**🟢 Top 10 Gainers (F&O)**")
            _fmt_table(movers(df, "gain"), "Data nahi.")
        with l:
            st.markdown("**🔴 Top 10 Losers (F&O)**")
            _fmt_table(movers(df, "loss"), "Data nahi.")

    with t2:
        st.caption("Vol x = aaj ka volume ÷ (20-din average × session beeta hissa). 2x+ = strong, 1.5x+ = spike.")
        _fmt_table(sp, "Abhi koi time-adjusted volume spike nahi (ya pre-market hai).")

    with t3:
        st.caption(f"Futures OI sabse zyada badha (EOD {eod_date}). 'Read' me EOD OI signal + LIVE price + "
                   "LIVE volume spike + zone ek saath judte hain.")
        _fmt_table(oi_inc, "EOD F&O bhavcopy abhi available nahi (sham ~18:30 IST ke baad aata hai).")

    with t4:
        st.caption(f"Futures OI sabse zyada ghata (EOD {eod_date}). Short covering / long unwinding ka "
                   "matlab 'Read' column me.")
        _fmt_table(oi_dec, "EOD F&O bhavcopy abhi available nahi.")

    with t5:
        gi = fetch_index_groups("gain")
        li = fetch_index_groups("loss")
        if not gi and not li:
            st.caption("NSE MCP ne index-wise movers nahi diye (cm_get_live_gainers/losers).")
        else:
            g, l = st.columns(2)
            with g:
                st.markdown("**🟢 Index-wise F&O gainers**")
                _fmt_table(index_movers_table(gi, fno, "gain"), "Data nahi.")
            with l:
                st.markdown("**🔴 Index-wise F&O losers**")
                _fmt_table(index_movers_table(li, fno, "loss"), "Data nahi.")

    with t6:
        watch = list(dict.fromkeys(list(zones.keys()) + list(oi_inc.get("Symbol", [])) +
                                   list(oi_dec.get("Symbol", []))))
        watch = [s for s in watch if s in set(fno)][:60]
        st.caption("Corporate actions sirf un F&O stocks ke liye jo zones ya top-OI list me hain "
                   "(ex-date: pichhle 2 din se agle 14 din tak).")
        if not watch:
            st.caption("Watchlist khaali hai.")
        else:
            with st.spinner("Corporate actions..."):
                raw = fetch_corp(tuple(watch))
            _fmt_table(corp_actions_table(raw), "Is window me koi corporate action nahi mila.")

    with st.expander("📖 Ye sab kaise padhein (simple guide)"):
        st.markdown(
            "- **Fut OI Δ %**: futures ka open interest (kitne contracts khule hain) kitna badla. OI badha = naye positions aaye.\n"
            "- **Long build-up** (price ↑ + OI ↑): buyers naye aa rahe hain - trend ke saath.\n"
            "- **Short build-up** (price ↓ + OI ↑): sellers naye aa rahe hain - girawat ka signal.\n"
            "- **Short covering** (price ↑ + OI ↓): sellers ne position band ki - rally kamzor ho sakti hai.\n"
            "- **Long unwinding** (price ↓ + OI ↓): buyers ne position chhodi - kamzori.\n"
            "- **Vol x (time-adj)**: aaj ka volume us waqt tak ke 'normal' se kitna guna. Subah ka 2x aur din ke ant ka 2x alag hota hai, isliye time-adjust karte hain.\n"
            "- **Zone**: aapke scanner ka active zone kitna door hai. Zone + OI signal + volume ek saath mile to context mazboot.\n"
            "- **Corporate action**: bonus/split par purane price levels bekaar ho jaate hain; dividend par chhota gap.\n"
            "- **Limit**: NSE MCP live data 1-3 min late hai; OI EOD hai; time-adjusted volume ek approximation hai (volume din me U-shape chalta hai)."
        )
