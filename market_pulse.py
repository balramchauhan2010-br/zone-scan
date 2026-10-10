"""
market_pulse.py — AI Trader Pulse (Senior Demand & Supply Trader Edition)
=========================================================================
Ye module zone-scan app me "trader ka daily briefing" add karta hai. Sirf
price-action zones se aage badhkar, ek senior D&S trader jo data dekhta hai:

  1. DELIVERY % (aaj vs pichhla din)      — NSE CM bhavcopy se (accumulation/distribution)
  2. BREADTH  (% F&O futures stocks up)   — NSE FO bhavcopy (FUTSTK) se
  3. OPTION OI signal                      — NSE option-chain API (PCR, max pain,
                                             support/resistance, put/call writing)
                                             + FO bhavcopy OI (long/short buildup)
  4. FII/DII                               — fii_dii_fetcher (NSE API, free)
  5. VOLUME + PRICE                        — bhavcopy volume vs yesterday
  6. GLOBAL cues + BHARATIYA/GLOBAL NEWS   — world indices + macro calendar + news
  7. AI SHORT SUMMARY (Hinglish)           — sab data ka fusion + matlab + forecast
  8. TOP 10 BUY / TOP 10 SELL              — zone + delivery + OI + volume + FII
                                             + global + news ka composite score
  9. PRE-MARKET / POST-MARKET sections     — market phase ke hisaab se briefing

Sab kuch FREE sources (NSE bhavcopy zip + NSE option chain + NSE FII API),
bina kisi API key ke. Har network call defensive hai — kuch fail ho to app
kabhi nahi rukega, bas "—" dikhayega. Gemini key ho to AI summary enhance
ho sakti hai (optional button).

Data source details:
- CM bhavcopy: https://archives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
- FO bhavcopy: https://archives.nseindia.com/content/historical/FNO/YYYY/MON/foDDMONYYYYbhav.csv.zip
- Option chain: https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
                https://www.nseindia.com/api/option-chain-equities?symbol=RELIANCE
- FII/DII:      https://www.nseindia.com/api/fiidiiTradeReact (via fii_dii_fetcher)

Bhavcopy usually NSE ~18:30-19:00 IST ke baad publish karta hai, isliye
"aaj ka" delivery data sham ko hi milta hai. Pre-market me ye "pichhla trading
day vs usse pehle wala din" dikhata hai (overnight positioning) — dono cases
me date labels clearly dikhte hain.
"""
from __future__ import annotations

import datetime as dt
import io
import time
import zipfile
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st

import candle_clock as cc

IST = "Asia/Kolkata"

# ------------------------------------------------------------------ helpers

_BHAV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_BHAV_HOSTS = [
    "https://archives.nseindia.com",
    "https://www.nseindia.com",
    "https://nsearchives.nseindia.com",
]

_NSE_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

GREEN, RED, YELLOW, GREY, BLUE = "#16c784", "#ea3943", "#f0b90b", "#8b8b8b", "#00bfff"


def _norm(name) -> str:
    """Column-name normaliser: 'Total Traded Qty' -> 'totaltradedqty'."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _find_col(df: pd.DataFrame, needles, exclude=()):
    """First column whose NORMALISED name contains any needle (and no exclude needle)."""
    if df is None or df.empty:
        return None
    for c in df.columns:
        n = _norm(c)
        if any(nd in n for nd in needles) and not any(ex in n for ex in exclude):
            return c
    return None


def _fnum(x):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None


# Tape + Trader Pulse chips ek hi flex block me (ek hi "table" jaisa strip)
TAPE_BLOCK_OPEN = '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:2px;">'


def _chip(label: str, value_html: str, color: str) -> str:
    return (f'<span style="background:{color}22;border:1px solid {color};border-radius:6px;'
            f'padding:4px 10px;margin:3px;display:inline-block;font-size:13px;color:#eaeaea;white-space:nowrap;">'
            f'<b>{label}</b> {value_html}</span>')


def _bias_color(bias_en: str) -> str:
    if "bull" in (bias_en or "").lower():
        return GREEN
    if "bear" in (bias_en or "").lower():
        return RED
    return YELLOW


# ------------------------------------------------------- bhavcopy download

# NSE ne 08-Jul-2024 se FO (aur CM) bhavcopy UDiff format me switch ki
_UDIFF_START = dt.date(2024, 7, 8)


def _cm_full_urls(d: dt.date) -> List[str]:
    """sec_bhavdata_full — plain CSV with OHLC + TTL_TRD_QNTY + DELIV_QTY + DELIV_PER.
    Delivery % ka sabse authoritative source (CM bhavcopy me delivery columns
    era ke hisaab se alag hote hain, ye file hamesha me complete hoti hai)."""
    fname = f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
    return [h + "/products/content/" + fname for h in _BHAV_HOSTS]


def _cm_legacy_urls(d: dt.date) -> List[str]:
    """Old CM bhavcopy zip (works post-2016; column names vary by era)."""
    mon = d.strftime("%b").upper()
    fname = f"cm{d.strftime('%d')}{mon}{d.year}bhav.csv.zip"
    return [h + f"/content/historical/EQUITIES/{d.year}/{mon}/{fname}" for h in _BHAV_HOSTS]


def _cm_udiff_urls(d: dt.date) -> List[str]:
    """UDiff CM bhavcopy zip (>= Jul 2024)."""
    fname = f"BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"
    return [h + "/content/cm/" + fname for h in _BHAV_HOSTS]


def _fo_legacy_urls(d: dt.date) -> List[str]:
    """Old FO bhavcopy zip — path DERIVATIVES hai (FNO nahi)."""
    mon = d.strftime("%b").upper()
    fname = f"fo{d.strftime('%d')}{mon}{d.year}bhav.csv.zip"
    paths = [f"/content/historical/DERIVATIVES/{d.year}/{mon}/{fname}",
             f"/content/historical/FNO/{d.year}/{mon}/{fname}"]
    return [h + p for h in _BHAV_HOSTS for p in paths]


def _fo_udiff_urls(d: dt.date) -> List[str]:
    """UDiff FO bhavcopy zip (>= Jul 2024) — different columns (TckrSymb, OpnIntrst...)."""
    fname = f"BhavCopy_NSE_FO_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"
    return [h + "/content/fo/" + fname for h in _BHAV_HOSTS]


def _fo_daily_reports_api(d: dt.date) -> Optional[bytes]:
    """daily-reports API fallback (sirf current/previous trading day ke liye).
    GET /api/daily-reports?key=FO -> fileKey 'FO-UDIFF-BHAVCOPY-CSV' -> download."""
    try:
        s = requests.Session()
        s.headers.update(_NSE_API_HEADERS)
        s.get("https://www.nseindia.com/", timeout=8)
        time.sleep(0.3)
        r = s.get("https://www.nseindia.com/api/daily-reports", params={"key": "FO"}, timeout=10)
        data = r.json()
        want = d.strftime("%d-%b-%Y")
        for day_list in (data.get("CurrentDay", []), data.get("PreviousDay", [])):
            for item in day_list:
                if item.get("fileKey") == "FO-UDIFF-BHAVCOPY-CSV" and item.get("tradingDate") == want:
                    url = f"{item.get('filePath', '')}{item.get('fileActlName', '')}"
                    rr = s.get(url, timeout=15)
                    if rr.status_code == 200 and rr.content:
                        return rr.content
        return None
    except Exception as e:
        print(f"FO daily-reports API error: {e}")
        return None


def _fetch_first_ok(urls: List[str], timeout: int = 12) -> Tuple[Optional[bytes], str]:
    """Returns (content, status). status: 'ok' | '404' | 'netfail'."""
    saw_404 = False
    for u in urls:
        try:
            r = requests.get(u, headers=_BHAV_HEADERS, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r.content, "ok"
            if r.status_code == 404:
                saw_404 = True
                continue
        except requests.exceptions.RequestException:
            continue
    return None, ("404" if saw_404 else "netfail")


def _read_bhav_csv(content: bytes) -> Optional[pd.DataFrame]:
    """Zip ya plain CSV dono handle karta hai. HTML error page ('<' se start) reject."""
    if not content or content[:1] == b"<":
        return None
    try:
        if content[:2] == b"PK":  # zip
            zf = zipfile.ZipFile(io.BytesIO(content))
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                return None
            content = zf.read(names[0])
        try:
            return pd.read_csv(io.BytesIO(content), encoding="utf-8", skipinitialspace=True)
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(content), encoding="latin-1", skipinitialspace=True)
    except Exception as e:
        print(f"bhavcopy read error: {e}")
        return None


def _cm_df_for_date(d: dt.date) -> Optional[pd.DataFrame]:
    """Ek date ka CM data — pehle sec_bhavdata_full (delivery ke saath), phir
    legacy CM bhavcopy zip, phir UDiff CM zip."""
    for urls in (_cm_full_urls(d), _cm_legacy_urls(d), _cm_udiff_urls(d)):
        content, status = _fetch_first_ok(urls)
        if status == "netfail":
            return None  # network hi down hai — doosre source ka fayda nahi
        if status == "ok" and content:
            df = _read_bhav_csv(content)
            if df is not None and not df.empty:
                return df
    return None


def _fo_df_for_date(d: dt.date) -> Optional[pd.DataFrame]:
    """Ek date ka FO data — UDiff-era me pehle UDiff zip, phir legacy DERIVATIVES
    zip, phir daily-reports API. Purani dates me legacy pehle."""
    order = [_fo_udiff_urls, _fo_legacy_urls] if d >= _UDIFF_START else [_fo_legacy_urls, _fo_udiff_urls]
    for url_fn in order:
        content, status = _fetch_first_ok(url_fn(d))
        if status == "netfail":
            break
        if status == "ok" and content:
            df = _read_bhav_csv(content)
            if df is not None and not df.empty:
                return df
    if d >= _UDIFF_START:
        content = _fo_daily_reports_api(d)
        if content:
            df = _read_bhav_csv(content)
            if df is not None and not df.empty:
                return df
    return None


def _walk_back_bhavcopy(kind: str, max_back: int = 8) -> Tuple[Optional[pd.DataFrame], str, str]:
    """Aaj se peeche trading days try karo jab tak bhavcopy mil jaye.
    kind: 'cm' ya 'fo'. Returns (df, date_iso, status). Network down ho to jaldi laut aata hai."""
    fetcher = _cm_df_for_date if kind == "cm" else _fo_df_for_date
    today = cc.now_ist().date()
    d = today
    for _ in range(max_back):
        if cc.is_trading_day(d):
            df = fetcher(d)
            if df is not None:
                return df, d.isoformat(), "ok"
            # 404 tha (abhi publish nahi hua) — ek aur peeche jao;
            # agar network bilkul down ho to fetcher None dega, loop chalega
            # lekin har date par sirf ek-ek request jaata hai toh fast rehta hai
        d -= dt.timedelta(days=1)
    fallback = cc.last_trading_day_on_or_before(today)
    return None, fallback.isoformat(), "not_found"


# ------------------------------------------------------- bhavcopy parsers

def _parse_cm_bhavcopy(raw: Optional[pd.DataFrame]) -> Dict[str, dict]:
    """CM data -> {SYMBOL: {close, prev_close, chg_pct, qty, deliv_qty, deliv_pct}}.
    teen formats handle karta hai:
      - sec_bhavdata_full: SYMBOL, SERIES, CLOSE_PRICE, PREV_CLOSE, TTL_TRD_QNTY, DELIV_QTY, DELIV_PER
      - legacy CM bhavcopy: 'Close Price', 'Total Traded Quantity', 'Deliverable Qty', '% Deli. Qty...'
      - UDiff CM: TckrSymb, SctySrs, ClsPric, PrvsClsgPric, TtlTradgVol"""
    if raw is None or raw.empty:
        return {}
    c_sym = _find_col(raw, ["symbol", "tckrsymb"])
    if c_sym is None:
        return {}
    c_ser = _find_col(raw, ["series", "sctysrs"])
    c_close = (_find_col(raw, ["closeprice", "clsgpric", "clspric"], exclude=["prv", "open", "high", "low", "last", "avg", "settle"])
               or _find_col(raw, ["close"], exclude=["prv", "open", "high", "low", "last", "avg", "settle"]))
    c_prev = _find_col(raw, ["prevclose", "prvsclsgpric", "prvsclsngpric"]) or _find_col(raw, ["prv"])
    c_qty = (_find_col(raw, ["ttltrdqnty", "totaltradedquantity", "tottrdqty", "tottrdqnty"])
             or _find_col(raw, ["ttltrdgvol", "totaltradedvolume", "tottrdvol"])
             or _find_col(raw, ["tradedqty", "trdqty", "trdgvol", "trdvol"]))
    c_dq = _find_col(raw, ["delivqty", "delivqnty", "deliverableqty"]) or _find_col(raw, ["deliverable"])
    c_dp = _find_col(raw, ["%deli", "delivper", "deliverpct", "deliverypct", "delipct",
                           "pctdeli", "deliqtytotraded", "%deliv", "deliverypc", "delipc"])

    df = raw.copy()
    if c_ser is not None:
        vals = df[c_ser].astype(str).str.upper().str.strip()
        if "EQ" in set(vals.unique()):
            df = df[vals == "EQ"]
    if df.empty:
        return {}

    out: Dict[str, dict] = {}
    for _, r in df.iterrows():
        sym = str(r[c_sym]).upper().strip()
        if not sym:
            continue
        close = _fnum(r.get(c_close)) if c_close else None
        prev = _fnum(r.get(c_prev)) if c_prev else None
        qty = _fnum(r.get(c_qty)) if c_qty else None
        dq = _fnum(r.get(c_dq)) if c_dq else None
        dp = _fnum(r.get(c_dp)) if c_dp else None
        if dp is None and dq is not None and qty:
            dp = dq / qty * 100.0
        chg = ((close / prev) - 1.0) * 100.0 if (close and prev) else None
        out[sym] = {
            "close": close, "prev_close": prev, "chg_pct": chg,
            "qty": qty, "deliv_qty": dq, "deliv_pct": dp,
        }
    return out


def _oi_signal(chg_pct, fut_oi_chg_pct, ce_chg, pe_chg):
    """Classic 4-way OI buildup signal + option-writing fallback."""
    if fut_oi_chg_pct is not None:
        up = chg_pct is not None and chg_pct > 0.1
        down = chg_pct is not None and chg_pct < -0.1
        oi_up = fut_oi_chg_pct > 0.5
        oi_dn = fut_oi_chg_pct < -0.5
        if up and oi_up:
            return "Long Buildup 🟢", "long_buildup"
        if down and oi_up:
            return "Short Buildup 🔴", "short_buildup"
        if up and oi_dn:
            return "Short Covering 🟢", "short_covering"
        if down and oi_dn:
            return "Long Unwinding 🔴", "long_unwinding"
    if ce_chg is not None and pe_chg is not None:
        if pe_chg > 0 and pe_chg > ce_chg:
            return "Put Writing 🟢", "put_writing"
        if ce_chg > 0 and ce_chg > pe_chg:
            return "Call Writing 🔴", "call_writing"
    return "Neutral ⚪", "neutral"


def oi_why(p: Optional[dict] = None, short: bool = False) -> str:
    """OI सिग्नल के पीछे का कारण - सिर्फ label नहीं, drivers (price/OI/delivery/PCR
    के numbers) + trader-interpretation के साथ. short=True -> table column के लिए compact."""
    if not p:
        return "—" if short else "OI/delivery data N/A (bhavcopy pending)"
    en = str(p.get("oi_signal_en") or "neutral")
    chg = p.get("chg_pct")
    oi = p.get("fut_oi_chg_pct")
    pcr = p.get("pcr")
    d1p = p.get("deliv_pct")
    dchg = p.get("deliv_chg_pp")
    pr = f"{chg:+.1f}%" if chg is not None else "—"
    orr = f"{oi:+.1f}%" if oi is not None else "—"
    pc = f"PCR {pcr:.2f}" if pcr else "PCR —"
    dv = f"{d1p:.0f}%" if d1p is not None else "—"

    if en == "long_buildup":
        if short:
            return f"नया लॉन्ग पैसा (P {pr}, OI {orr})"
        return (f"नया लॉन्ग पैसा: price {pr} + OI {orr} दोनों बढ़े = traders positions बना कर बैठे हैं, यही असली ताकत है. "
                f"Delivery {dv} ({'होल्डिंग पर भरोसा बढ़ा' if (dchg or 0) > 0 else 'delivery में कमी - profit-booking आ सकती है'}). {pc}. "
                f"⚠️ OI ज़्यादा बढ़ा है तो leveraged positions की उलट-गिनती भी तेज़ हो सकती है.")
    if en == "short_covering":
        if short:
            return f"शॉर्ट कवरिंग = कमज़ोर तेज़ी (P {pr}, OI {orr})"
        return (f"कमज़ोर तेज़ी: price {pr} बढ़ा पर OI {orr} घटा = नई खरीद नहीं, shorts बस कवर कर रहे हैं. "
                f"ऐसी रैली resistance पर अक्सर थम जाती है (shorts फिर बनते हैं). Delivery {dv}. {pc}. "
                f"👉 Entry से पहले देखें कि delivery + volume भी साथ बढ़ रहा है या नहीं.")
    if en == "short_buildup":
        if short:
            return f"नए shorts बन रहे (P {pr}, OI {orr})"
        return (f"नए shorts: price {pr} + OI {orr} बढ़ा = sellers aggressive, positions बना कर गिरावट का इंतज़ार. "
                f"Support टूटा तो short-add से और गिरेगा. Delivery {dv} (कम delivery = आज के खरीदार भी डे-ट्रेडर). {pc}.")
    if en == "long_unwinding":
        if short:
            return f"लॉन्ग निकासी (P {pr}, OI {orr})"
        return (f"लॉन्ग निकासी: price {pr} + OI {orr} घटा = longs बेच कर निकल रहे हैं (असली बिकवाली). "
                f"OI का घटना = forced exits खत्म होने की तरफ इशारा - selling की गति धीमी पड़ सकती है. Delivery {dv}. {pc}.")
    if en == "put_writing":
        if short:
            return f"Put writing = support (P {pr})"
        return f"Put writing: price लगभग flat ({pr}) पर put OI बढ़ा = premium sellers को support दिख रहा है (बुलिश दांव). {pc}."
    if en == "call_writing":
        if short:
            return f"Call writing = resistance (P {pr})"
        return f"Call writing: price लगभग flat ({pr}) पर call OI बढ़ा = premium sellers ऊपर resistance बना रहे हैं (बेयरिश दांव). {pc}."
    if short:
        return "साफ़ सिग्नल नहीं"
    return f"साफ़ सिग्नल नहीं: price {pr}, OI {orr} दोनों flat = न नया पैसा, न कवरिंग. ऐसे zones में OI confirmation का इंतज़ार करें. {pc}."


# Legacy FO bhavcopy INSTRUMENT values + UDiff (>= Jul 2024) FinInstrmTp values — dono
_FUT_INSTRUMENTS = {"FUTIDX", "FUTSTK", "FUTIVX", "FUTCOM", "FUTIRC", "FUTIRT", "FUTBLK",
                    "IDF", "STF", "FUT"}
_OPT_INSTRUMENTS = {"OPTIDX", "OPTSTK", "OPTIVX", "OPTCOM", "OPTIRC", "OPTIRT", "OPTBLK",
                    "IDO", "STO", "OPT"}
# Stock futures (breadth ke liye): legacy FUTSTK + UDiff STF
_STK_FUT_INSTRUMENTS = {"FUTSTK", "STF"}


def _parse_fo_bhavcopy(raw: Optional[pd.DataFrame]) -> dict:
    """FO bhavcopy -> {'map': {SYM: {...}}, 'breadth': {...}}.

    map entry: fut close/chg/qty/OI + option aggregates (CE/PE OI, chg OI, vol)
    + PCR + 4-way OI signal. breadth: stock-futures advancers/decliners (jab
    prev close available ho — UDiff me hota hai, legacy me nahi).

    Do formats handle karta hai:
      - Legacy (pre Jul-2024): INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP,
        OPEN..CLOSE, SETTLE_PR, CONTRACTS, OPEN_INT, CHG_IN_OI  (no prev close)
      - UDiff (>= Jul-2024): FinInstrmTp (IDF/IDO/STF/STO), TckrSymb, XpryDt, StrkPric,
        OptnTp, ClsPric, PrvsClsgPric, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTradgVol"""
    empty = {"map": {}, "breadth": {"up": 0, "down": 0, "flat": 0, "total": 0, "pct_up": 0.0, "source": "none"}}
    if raw is None or raw.empty:
        return empty
    c_sym = _find_col(raw, ["symbol", "tckrsymb"])
    c_ser = _find_col(raw, ["instrument", "fininstrmtp", "series"])
    if c_sym is None or c_ser is None:
        return empty
    c_close = (_find_col(raw, ["clsgpric", "clspric", "closeprice", "sttlmpric", "settlepr"],
                         exclude=["prv", "open", "high", "low", "last"])
               or _find_col(raw, ["close"], exclude=["prv", "open", "high", "low", "last"]))
    c_prev = _find_col(raw, ["prvsclsgpric", "prvsclsngpric", "prevclose"]) or _find_col(raw, ["prv"])
    c_qty = (_find_col(raw, ["tottrdqty", "tottrdqnty", "ttltrdgvol"])
             or _find_col(raw, ["contracts", "tottrdvol", "trdvol", "tradedqty"]))
    c_oi = (_find_col(raw, ["openint", "opnintrst", "openinterest", "openintrst", "totaloi"])
            or _find_col(raw, ["oi"], exclude=["point", "oil"]))
    c_chg = (_find_col(raw, ["chngopenint", "chnginopnintrst", "chginoi", "chgoi", "changeinoi", "chngintrst"])
             or _find_col(raw, ["chg"], exclude=["chgprice"]))
    c_strike = _find_col(raw, ["strikepr", "strkpric", "strikeprice"])
    c_otype = _find_col(raw, ["optiontyp", "optiontp", "optntp", "optiontype"])

    df = raw.copy()
    df["_sym"] = df[c_sym].astype(str).str.upper().str.strip()
    df["_ser"] = df[c_ser].astype(str).str.upper().str.strip()
    for c in (c_close, c_prev, c_qty, c_oi, c_chg):
        if c is not None:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---------- futures rows ----------
    fut = df[df["_ser"].isin(_FUT_INSTRUMENTS)].copy()
    fut_map: Dict[str, dict] = {}
    if not fut.empty and c_oi is not None:
        fut = fut.sort_values(c_oi, ascending=False)  # current-month (max OI) pehle
        for sym, grp in fut.groupby("_sym"):
            r = grp.iloc[0]
            close, prev = r.get(c_close), r.get(c_prev)
            chg = ((close / prev) - 1.0) * 100.0 if (close is not None and prev is not None
                                                     and pd.notna(close) and pd.notna(prev) and prev) else None
            oi = _fnum(r.get(c_oi))
            chg_oi = _fnum(r.get(c_chg)) if c_chg is not None else None
            prev_oi = (oi - chg_oi) if (oi is not None and chg_oi is not None) else None
            oi_chg_pct = (chg_oi / prev_oi * 100.0) if (chg_oi is not None and prev_oi) else None
            fut_map[sym] = {
                "chg_pct": chg,
                "fut_close": _fnum(close) if close is not None and pd.notna(close) else None,
                "fut_prev_close": _fnum(prev) if prev is not None and pd.notna(prev) else None,
                "fut_qty": _fnum(r.get(c_qty)) if c_qty else None,
                "fut_oi": oi, "fut_oi_chg": chg_oi, "fut_oi_chg_pct": oi_chg_pct,
            }

    # ---------- option rows (aggregate CE/PE per symbol) ----------
    opt = df[df["_ser"].isin(_OPT_INSTRUMENTS)].copy()
    opt_map: Dict[str, dict] = {}
    if not opt.empty and c_oi is not None:
        is_ce = opt[c_otype].astype(str).str.upper().str.strip() == "CE" if c_otype else pd.Series(False, index=opt.index)
        is_pe = opt[c_otype].astype(str).str.upper().str.strip() == "PE" if c_otype else pd.Series(False, index=opt.index)
        opt["_ce_oi"] = np.where(is_ce, opt[c_oi].fillna(0), 0.0)
        opt["_pe_oi"] = np.where(is_pe, opt[c_oi].fillna(0), 0.0)
        if c_chg is not None:
            opt["_ce_chg"] = np.where(is_ce, opt[c_chg].fillna(0), 0.0)
            opt["_pe_chg"] = np.where(is_pe, opt[c_chg].fillna(0), 0.0)
        else:
            opt["_ce_chg"] = 0.0
            opt["_pe_chg"] = 0.0
        vol_col = c_qty
        if vol_col is not None:
            opt["_ce_vol"] = np.where(is_ce, opt[vol_col].fillna(0), 0.0)
            opt["_pe_vol"] = np.where(is_pe, opt[vol_col].fillna(0), 0.0)
        else:
            opt["_ce_vol"] = 0.0
            opt["_pe_vol"] = 0.0
        agg = opt.groupby("_sym").agg(
            ce_oi=("_ce_oi", "sum"), pe_oi=("_pe_oi", "sum"),
            ce_chg_oi=("_ce_chg", "sum"), pe_chg_oi=("_pe_chg", "sum"),
            ce_vol=("_ce_vol", "sum"), pe_vol=("_pe_vol", "sum"),
        )
        for sym, r in agg.iterrows():
            opt_map[sym] = {k: float(v) for k, v in r.items()}

    # ---------- merge ----------
    fno_map: Dict[str, dict] = {}
    for sym in set(fut_map) | set(opt_map):
        f = fut_map.get(sym, {})
        o = opt_map.get(sym, {})
        ce_oi, pe_oi = o.get("ce_oi", 0.0), o.get("pe_oi", 0.0)
        ce_chg, pe_chg = o.get("ce_chg_oi", 0.0), o.get("pe_chg_oi", 0.0)
        pcr = (pe_oi / ce_oi) if ce_oi else None
        sig, sig_en = _oi_signal(f.get("chg_pct"), f.get("fut_oi_chg_pct"), ce_chg, pe_chg)
        entry = dict(f)
        entry.update({
            "ce_oi": ce_oi, "pe_oi": pe_oi, "ce_chg_oi": ce_chg, "pe_chg_oi": pe_chg,
            "ce_vol": o.get("ce_vol", 0.0), "pe_vol": o.get("pe_vol", 0.0),
            "pcr": pcr, "oi_signal": sig, "oi_signal_en": sig_en,
        })
        fno_map[sym] = entry

    # ---------- breadth (stock futures = FUTSTK/STF; UDiff me prev close hota hai) ----------
    breadth = {"up": 0, "down": 0, "flat": 0, "total": 0, "pct_up": 0.0, "source": "none"}
    futstk = df[df["_ser"].isin(_STK_FUT_INSTRUMENTS)]
    if not futstk.empty and c_close is not None and c_prev is not None:
        up = down = flat = 0
        for _, r in futstk.iterrows():
            close, prev = r.get(c_close), r.get(c_prev)
            if close is None or prev is None or pd.isna(close) or pd.isna(prev) or not prev:
                continue
            chg = (close / prev - 1.0) * 100.0
            if chg > 0.05:
                up += 1
            elif chg < -0.05:
                down += 1
            else:
                flat += 1
        total = up + down + flat
        breadth = {
            "up": up, "down": down, "flat": flat, "total": total,
            "pct_up": (up / total * 100.0) if total else 0.0,
            "pct_down": (down / total * 100.0) if total else 0.0,
            "source": "fo_bhavcopy",
        }
    return {"map": fno_map, "breadth": breadth}


# ------------------------------------------- cached bhavcopy accessors

@st.cache_data(show_spinner=False, ttl=1800)
def _cm_auto() -> Tuple[Dict[str, dict], str]:
    """Latest available CM bhavcopy map + uski date (aaj ki file na mile to peeche walk-back)."""
    df, d_iso, status = _walk_back_bhavcopy("cm")
    if df is None:
        print(f"CM bhavcopy not available (status={status}, date tried={d_iso})")
        return {}, d_iso
    return _parse_cm_bhavcopy(df), d_iso


@st.cache_data(show_spinner=False, ttl=1800)
def _cm_for(date_str: str) -> Dict[str, dict]:
    """Ek specific date ki CM data (previous trading day ke liye)."""
    try:
        d = dt.date.fromisoformat(date_str)
    except Exception:
        return {}
    df = _cm_df_for_date(d)
    if df is None:
        return {}
    return _parse_cm_bhavcopy(df)


@st.cache_data(show_spinner=False, ttl=1800)
def _fo_auto() -> dict:
    """Latest available FO bhavcopy -> parsed map + breadth + date."""
    df, d_iso, status = _walk_back_bhavcopy("fo")
    if df is None:
        print(f"FO bhavcopy not available (status={status}, date tried={d_iso})")
        return {"map": {}, "breadth": {"up": 0, "down": 0, "flat": 0, "total": 0, "pct_up": 0.0, "source": "none"}, "date": d_iso}
    parsed = _parse_fo_bhavcopy(df)
    parsed["date"] = d_iso
    return parsed


# ------------------------------------------------------------- option chain

_OPTION_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def _fetch_option_chain_payload(symbol: str) -> dict:
    s = requests.Session()
    s.headers.update(_NSE_API_HEADERS)
    s.get("https://www.nseindia.com/", timeout=8)  # cookie warm-up
    time.sleep(0.4)
    if symbol in _OPTION_INDEX_UNDERLYINGS:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"
    r = s.get(url, headers={**_NSE_API_HEADERS, "Referer": "https://www.nseindia.com/option-chain"}, timeout=12)
    r.raise_for_status()
    return r.json()


def _max_pain(df: pd.DataFrame):
    """Classic max-pain strike (min total ITM option value at expiry)."""
    try:
        rows = df[["strike", "ce_oi", "pe_oi"]].dropna().values
        if not len(rows):
            return None
        strikes = sorted({float(s) for s, _, _ in rows})
        best_s, best_pain = None, None
        for S in strikes:
            pain = 0.0
            for K, ce, pe in rows:
                K = float(K)
                if K < S:
                    pain += float(ce) * (S - K)
                elif K > S:
                    pain += float(pe) * (K - S)
            if best_pain is None or pain < best_pain:
                best_pain, best_s = pain, S
        return float(best_s) if best_s is not None else None
    except Exception:
        return None


def parse_option_chain(payload: dict) -> dict:
    """NSE option-chain JSON -> PCR / max pain / support / resistance / signal."""
    rec = (payload or {}).get("records") or {}
    data = rec.get("data") or []
    if not data:
        return {}
    uv = _fnum(rec.get("underlyingValue"))
    expiries = [e for e in (rec.get("expiryDates") or []) if e]
    rows = []
    for item in data:
        strike = _fnum(item.get("strikePrice"))
        if strike is None:
            continue
        ce = item.get("CE") or {}
        pe = item.get("PE") or {}
        rows.append({
            "strike": strike,
            "expiry": item.get("expiryDate"),
            "ce_oi": _fnum(ce.get("openInterest")) or 0.0,
            "pe_oi": _fnum(pe.get("openInterest")) or 0.0,
            "ce_chg": _fnum(ce.get("changeinOpenInterest")) or 0.0,
            "pe_chg": _fnum(pe.get("changeinOpenInterest")) or 0.0,
            "ce_vol": _fnum(ce.get("totalTradedVolume")) or 0.0,
            "pe_vol": _fnum(pe.get("totalTradedVolume")) or 0.0,
        })
    df = pd.DataFrame(rows)
    ce_oi, pe_oi = float(df["ce_oi"].sum()), float(df["pe_oi"].sum())
    ce_chg, pe_chg = float(df["ce_chg"].sum()), float(df["pe_chg"].sum())
    ce_vol, pe_vol = float(df["ce_vol"].sum()), float(df["pe_vol"].sum())

    near = df
    if expiries and "expiry" in df.columns:
        cand = df[df["expiry"] == expiries[0]]
        if not cand.empty:
            near = cand
    max_pain = _max_pain(near)

    atm = sup = res = None
    if uv:
        atm = float(near.iloc[(near["strike"] - float(uv)).abs().argsort()]["strike"].iloc[0])
        below = near[near["strike"] <= atm].sort_values("pe_oi", ascending=False)
        above = near[near["strike"] >= atm].sort_values("ce_oi", ascending=False)
        if not below.empty:
            sup = float(below["strike"].iloc[0])
        if not above.empty:
            res = float(above["strike"].iloc[0])
        if sup is None:  # koi strike neeche nahi → overall max PE OI
            sup = float(near.sort_values("pe_oi", ascending=False)["strike"].iloc[0])
        if res is None:
            res = float(near.sort_values("ce_oi", ascending=False)["strike"].iloc[0])

    if pe_chg > 0 and pe_chg > ce_chg:
        sig, sig_en = "Put Writing 🟢 (support ban raha hai)", "put_writing"
    elif ce_chg > 0 and ce_chg > pe_chg:
        sig, sig_en = "Call Writing 🔴 (resistance ban raha hai)", "call_writing"
    elif pe_chg < 0 and ce_chg < 0:
        sig, sig_en = "OI Unwinding ⚪", "unwinding"
    else:
        sig, sig_en = "Neutral ⚪", "neutral"

    return {
        "underlying_value": uv,
        "pcr_oi": round(pe_oi / ce_oi, 2) if ce_oi else None,
        "pcr_vol": round(pe_vol / ce_vol, 2) if ce_vol else None,
        "ce_oi": int(ce_oi), "pe_oi": int(pe_oi),
        "ce_chg_oi": int(ce_chg), "pe_chg_oi": int(pe_chg),
        "max_pain": max_pain, "atm": atm, "support": sup, "resistance": res,
        "signal": sig, "signal_en": sig_en,
        "expiry": expiries[0] if expiries else None,
        "n_strikes": int(len(df)),
    }


@st.cache_data(show_spinner=False, ttl=900)
def get_option_chain_summary(symbol: str) -> dict:
    """Option chain summary for an index (NIFTY/BANKNIFTY) or a stock.
    NSE API fail ho to FO bhavcopy OI aggregates se fallback."""
    sym = str(symbol).upper().strip()
    try:
        out = parse_option_chain(_fetch_option_chain_payload(sym))
        if out:
            out["symbol"] = sym
            out["source"] = "nse_api"
            return out
    except Exception as e:
        print(f"Option chain API error ({sym}): {e}")
    # fallback: FO bhavcopy
    try:
        fo = _fo_auto()
        m = (fo.get("map") or {}).get(sym)
        if m and (m.get("ce_oi") or m.get("pe_oi")):
            pcr = m.get("pcr")
            return {
                "symbol": sym, "underlying_value": None,
                "pcr_oi": round(pcr, 2) if pcr else None, "pcr_vol": None,
                "ce_oi": int(m.get("ce_oi") or 0), "pe_oi": int(m.get("pe_oi") or 0),
                "ce_chg_oi": int(m.get("ce_chg_oi") or 0), "pe_chg_oi": int(m.get("pe_chg_oi") or 0),
                "max_pain": None, "atm": None, "support": None, "resistance": None,
                "signal": m.get("oi_signal", "—"), "signal_en": m.get("oi_signal_en", "neutral"),
                "source": "fo_bhavcopy",
            }
    except Exception as e:
        print(f"Option chain bhavcopy fallback error ({sym}): {e}")
    return {}


# ------------------------------------------------------- pulse map + tables

@st.cache_data(show_spinner=False, ttl=1800)
def get_pulse_map(tickers_tuple) -> Dict[str, dict]:
    """Per-symbol trader pulse: delivery %, Δdelivery (pp), volume ×, futures OI
    change, option PCR + 4-way OI signal. Keys = clean symbols (no .NS)."""
    tickers_tuple = tuple(tickers_tuple or ())
    cm1, d1s = _cm_auto()
    try:
        d1 = dt.date.fromisoformat(d1s)
        d2 = cc.previous_trading_day(d1)
        d2s = d2.isoformat()
    except Exception:
        d2s = ""
    cm2 = _cm_for(d2s) if d2s else {}
    fo = _fo_auto()
    fo_map = fo.get("map") or {}

    pulse: Dict[str, dict] = {}
    for t in tickers_tuple:
        clean = str(t).replace(".NS", "").upper().strip()
        if not clean:
            continue
        c1 = cm1.get(clean, {})
        c2 = cm2.get(clean, {})
        f = fo_map.get(clean, {})

        chg = f.get("chg_pct")
        if chg is None:
            chg = c1.get("chg_pct")

        d1p = c1.get("deliv_pct")
        if d1p is None and c1.get("deliv_qty") is not None and c1.get("qty"):
            d1p = c1["deliv_qty"] / c1["qty"] * 100.0
        d2p = c2.get("deliv_pct")
        if d2p is None and c2.get("deliv_qty") is not None and c2.get("qty"):
            d2p = c2["deliv_qty"] / c2["qty"] * 100.0
        dchg = (d1p - d2p) if (d1p is not None and d2p is not None) else None

        vol_x = None
        if c1.get("qty") and c2.get("qty"):
            vol_x = c1["qty"] / c2["qty"]

        pulse[clean] = {
            "symbol": clean,
            "chg_pct": round(chg, 2) if chg is not None else None,
            "deliv_pct": round(d1p, 1) if d1p is not None else None,
            "deliv_prev": round(d2p, 1) if d2p is not None else None,
            "deliv_chg_pp": round(dchg, 1) if dchg is not None else None,
            "vol_vs_yday": round(vol_x, 2) if vol_x else None,
            "fut_oi_chg_pct": round(f["fut_oi_chg_pct"], 2) if f.get("fut_oi_chg_pct") is not None else None,
            "pcr": round(f["pcr"], 2) if f.get("pcr") else None,
            "oi_signal": f.get("oi_signal", "—"),
            "oi_signal_en": f.get("oi_signal_en", "neutral"),
            "d1": d1s, "d2": d2s,
        }
    return pulse


@st.cache_data(show_spinner=False, ttl=1800)
def get_market_tables() -> dict:
    """Saare EOD tables ek saath (delivery gainers/losers, top gainers/losers,
    volume breakout, OI signals, breadth, delivery stats)."""
    cm1, d1s = _cm_auto()
    try:
        d1 = dt.date.fromisoformat(d1s)
        d2 = cc.previous_trading_day(d1)
        d2s = d2.isoformat()
    except Exception:
        d2s = ""
    cm2 = _cm_for(d2s) if d2s else {}
    fo = _fo_auto()
    fo_map = fo.get("map") or {}

    rows = []
    for sym in sorted(fo_map.keys()):
        c1 = cm1.get(sym, {})
        c2 = cm2.get(sym, {})
        f = fo_map.get(sym, {})
        chg = f.get("chg_pct")
        if chg is None:
            chg = c1.get("chg_pct")
        d1p = c1.get("deliv_pct")
        if d1p is None and c1.get("deliv_qty") is not None and c1.get("qty"):
            d1p = c1["deliv_qty"] / c1["qty"] * 100.0
        d2p = c2.get("deliv_pct")
        if d2p is None and c2.get("deliv_qty") is not None and c2.get("qty"):
            d2p = c2["deliv_qty"] / c2["qty"] * 100.0
        dchg = (d1p - d2p) if (d1p is not None and d2p is not None) else None
        vol_x = (c1["qty"] / c2["qty"]) if (c1.get("qty") and c2.get("qty")) else None
        rows.append({
            "Symbol": sym,
            "Chg %": round(chg, 2) if chg is not None else None,
            "Delivery %": round(d1p, 1) if d1p is not None else None,
            "Prev Deliv %": round(d2p, 1) if d2p is not None else None,
            "ΔDeliv pp": round(dchg, 1) if dchg is not None else None,
            "Vol ×": round(vol_x, 2) if vol_x else None,
            "OI Chg %": round(f["fut_oi_chg_pct"], 2) if f.get("fut_oi_chg_pct") is not None else None,
            "PCR": round(f["pcr"], 2) if f.get("pcr") else None,
            "OI Signal": f.get("oi_signal", "—"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        # bhavcopy nahi mila to bhi columns hone chahiye — warna dropna(subset=[...]) KeyError dega
        df = pd.DataFrame(columns=["Symbol", "Chg %", "Delivery %", "Prev Deliv %", "ΔDeliv pp",
                                   "Vol ×", "OI Chg %", "PCR", "OI Signal"])

    def _head(dfx, col, n=10, asc=False, tie=None):
        # tie = secondary sort column (deterministic order on equal values)
        d = dfx.dropna(subset=[col])
        if tie and tie in d.columns:
            return d.sort_values([col, tie], ascending=[asc, False]).head(n).reset_index(drop=True)
        return d.sort_values(col, ascending=asc).head(n).reset_index(drop=True)

    valid = df.dropna(subset=["Delivery %"])
    stats = {
        "avg_deliv_pct": round(float(valid["Delivery %"].mean()), 1) if not valid.empty else None,
        "avg_deliv_chg_pp": round(float(valid["ΔDeliv pp"].mean()), 1) if not valid.empty else None,
        "pct_deliv_up": round(float((valid["ΔDeliv pp"] > 0).mean() * 100), 1) if not valid.empty else 0.0,
        "pct_deliv_down": round(float((valid["ΔDeliv pp"] < 0).mean() * 100), 1) if not valid.empty else 0.0,
        "n": int(len(valid)),
    }
    oi_tab = df.dropna(subset=["OI Chg %"])
    oi_tab = oi_tab.reindex(oi_tab["OI Chg %"].abs().sort_values(ascending=False).index).head(15).reset_index(drop=True)
    vol_bo = df.dropna(subset=["Vol ×"])
    vol_bo = vol_bo[vol_bo["Vol ×"] >= 1.5].sort_values(["Vol ×", "Chg %"], ascending=[False, False]).head(10).reset_index(drop=True)

    return {
        "df": df,
        "delivery_gainers": _head(valid, "ΔDeliv pp", 10, asc=False, tie="Delivery %"),
        "delivery_decliners": _head(valid, "ΔDeliv pp", 10, asc=True, tie="Delivery %"),
        "top_gainers": _head(df, "Chg %", 10, asc=False, tie="Vol ×"),
        "top_losers": _head(df, "Chg %", 10, asc=True, tie="Vol ×"),
        "volume_breakout": vol_bo,
        "oi_signals": oi_tab,
        "delivery_stats": stats,
        "breadth": get_breadth(),
        "d1": d1s, "d2": d2s,
    }


@st.cache_data(show_spinner=False, ttl=1800)
def get_breadth() -> dict:
    """% of NSE F&O futures stocks that increased (last available EOD).

    Priority:
      1. FO bhavcopy breadth (UDiff era — FO file me prev close hota hai)
      2. CM (sec_bhavdata_full) chg% over F&O symbols — FO map ke keys, warna F&O list
         (legacy FO me prev close nahi hota, isliye CM chg sabse robust hai)
      3. Yahoo daily over the F&O universe (last resort)"""
    fo = _fo_auto()
    b = fo.get("breadth") or {}
    if b.get("total"):
        return b

    # ---- CM-based breadth over F&O symbols ----
    try:
        cm1, _d1s = _cm_auto()
        fo_syms = set((fo.get("map") or {}).keys())
        if not fo_syms:
            fo_syms = set(_fno_symbols_cached())
        up = down = flat = total = 0
        for sym in fo_syms:
            c = cm1.get(sym)
            if not c or c.get("chg_pct") is None:
                continue
            chg = c["chg_pct"]
            total += 1
            if chg > 0.05:
                up += 1
            elif chg < -0.05:
                down += 1
            else:
                flat += 1
        if total:
            return {
                "up": up, "down": down, "flat": flat, "total": total,
                "pct_up": (up / total * 100.0), "pct_down": (down / total * 100.0),
                "source": "sec_bhavdata_full",
            }
    except Exception as e:
        print(f"breadth CM-based error: {e}")

    # ---- Yahoo fallback ----
    try:
        from fno_universe import get_fno_symbols, to_yahoo_tickers
        import data_fetch
        symbols, _src = get_fno_symbols()
        raw = data_fetch.fetch_daily(to_yahoo_tickers(symbols))
        up = down = flat = 0
        for _sym, df in raw.items():
            if df is None or len(df) < 2:
                continue
            try:
                chg = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-2]) - 1.0) * 100.0
            except Exception:
                continue
            if chg > 0.05:
                up += 1
            elif chg < -0.05:
                down += 1
            else:
                flat += 1
        total = up + down + flat
        return {
            "up": up, "down": down, "flat": flat, "total": total,
            "pct_up": (up / total * 100.0) if total else 0.0,
            "pct_down": (down / total * 100.0) if total else 0.0,
            "source": "yahoo",
        }
    except Exception as e:
        print(f"breadth yahoo fallback error: {e}")
        return {"up": 0, "down": 0, "flat": 0, "total": 0, "pct_up": 0.0, "source": "none"}


@st.cache_data(show_spinner=False, ttl=300)
def get_live_breadth(tickers_tuple) -> dict:
    """Yahoo daily se live-ish breadth (market hours me kaam aata hai)."""
    res = {"up": 0, "down": 0, "flat": 0, "total": 0, "pct_up": 0.0, "source": "none"}
    try:
        import data_fetch
        raw = data_fetch.fetch_daily(list(tickers_tuple))
        up = down = flat = 0
        for _sym, df in raw.items():
            if df is None or len(df) < 2:
                continue
            try:
                chg = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-2]) - 1.0) * 100.0
            except Exception:
                continue
            if chg > 0.05:
                up += 1
            elif chg < -0.05:
                down += 1
            else:
                flat += 1
        total = up + down + flat
        res = {
            "up": up, "down": down, "flat": flat, "total": total,
            "pct_up": (up / total * 100.0) if total else 0.0,
            "pct_down": (down / total * 100.0) if total else 0.0,
            "source": "yahoo_live",
        }
    except Exception as e:
        print(f"live breadth error: {e}")
    return res


# ------------------------------------------------------------- context data

@st.cache_data(show_spinner=False, ttl=1800)
def get_fii_safe() -> dict:
    try:
        from fii_dii_fetcher import get_fii_dii_summary
        return get_fii_dii_summary()
    except Exception as e:
        print(f"FII safe error: {e}")
        return {"fii_net": 0, "dii_net": 0, "fii_trend": "Neutral", "dii_trend": "Neutral", "last_date": "N/A"}


@st.cache_data(show_spinner=False, ttl=300)
def get_global_bias() -> dict:
    """World indices (NSE API) se US/Asia/Europe bias + DXY/USDINR/Crude/Gold."""
    out = {"label": "N/A", "score": 0, "us": "—", "asia": "—", "europe": "—",
           "details": pd.DataFrame(), "dxy": None, "usdinr": None, "crude": None, "gold": None}
    try:
        from global_macro_fetcher import get_world_indices
        df = get_world_indices()
        if df is not None and not df.empty:
            out["details"] = df
            groups = {"US": [], "Asia": [], "Europe": []}
            for _, r in df.iterrows():
                name = str(r.get("index", "")).lower()
                pct = _fnum(r.get("percent")) or 0.0
                if any(k in name for k in ["dow", "nasdaq", "s&p", "sp 500", "sp500", "russell"]):
                    groups["US"].append(pct)
                elif any(k in name for k in ["nikkei", "hang seng", "shanghai", "kospi", "straits", "taiwan", "asx", "sgx"]):
                    groups["Asia"].append(pct)
                elif any(k in name for k in ["ftse", "dax", "cac", "euro", "stoxx"]):
                    groups["Europe"].append(pct)

            def _bias(vals):
                if not vals:
                    return "—", 0
                avg = sum(vals) / len(vals)
                lab = "🟢" if avg > 0 else "🔴" if avg < 0 else "➡️"
                return f"{lab} {avg:+.2f}%", (1 if avg > 0.15 else -1 if avg < -0.15 else 0)

            us_l, us_s = _bias(groups["US"])
            as_l, as_s = _bias(groups["Asia"])
            eu_l, eu_s = _bias(groups["Europe"])
            out["us"], out["asia"], out["europe"] = us_l, as_l, eu_l
            out["score"] = us_s + eu_s + int(round(as_s * 0.5))
            out["label"] = f"US {us_l} | Asia {as_l} | EU {eu_l}"
    except Exception as e:
        print(f"global bias error: {e}")
    try:
        import data_fetch
        import global_instruments as _gi
        _top_items = list(_gi.TOP_GLOBAL)
        q = data_fetch.fetch_market_watch_quotes(["DX-Y.NYB", "USDINR=X", "CL=F", "GC=F"] + _gi.top_global_yahoo())
        # AI summary ke liye current Top Global cues: {label: (last, chg_pct)}
        out["top"] = {it["label"]: q.get(it["yahoo"]) for it in _top_items if q.get(it["yahoo"])}
        out["dxy"] = q.get("DX-Y.NYB")
        out["usdinr"] = q.get("USDINR=X")
        out["crude"] = q.get("CL=F")
        out["gold"] = q.get("GC=F")
    except Exception as e:
        print(f"global commodities error: {e}")
    return out


@st.cache_data(show_spinner=False, ttl=300)
def get_news_sentiment(hours: int = 24) -> dict:
    res = {"bull": 0, "bear": 0, "neu": 0, "headlines": [], "bias_map": {}, "df": pd.DataFrame()}
    try:
        from powerful_news_fetcher import get_verified_news_with_gemini_layers
        df = get_verified_news_with_gemini_layers(hours=hours)
        if df is None or df.empty:
            return res
        res["df"] = df
        b = df["gemini_bias"].astype(str) if "gemini_bias" in df.columns else pd.Series(["Neutral"] * len(df))
        res["bull"] = int(b.str.contains("Bullish", case=False, na=False).sum())
        res["bear"] = int(b.str.contains("Bearish", case=False, na=False).sum())
        res["neu"] = int(len(df) - res["bull"] - res["bear"])
        for _, r in df.head(6).iterrows():
            res["headlines"].append({
                "symbol": str(r.get("symbol", "MARKET")),
                "title": str(r.get("title", ""))[:110],
                "bias": str(r.get("gemini_bias", "Neutral")),
            })
        for _, r in df.iterrows():
            s = str(r.get("symbol", "")).upper().strip()
            bb = str(r.get("gemini_bias", ""))
            if s and s not in ("MARKET", "NIFTY", "NIFTY 50", "BANKNIFTY", "BANK NIFTY", ""):
                res["bias_map"][s] = "Bullish" if "Bullish" in bb else "Bearish" if "Bearish" in bb else "Neutral"
    except Exception as e:
        print(f"news sentiment error: {e}")
    return res


@st.cache_data(show_spinner=False, ttl=600)
def get_macro_events() -> pd.DataFrame:
    try:
        from global_macro_fetcher import get_global_macro_news
        df = get_global_macro_news()
        if df is None:
            return pd.DataFrame()
        return df
    except Exception as e:
        print(f"macro events error: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=24 * 3600)
def _fno_symbols_cached() -> tuple:
    try:
        from fno_universe import get_fno_symbols
        symbols, _src = get_fno_symbols()
        return tuple(symbols)
    except Exception:
        return ()


# ------------------------------------------------------------- market phase

def get_market_phase(now: pd.Timestamp = None) -> dict:
    """pre_market (before 09:15) / open / post_market (after 15:30) / closed."""
    now = now or cc.now_ist()
    d = now.date()
    if not cc.is_trading_day(d):
        return {
            "phase": "closed", "label": "🔴 Market Band (Weekend/Holiday)", "date": str(d), "now": now,
            "tab_index": 0,
            "tab_note": "Aaj market band hai. Pre-market briefing me global cues, OI signal aur events dekh sakte ho.",
        }
    o = pd.Timestamp.combine(d, dt.time(9, 15)).tz_localize(IST)
    c = pd.Timestamp.combine(d, dt.time(15, 30)).tz_localize(IST)
    if now < o:
        return {
            "phase": "pre_market", "label": "🌅 Pre-Market", "date": str(d), "now": now,
            "tab_index": 0,
            "tab_note": f"Market abhi nahi khula (khulega {o.strftime('%H:%M')} IST). Ye aaj ka PRE-MARKET setup hai — global cues, overnight OI, delivery trend, aaj ke events aur Top 10 watchlist.",
        }
    if now < c:
        return {
            "phase": "open", "label": "⚡ Market Open (Live)", "date": str(d), "now": now,
            "tab_index": 1,
            "tab_note": "Market khul chuka hai — neeche wala section LIVE (so far) data dikhata hai. EOD bhavcopy sham ~18:30-19:00 ke baad aata hai.",
        }
    return {
        "phase": "post_market", "label": "🌇 Post-Market", "date": str(d), "now": now,
        "tab_index": 1,
        "tab_note": "Session band ho chuka hai. Ye POST-MARKET review hai — aaj ka delivery %, breadth %, OI signals, FII/DII aur kal ka forecast.",
    }


# ------------------------------------------------------------- AI summary

def generate_ai_summary(*, phase: str, breadth: dict, delivery_stats: dict,
                        nifty_opt: dict, banknifty_opt: dict, fii: dict,
                        glob: dict, news: dict, d1: str = "", d2: str = "") -> dict:
    """Rule-based AI jaisa short summary (Hinglish) — sab signals ka fusion.
    Gemini key ho to UI me ek button se ise aur gehra kiya ja sakta hai."""
    drivers: List[str] = []
    score = 0.0

    # ---- breadth ----
    if breadth and breadth.get("total"):
        pct = float(breadth.get("pct_up") or 0)
        if pct >= 55:
            score += 1.0
            drivers.append(f"Breadth mazboot — {breadth['up']}/{breadth['total']} F&O futures ({pct:.0f}%) groen")
        elif pct <= 45:
            score -= 1.0
            drivers.append(f"Breadth kamzor — sirf {pct:.0f}% futures groen, {breadth['down']} laal")
        else:
            drivers.append(f"Breadth mixed — {pct:.0f}% groen vs {100 - pct:.0f}% laal")

    # ---- delivery ----
    if delivery_stats and delivery_stats.get("n"):
        avg = float(delivery_stats.get("avg_deliv_chg_pp") or 0)
        up_share = float(delivery_stats.get("pct_deliv_up") or 0)
        avg_pct = delivery_stats.get("avg_deliv_pct")
        if avg >= 2:
            score += 1.0
            drivers.append(f"Delivery {avg:+.1f}pp badhi (avg {avg_pct:.0f}%) — accumulation, smart money khareed raha hai")
        elif avg <= -2:
            score -= 1.0
            drivers.append(f"Delivery {avg:+.1f}pp giri — distribution, log profit book kar rahe hain")
        else:
            drivers.append(f"Delivery {avg:+.1f}pp — normal day, na accumulation na distribution")
        drivers.append(f"{up_share:.0f}% stocks me delivery badhi vs {100 - up_share:.0f}% me giri")

    # ---- option OI ----
    for name, opt in (("NIFTY", nifty_opt), ("BANKNIFTY", banknifty_opt)):
        if opt and opt.get("pcr_oi"):
            pcr = float(opt["pcr_oi"])
            if pcr >= 1.1:
                score += 0.5
                drivers.append(f"{name} PCR {pcr:.2f} — put writing zyada, neeche support mazboot")
            elif pcr <= 0.9:
                score -= 0.5
                drivers.append(f"{name} PCR {pcr:.2f} — call writing zyada, upar resistance")
            else:
                drivers.append(f"{name} PCR {pcr:.2f} — santulit positioning")
            if opt.get("signal"):
                drivers.append(f"{name} OI signal: {opt['signal']}")

    # ---- FII/DII ----
    fii_net = float(fii.get("fii_net") or 0)
    dii_net = float(fii.get("dii_net") or 0)
    if fii_net > 0:
        score += 1.0
        drivers.append(f"FII net buying {fii_net:+.0f} Cr — foreign support hai")
    elif fii_net < 0:
        score -= 1.0
        drivers.append(f"FII net selling {fii_net:+.0f} Cr — foreign drag hai")
    if dii_net > 0 and fii_net < 0:
        drivers.append(f"DII buying {dii_net:+.0f} Cr — desi institutions ne FII selling sambhala")
    elif dii_net < 0 and fii_net > 0:
        drivers.append(f"DII selling {dii_net:+.0f} Cr — lekin FII zyada mazboot hain")

    # ---- top global cues (live, informational) ----
    top = (glob or {}).get("top") or {}
    cue_parts = []
    for lab in ("COPPER", "NATURAL GAS", "XAU/USD", "USD/JPY", "BITCOIN/USD"):
        v = top.get(lab)
        if isinstance(v, tuple) and len(v) == 2:
            cue_parts.append(f"{lab} {float(v[1]):+.2f}%")
    if cue_parts:
        drivers.append("Top global cues (live): " + " | ".join(cue_parts))

    # ---- global ----
    if glob:
        g = glob.get("score") or 0
        if g > 0:
            score += 0.75
            drivers.append(f"Global cues positive ({glob.get('label', '')})")
        elif g < 0:
            score -= 0.75
            drivers.append(f"Global cues negative ({glob.get('label', '')})")
        else:
            drivers.append(f"Global cues mixed ({glob.get('label', '')})")
        if isinstance(glob.get("usdinr"), tuple):
            u = glob["usdinr"][1]
            if u >= 0.3:
                score -= 0.25
                drivers.append(f"USD/INR {u:+.2f}% — rupee kamzor, FII ke liye negativo")
            elif u <= -0.3:
                score += 0.25
                drivers.append(f"USD/INR {u:+.2f}% — rupee mazboot, risk-on support")
        if isinstance(glob.get("crude"), tuple):
            c = glob["crude"][1]
            if c >= 1.0:
                score -= 0.25
                drivers.append(f"Crude {c:+.2f}% — mehnga tel, India ke liye inflation pressure")
            elif c <= -1.0:
                score += 0.25
                drivers.append(f"Crude {c:+.2f}% — tel sasta, India ke liye positive")

    # ---- news ----
    if news:
        nb = news.get("bull", 0) - news.get("bear", 0)
        if nb > 0:
            score += 0.5
            drivers.append(f"News sentiment positive ({news.get('bull', 0)} bullish vs {news.get('bear', 0)} bearish headlines)")
        elif nb < 0:
            score -= 0.5
            drivers.append(f"News sentiment negative ({news.get('bear', 0)} bearish vs {news.get('bull', 0)} bullish headlines)")

    # ---- bias ----
    if score >= 1.5:
        bias, bias_en = "Bullish 📈", "bullish"
    elif score <= -1.5:
        bias, bias_en = "Bearish 📉", "bearish"
    elif score > 0:
        bias, bias_en = "Mild Bullish 🟢", "mild_bullish"
    elif score < 0:
        bias, bias_en = "Mild Bearish 🔴", "mild_bearish"
    else:
        bias, bias_en = "Neutral ➡️", "neutral"
    confidence = "High" if abs(score) >= 2.5 else "Medium" if abs(score) >= 1.0 else "Low"

    dl = f" (data: {d1} vs {d2})" if d1 else ""
    if phase == "pre_market":
        summary = (f"🌅 Pre-Market AI Summary: Global cues + overnight data se aaj ka setup **{bias}** hai. "
                   f"{' | '.join(drivers[:4])}.")
        meaning = ("📖 Iska matlab: jab delivery %, OI buildup aur FII flow ek hi direction me hote hain, "
                   "to smart money usi taraf position bana raha hota hai — aaj ke session me usi side ka haath upar "
                   "rehne ki sambhavna zyada hai. Agar signals ek-doosre ke opposite hain to open volatile ho sakta hai.")
        forecast_bits = [f"🔮 Aaj ka forecast: {bias} open ki umeed."]
        if nifty_opt and nifty_opt.get("support") and nifty_opt.get("resistance"):
            forecast_bits.append(f"NIFTY {nifty_opt['support']:.0f} (support) / {nifty_opt['resistance']:.0f} (resistance) ke beech range sambhav — "
                                 f"max pain {nifty_opt['max_pain']:.0f} ke aas-paas closing ki sambhavna." if nifty_opt.get("max_pain") else
                                 f"NIFTY {nifty_opt['support']:.0f} support / {nifty_opt['resistance']:.0f} resistance.")
        if glob.get("us") and "🟢" in str(glob.get("us")):
            forecast_bits.append("US markets positive hain to gap-up open sambhav.")
        elif glob.get("us") and "🔴" in str(glob.get("us")):
            forecast_bits.append("US markets negative hain to gap-down ya flat open sambhav.")
        forecast = " ".join(forecast_bits)
    elif phase == "post_market":
        summary = (f"🌇 Post-Market AI Summary ({d1}): Aaj ka poora data — breadth, delivery, OI, FII/DII, global "
                   f"aur news — milakar bata raha hai ki aaj ka session **{bias}** tha. {' | '.join(drivers[:4])}.")
        meaning = ("📖 Iska matlab: aaj ke delivery %, volume aur OI data se pata chalta hai ki kis side ka haath mazboot tha. "
                   "Delivery badhne ka matlab shares haath badalna (accumulation), girne ka matlab profit booking (distribution). "
                   "OI ke saath price dekhne se pata chalta hai ki naye positions bane (buildup) ya purane band hue (unwinding).")
        forecast = (f"🔮 Kal ka forecast: overall bias {bias}. "
                    + (f"NIFTY {nifty_opt['support']:.0f} support / {nifty_opt['resistance']:.0f} resistance — in levels ke bahar break hone par trend tez hoga. "
                       if nifty_opt and nifty_opt.get("support") and nifty_opt.get("resistance") else "")
                    + ("FII buying + delivery up = kal bhi upside follow-through. " if fii_net > 0 else "FII selling + delivery down = kal bhi downside sambhav. " if fii_net < 0 else ""))
    else:
        summary = (f"⚡ Live AI Summary: Market open hai — abhi tak ka data **{bias}** setup dikha raha hai. "
                   f"{' | '.join(drivers[:4])}.")
        meaning = ("📖 Iska matlab: intraday me delivery data EOD ke baad hi aata hai, isliye abhi OI + FII + global cues "
                   "se hi bias judge karo. Live breadth aur PCR sabse tez badlav batate hain.")
        forecast = f"🔮 Session close ke baad post-market section me poora review + kal ka forecast milega (bias abhi: {bias})."

    return {
        "bias": bias, "bias_en": bias_en, "score": round(score, 2),
        "summary": summary, "meaning": meaning, "forecast": forecast,
        "confidence": confidence, "drivers": drivers, "delivery_label": dl,
    }


# ------------------------------------------------------------- top 10

_TF_SCORE = {"Monthly": 6, "Weekly": 5, "Daily": 5, "6H": 4, "4H": 4, "2H": 4, "1H": 3, "75m": 2, "30m": 2, "15m": 1}


def compute_top10(zones_df: Optional[pd.DataFrame], pulse_map: dict, ctx: dict,
                  direction: str = "buy", n: int = 10) -> pd.DataFrame:
    """Top N buy/sell — zone proximity + freshness/HQ + delivery + volume + OI
    signal + PCR + FII + global + news ka composite score."""
    direction = "buy" if direction == "buy" else "sell"
    is_buy = direction == "buy"

    best_zone: Dict[str, pd.Series] = {}
    if zones_df is not None and not zones_df.empty and "Ticker" in zones_df.columns:
        z = zones_df.copy()
        want = "DEMAND" if is_buy else "SUPPLY"
        z = z[z["Direction"].astype(str).str.contains(want, na=False)]
        if not z.empty:
            # pulse_map clean symbols (no .NS) use karta hai — normalize karke join karo
            z["_clean"] = z["Ticker"].astype(str).str.replace(".NS", "", regex=False).str.upper().str.strip()
            z["_absd"] = pd.to_numeric(z["Distance %"], errors="coerce").abs().fillna(99)
            z["_tfsc"] = z["Timeframe"].map(_TF_SCORE).fillna(1)
            z = z.sort_values(["_clean", "_absd", "_tfsc"], ascending=[True, True, False])
            for sym, grp in z.groupby("_clean"):
                best_zone[str(sym)] = grp.iloc[0]

    candidates = set(best_zone.keys()) | set((pulse_map or {}).keys())
    rows = []
    for sym in candidates:
        p = (pulse_map or {}).get(sym, {})
        z = best_zone.get(sym)
        score = 0.0
        reasons: List[str] = []

        if z is not None:
            dist = float(z["_absd"])
            score += 40.0 * max(0.0, 1.0 - min(dist, 10.0) / 10.0)
            if str(z.get("State", "")) == "Fresh":
                score += 8
                reasons.append("Fresh zone")
            hq = z.get("HQ Zone (Rule3 Boring-Colour)", z.get("HQ Zone"))
            if hq is True or str(hq).upper() == "TRUE":
                score += 8
                reasons.append("HQ zone")
            if str(z.get("Timeframe")) in ("Daily", "Weekly", "Monthly", "1H", "2H", "4H", "6H"):
                score += 5
                reasons.append(f"{z.get('Timeframe')} TF")
            entry = z.get("Entry (Proximal)")
            sl = z.get("Stop Loss (Distal+Buffer)")
            tgt = z.get("Target (RR set)")
            tf = str(z.get("Timeframe"))
            dist_s = f"{float(z.get('Distance %')):+.2f}%"
        else:
            score += 10.0  # pulse-only idea (no live zone)
            entry = sl = tgt = None
            tf = "—"
            dist_s = "—"

        dchg = p.get("deliv_chg_pp")
        dpct = p.get("deliv_pct")
        if dchg is not None:
            if is_buy:
                if dchg >= 5:
                    score += 12; reasons.append(f"Delivery {dchg:+.1f}pp↑")
                elif dchg >= 2:
                    score += 7; reasons.append(f"Delivery {dchg:+.1f}pp↑")
                elif dchg <= -3:
                    score -= 8; reasons.append(f"Delivery {dchg:+.1f}pp↓ (distribution)")
            else:
                if dchg <= -5:
                    score += 12; reasons.append(f"Delivery {dchg:+.1f}pp↓ (distribution)")
                elif dchg <= -2:
                    score += 7; reasons.append(f"Delivery {dchg:+.1f}pp↓")
                elif dchg >= 3:
                    score -= 8; reasons.append(f"Delivery {dchg:+.1f}pp↑ (accumulation)")
        if dpct is not None and dpct >= 60:
            score += 5
            reasons.append(f"High delivery {dpct:.0f}%")

        v = p.get("vol_vs_yday")
        if v is not None:
            if v >= 2:
                score += 8; reasons.append(f"Vol {v:.1f}×")
            elif v >= 1.5:
                score += 5; reasons.append(f"Vol {v:.1f}×")
            elif v <= 0.6:
                score -= 4

        sig_en = (p.get("oi_signal_en") or "")
        if is_buy:
            if sig_en in ("long_buildup", "short_covering", "put_writing"):
                score += 8; reasons.append(p.get("oi_signal", ""))
            elif sig_en in ("short_buildup", "long_unwinding", "call_writing"):
                score -= 10; reasons.append(p.get("oi_signal", ""))
        else:
            if sig_en in ("short_buildup", "long_unwinding", "call_writing"):
                score += 8; reasons.append(p.get("oi_signal", ""))
            elif sig_en in ("long_buildup", "short_covering", "put_writing"):
                score -= 10; reasons.append(p.get("oi_signal", ""))

        pcr = p.get("pcr")
        if pcr is not None:
            if is_buy and pcr >= 1.05:
                score += 3; reasons.append(f"PCR {pcr:.2f}")
            if (not is_buy) and pcr <= 0.95:
                score += 3; reasons.append(f"PCR {pcr:.2f}")

        if ctx.get("fii_buying") and is_buy:
            score += 4
        if ctx.get("fii_selling") and not is_buy:
            score += 4
        if ctx.get("global_bullish") and is_buy:
            score += 3
        if ctx.get("global_bearish") and not is_buy:
            score += 3

        nb = (ctx.get("news_bias") or {}).get(sym)
        if nb == "Bullish" and is_buy:
            score += 5; reasons.append("Bullish news 📰")
        if nb == "Bearish" and not is_buy:
            score += 5; reasons.append("Bearish news 📰")

        rows.append({
            "Symbol": sym,
            "Score": round(score, 1),
            "TF": tf,
            "Entry": entry, "SL": sl, "Target": tgt,
            "Dist %": dist_s,
            "Deliv %": p.get("deliv_pct"),
            "ΔDeliv pp": p.get("deliv_chg_pp"),
            "Vol ×": p.get("vol_vs_yday"),
            "OI Signal": p.get("oi_signal", "—"),
            "Reason": "; ".join([r for r in reasons if r])[:160] or "Pulse data only",
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values("Score", ascending=False).head(n).reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out


# ------------------------------------------------------------- enrichment

def enrich_zones_with_pulse(df: Optional[pd.DataFrame], pulse_map: dict):
    """Zone table me naye trader columns add karta hai:
    Delivery %, ΔDeliv pp (aaj vs pichhla din), Vol ×Yday, OI Signal."""
    if df is None or df.empty or "Ticker" not in df.columns:
        return df
    out = df.copy()

    def _g(t, k):
        p = (pulse_map or {}).get(str(t).replace(".NS", "").upper().strip())
        return p.get(k) if p else None

    out["Delivery %"] = [_g(t, "deliv_pct") for t in out["Ticker"]]
    out["ΔDeliv pp"] = [_g(t, "deliv_chg_pp") for t in out["Ticker"]]
    out["Vol ×Yday"] = [_g(t, "vol_vs_yday") for t in out["Ticker"]]
    out["OI Signal"] = [(_g(t, "oi_signal") or "—") for t in out["Ticker"]]
    return out


def enrich_zones_with_pulse_cached(df: Optional[pd.DataFrame]):
    if df is None or df.empty or "Ticker" not in df.columns:
        return df
    tickers = tuple(sorted({str(t) for t in df["Ticker"].dropna().unique()}))
    pulse = get_pulse_map(tickers)
    return enrich_zones_with_pulse(df, pulse)


def clear_pulse_caches():
    for fn in (_cm_auto, _cm_for, _fo_auto, get_pulse_map, get_market_tables, get_breadth,
               get_live_breadth, get_option_chain_summary, get_news_sentiment, get_global_bias,
               get_macro_events, get_fii_safe, _fno_symbols_cached):
        try:
            fn.clear()
        except Exception:
            pass


# ------------------------------------------------------------- UI rendering

def render_pulse_strip(tickers=(), prefix_html: str = "", show_fii: bool = True) -> bool:
    """Top tape ke neeche compact strip: phase + PCR + FII/DII + global + AI bias.

    prefix_html (market tape ke chips) isi st.markdown block me render hota hai, taaki
    tape aur pulse chips ke beech khaali gap na bane. Return True jab prefix render ho gaya.
    """
    rendered = False
    try:
        phase = get_market_phase()
        nifty_opt = get_option_chain_summary("NIFTY")
        fii = get_fii_safe()
        glob = get_global_bias()
        news = get_news_sentiment(hours=24)

        score = 0.0
        pcr = (nifty_opt or {}).get("pcr_oi")
        if pcr:
            score += 0.5 if pcr >= 1.05 else (-0.5 if pcr <= 0.95 else 0)
        fii_net = float(fii.get("fii_net") or 0)
        dii_net = float(fii.get("dii_net") or 0)
        score += 1.0 if fii_net > 0 else (-1.0 if fii_net < 0 else 0)
        g = glob.get("score") or 0
        score += 0.75 if g > 0 else (-0.75 if g < 0 else 0)
        nb = news.get("bull", 0) - news.get("bear", 0)
        score += 0.5 if nb > 0 else (-0.5 if nb < 0 else 0)

        bias = "Bullish 📈" if score >= 1.0 else "Bearish 📉" if score <= -1.0 else "Neutral ➡️"
        bcolor = GREEN if score >= 1.0 else RED if score <= -1.0 else YELLOW

        chips = [_chip("🕒 Phase", phase["label"], GREY)]
        if pcr:
            chips.append(_chip("NIFTY PCR (OI)", f"{pcr:.2f}", BLUE))
        if show_fii and (fii_net or dii_net):  # tape me FII/DII pehle se ho to yahan dobara nahi
            fii_c = GREEN if fii_net >= 0 else RED
            dii_c = GREEN if dii_net >= 0 else RED
            chips.append(_chip("FII/DII", f'<span style="color:{fii_c};">FII {fii_net:+.0f}Cr</span> <span style="color:{dii_c};">DII {dii_net:+.0f}Cr</span>', GREY))
        chips.append(_chip("🌍 Global", glob.get("label", "N/A"), GREY))
        chips.append(_chip("🧠 AI Bias", bias, bcolor))
        st.markdown(TAPE_BLOCK_OPEN + str(prefix_html or "") + "".join(chips) + "</div>", unsafe_allow_html=True)
        rendered = True
    except Exception as e:
        print(f"pulse strip render error (safe): {e}")
        if prefix_html and not rendered:
            st.markdown(TAPE_BLOCK_OPEN + prefix_html + "</div>", unsafe_allow_html=True)  # tape kam se kam dikhe
            rendered = True
    return rendered


def _df_table(df, height=None):
    if df is None or df.empty:
        st.caption("Data unavailable (source blocked ya abhi publish nahi hua)")
        return
    kwargs = {"width": "stretch", "hide_index": True}
    if height:
        kwargs["height"] = height
    st.dataframe(df, **kwargs)


def _render_ai_box(summary: dict, key_suffix: str = ""):
    color = _bias_color(summary.get("bias_en", ""))
    st.markdown(
        f"<div style='background:{color}22;border:1px solid {color};border-radius:10px;padding:12px 16px;margin:8px 0;'>"
        f"<b style='font-size:15px;'>{summary['summary']}</b><br>"
        f"<span style='color:#ccc;'>{summary['meaning']}</span><br>"
        f"<span style='color:#f0b90b;'>{summary['forecast']}</span><br>"
        f"<small style='color:#888;'>Confidence: {summary['confidence']} | Bias score: {summary['score']:+.2f} | "
        f"Rule-based AI (bina key ke) — data fusion: breadth + delivery + OI + FII/DII + volume + global + news</small></div>",
        unsafe_allow_html=True)
    with st.expander("🔎 AI ne kaun-kaun se signals dekhe (drivers)", expanded=False):
        for d in summary.get("drivers", []):
            st.markdown(f"- {d}")
    if st.button("🤖 Gemini se AI Summary aur gehra karo (optional)", key=f"pulse_gemini_btn{key_suffix}"):
        try:
            from secure_config import is_gemini_configured, get_gemini_key
            if not is_gemini_configured():
                st.info("Gemini key nahi hai — rule-based AI summary already chal raha hai (bina key ke bhi kaam karta hai). Key dene par ye aur gehra ho jayega.")
            else:
                from gemini_analyzer import GeminiZoneAnalyzer
                client = GeminiZoneAnalyzer(api_key=get_gemini_key())
                prompt = (
                    "You are a senior NSE demand & supply trader. niche diye gaye data se ek SHORT Hinglish "
                    "market summary do (max 5 lines): bias, kya matlab hai, aur agla session ka forecast.\n\n"
                    f"Data: {summary['summary']} | {summary['meaning']} | Drivers: {'; '.join(summary.get('drivers', []))}"
                )
                with st.spinner("Gemini AI summary bana raha hai..."):
                    enhanced = client.model.generate_content(prompt).text
                st.markdown(f"<div style='background:#8a2be222;border:1px solid #8a2be2;border-radius:10px;padding:12px 16px;margin:8px 0;'>{enhanced}</div>", unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"Gemini enhance error (rule-based summary pehle se chal raha hai): {e}")


def _render_top10(zones_df, tickers, fii, glob, news):
    st.markdown("#### 🎯 Top 10 BUY / 🔻 Top 10 SELL — Forecast (Zone + Delivery + OI + Volume + FII + Global + News)")
    st.caption("Composite score: sabse nazdeek fresh/HQ zone (bade TF ko weight) + delivery change + volume surge + OI buildup + PCR + FII/DII + global cues + news sentiment. Educational only — financial advice nahi.")
    try:
        fno_syms = _fno_symbols_cached()
        zone_syms = []
        if zones_df is not None and not zones_df.empty and "Ticker" in zones_df.columns:
            zone_syms = [str(t) for t in zones_df["Ticker"].dropna().unique()]
        all_syms = tuple(sorted(set(fno_syms) | set(zone_syms) | {str(t).replace(".NS", "") for t in (tickers or ())}))
        pulse = get_pulse_map(all_syms) if all_syms else {}
        ctx = {
            "fii_buying": float(fii.get("fii_net") or 0) > 0,
            "fii_selling": float(fii.get("fii_net") or 0) < 0,
            "global_bullish": (glob.get("score") or 0) > 0,
            "global_bearish": (glob.get("score") or 0) < 0,
            "news_bias": (news or {}).get("bias_map", {}),
        }
        buy10 = compute_top10(zones_df, pulse, ctx, "buy", 10)
        sell10 = compute_top10(zones_df, pulse, ctx, "sell", 10)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**🟢 Top 10 BUY (watchlist)**")
            _df_table(buy10, height=380)
        with c2:
            st.markdown("**🔴 Top 10 SELL (watchlist)**")
            _df_table(sell10, height=380)
    except Exception as e:
        st.warning(f"Top 10 compute error (safe): {e}")


def _render_pre_market(ctx: dict):
    phase, breadth, tables = ctx["phase"], ctx["breadth"], ctx["tables"]
    nifty_opt, banknifty_opt = ctx["nifty_opt"], ctx["banknifty_opt"]
    fii, glob, news, macro = ctx["fii"], ctx["glob"], ctx["news"], ctx["macro"]
    d1, d2 = tables.get("d1", ""), tables.get("d2", "")

    st.info(phase.get("tab_note", ""))

    stats = tables.get("delivery_stats") or {}
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🌍 Global Cues", glob.get("label", "N/A"))
    m2.metric("NIFTY PCR (OI)", f"{nifty_opt['pcr_oi']:.2f}" if nifty_opt.get("pcr_oi") else "N/A")
    m3.metric("FII Net (last day)", f"{float(fii.get('fii_net') or 0):+.0f} Cr")
    m4.metric("Avg Delivery Δ", f"{stats.get('avg_deliv_chg_pp'):+.1f} pp" if stats.get("avg_deliv_chg_pp") is not None else "N/A",
              help=f"Latest available EOD ({d1}) vs previous ({d2}). Bhavcopy sham ~18:30-19:00 IST ke baad publish hota hai.")

    # ---- option OI overnight ----
    st.markdown("#### 🧾 Option OI — Overnight Signal (PCR + Max Pain + Support/Resistance)")
    rows = []
    for nm, o in (("NIFTY", nifty_opt), ("BANKNIFTY", banknifty_opt)):
        if o:
            rows.append({
                "Index": nm,
                "PCR (OI)": o.get("pcr_oi"), "PCR (Vol)": o.get("pcr_vol"),
                "ΔCE OI": o.get("ce_chg_oi"), "ΔPE OI": o.get("pe_chg_oi"),
                "Max Pain": o.get("max_pain"), "Support (max PE OI)": o.get("support"),
                "Resistance (max CE OI)": o.get("resistance"),
                "Signal": o.get("signal"), "Source": o.get("source", ""),
            })
    if rows:
        _df_table(pd.DataFrame(rows))
    else:
        st.caption("Option chain data unavailable (NSE blocked?) — FO bhavcopy fallback bhi nahi mila.")

    # ---- delivery trend ----
    st.markdown(f"#### 📦 Delivery Trend — latest EOD ({d1}) vs previous day ({d2})")
    st.caption("Delivery % = kitne % traded shares actually deliver hue (physical settlement). Badhna = accumulation, girna = distribution.")
    dg, dd = tables.get("delivery_gainers"), tables.get("delivery_decliners")
    if dg is not None and not dg.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**🟢 Top Delivery Gainers (accumulation)**")
            _df_table(dg)
        with c2:
            st.markdown("**🔴 Top Delivery Losers (distribution)**")
            _df_table(dd)
    else:
        st.caption("Delivery data unavailable (CM bhavcopy nahi mila — NSE blocked ho sakta hai).")

    # ---- events ----
    st.markdown("#### 📰 Aaj ke Events / News (Global macro + Indian market)")
    if macro is not None and not macro.empty:
        _df_table(macro.head(10))
    else:
        st.caption("Macro calendar unavailable.")
    if news.get("headlines"):
        for h in news["headlines"][:5]:
            bc = GREEN if "Bullish" in h["bias"] else RED if "Bearish" in h["bias"] else YELLOW
            st.markdown(
                f"<div style='background:{bc}22;border:1px solid {bc};border-radius:8px;padding:8px 12px;margin:6px 0;'>"
                f"<b style='color:#f0b90b;'>{h['symbol']}</b> <span style='color:{bc};'><b>{h['bias']}</b></span> — "
                f"<span style='color:#eaeaea;'>{h['title']}</span></div>", unsafe_allow_html=True)

    # ---- global detail ----
    with st.expander("🌐 Global Markets Detail (World Indices + DXY / USDINR / Crude / Gold)", expanded=False):
        chips = []
        for key, label in (("dxy", "DXY"), ("usdinr", "USD/INR"), ("crude", "WTI Crude"), ("gold", "Gold")):
            v = glob.get(key)
            if isinstance(v, tuple):
                last, chg = v
                color = GREEN if chg >= 0 else RED
                arrow = "▲" if chg >= 0 else "▼"
                chips.append(_chip(label, f'{last:,.2f} <span style="color:{color};">{arrow} {chg:+.2f}%</span>', color))
        if chips:
            st.markdown("".join(chips), unsafe_allow_html=True)
        _df_table(glob.get("details"))

    # ---- AI summary ----
    st.markdown("#### 🤖 AI Short Summary (sab data ka fusion)")
    summary = generate_ai_summary(
        phase="pre_market", breadth=breadth, delivery_stats=stats,
        nifty_opt=nifty_opt, banknifty_opt=banknifty_opt, fii=fii, glob=glob, news=news, d1=d1, d2=d2)
    _render_ai_box(summary, key_suffix="_pre")

    # ---- top 10 ----
    _render_top10(ctx["zones_df"], ctx["tickers"], fii, glob, news)


def _render_post_market(ctx: dict):
    phase, breadth, tables = ctx["phase"], ctx["breadth"], ctx["tables"]
    nifty_opt, banknifty_opt = ctx["nifty_opt"], ctx["banknifty_opt"]
    fii, glob, news = ctx["fii"], ctx["glob"], ctx["news"]
    d1, d2 = tables.get("d1", ""), tables.get("d2", "")
    stats = tables.get("delivery_stats") or {}

    st.info(phase.get("tab_note", ""))

    # ---- headline: % of F&O futures stocks increased ----
    b = breadth or {}
    pct_up = float(b.get("pct_up") or 0)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(f"📈 F&O Futures Groen % ({d1})", f"{pct_up:.1f}%", help=f"{b.get('up', 0)} up / {b.get('down', 0)} down / {b.get('flat', 0)} flat out of {b.get('total', 0)} stock futures (source: {b.get('source', '—')})")
    m2.metric("Advancers / Decliners", f"{b.get('up', 0)} / {b.get('down', 0)}")
    m3.metric("Avg Delivery Δ", f"{stats.get('avg_deliv_chg_pp'):+.1f} pp" if stats.get("avg_deliv_chg_pp") is not None else "N/A")
    m4.metric("NIFTY PCR (OI)", f"{nifty_opt['pcr_oi']:.2f}" if nifty_opt.get("pcr_oi") else "N/A")
    m5.metric("FII / DII Net", f"{float(fii.get('fii_net') or 0):+.0f} / {float(fii.get('dii_net') or 0):+.0f} Cr")
    if b.get("total"):
        st.progress(min(max(pct_up / 100.0, 0.0), 1.0))
        st.caption(f"Breadth bar: {pct_up:.1f}% of NSE F&O futures stocks increased on {d1} (vs prev close). 50% = neutral, >55% = healthy, <45% = weak.")

    # ---- delivery: aaj ka % vs pichhla din ----
    st.markdown(f"#### 📦 Aaj ka Delivery % vs Pichhla Din ({d1} vs {d2})")
    dg, dd = tables.get("delivery_gainers"), tables.get("delivery_decliners")
    if dg is not None and not dg.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**🟢 Delivery sabse zyada badhi (accumulation)**")
            _df_table(dg)
        with c2:
            st.markdown("**🔴 Delivery sabse zyada giri (distribution)**")
            _df_table(dd)
    else:
        st.caption("Delivery data unavailable.")

    # ---- gainers/losers + volume + OI ----
    st.markdown("#### 📊 Price Movers + Volume + OI Signals (EOD)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Top Gainers**")
        _df_table(tables.get("top_gainers"))
    with c2:
        st.markdown("**🔴 Top Losers**")
        _df_table(tables.get("top_losers"))
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**📢 Volume Breakout (≥1.5× vs prev day)**")
        _df_table(tables.get("volume_breakout"))
    with c4:
        st.markdown("**🧾 Option/Futures OI Signals (sabse bada OI change)**")
        _df_table(tables.get("oi_signals"))

    # ---- option chain EOD ----
    st.markdown("#### 🧾 Option Chain — EOD Signal (PCR + Max Pain + Support/Resistance)")
    rows = []
    for nm, o in (("NIFTY", nifty_opt), ("BANKNIFTY", banknifty_opt)):
        if o:
            rows.append({
                "Index": nm, "PCR (OI)": o.get("pcr_oi"), "PCR (Vol)": o.get("pcr_vol"),
                "CE OI": o.get("ce_oi"), "PE OI": o.get("pe_oi"),
                "ΔCE OI": o.get("ce_chg_oi"), "ΔPE OI": o.get("pe_chg_oi"),
                "Max Pain": o.get("max_pain"), "Support": o.get("support"), "Resistance": o.get("resistance"),
                "Signal": o.get("signal"), "Source": o.get("source", ""),
            })
    if rows:
        _df_table(pd.DataFrame(rows))
    else:
        st.caption("Option chain data unavailable.")

    # ---- FII/DII ----
    with st.expander("💰 FII/DII — Full Data (last few days)", expanded=False):
        fii_df = fii.get("full_df")
        if fii_df is None or (hasattr(fii_df, "empty") and fii_df.empty):
            try:
                from fii_dii_fetcher import get_fii_dii_data
                fii_df = get_fii_dii_data()
            except Exception:
                fii_df = None
        _df_table(fii_df if fii_df is not None else pd.DataFrame())

    # ---- AI summary ----
    st.markdown("#### 🤖 AI Short Summary + Kal ka Forecast")
    summary = generate_ai_summary(
        phase="post_market", breadth=breadth, delivery_stats=stats,
        nifty_opt=nifty_opt, banknifty_opt=banknifty_opt, fii=fii, glob=glob, news=news, d1=d1, d2=d2)
    _render_ai_box(summary, key_suffix="_post")

    # ---- top 10 for next session ----
    _render_top10(ctx["zones_df"], ctx["tickers"], fii, glob, news)


def render_ai_trader_pulse(zones_df: Optional[pd.DataFrame] = None, tickers=()):
    """Full AI Trader Pulse section — Pre-Market / Post-Market briefing."""
    try:
        phase = get_market_phase()
        st.markdown("---")
        st.header("🧠 AI Trader Pulse — Pre-Market / Post-Market Briefing")
        st.caption("Senior D&S trader style briefing: Delivery % (aaj vs pichhla din) + F&O Breadth (% futures up) + Option OI (PCR/max pain/buildup) + FII/DII + Volume/Price + Global + Indian News → AI short summary (matlab + forecast) + Top 10 Buy/Sell. Sab free sources, bina API key ke.")

        choice = st.radio(
            "Kaunsa section dekhna hai?",
            ["🌅 Pre-Market Setup", "🌇 Post-Market Review"],
            index=phase.get("tab_index", 0), horizontal=True, key="pulse_section_choice",
            help="Market phase ke hisaab se default section pehle se select hai — dono dekh sakte ho.",
        )

        ctx = {
            "phase": phase,
            "breadth": get_breadth(),
            "tables": get_market_tables(),
            "nifty_opt": get_option_chain_summary("NIFTY"),
            "banknifty_opt": get_option_chain_summary("BANKNIFTY"),
            "fii": get_fii_safe(),
            "glob": get_global_bias(),
            "news": get_news_sentiment(hours=24),
            "macro": get_macro_events(),
            "zones_df": zones_df if zones_df is not None else pd.DataFrame(),
            "tickers": tuple(tickers or ()),
        }

        c1, c2, c3 = st.columns([1, 1, 1])
        with c3:
            if st.button("🔄 Pulse data refresh (bhavcopy/OI cache clear)", width="stretch"):
                clear_pulse_caches()
                st.rerun()

        if choice.startswith("🌅"):
            _render_pre_market(ctx)
        else:
            _render_post_market(ctx)
    except Exception as e:
        print(f"render_ai_trader_pulse error (safe): {e}")
        st.caption("⚠️ AI Trader Pulse load nahi ho paya — scanner bilkul unaffected hai (neeche table chalti rahegi).")


# ------------------------------------------------------------- self test

if __name__ == "__main__":
    # Fixture-based self test — bina network ke parsing logic verify karta hai.
    # Real NSE formats verify kiye gaye hain (web + jugaad-data source se):
    #   CM: sec_bhavdata_full (DELIV_QTY/DELIV_PER) + legacy space-style bhavcopy
    #   FO: legacy (INSTRUMENT/OPEN_INT/CHG_IN_OI, no prev close) + UDiff (>= Jul-2024)
    print("=== market_pulse self test (fixtures, no network) ===")

    # ---- CM format 1: sec_bhavdata_full (authoritative delivery file) ----
    cm_full_csv = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, "
        "CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "RELIANCE, EQ, 09-Oct-2026, 2900.00, 2905.00, 2950.00, 2890.00, 2940.00, 2940.00, 2925.00, 10000000, 2940.00, 50000, 4500000, 45.00\n"
        "TCS, EQ, 09-Oct-2026, 4150.00, 4160.00, 4180.00, 4090.00, 4120.00, 4120.00, 4130.00, 8000000, 3296.00, 40000, 2000000, 25.00\n"
        "SGBJAN29IX, GB, 09-Oct-2026, 13223.64, 13231.01, 13588.99, 13231.01, 13540.00, 13539.99, 13487.00, 286, 38.57, 61, 254, 88.81\n"
    )
    cm_map = _parse_cm_bhavcopy(pd.read_csv(io.StringIO(cm_full_csv)))
    assert cm_map["RELIANCE"]["deliv_pct"] == 45.0, cm_map["RELIANCE"]
    assert abs(cm_map["RELIANCE"]["chg_pct"] - (2940 / 2900 - 1) * 100) < 1e-6
    assert abs(cm_map["TCS"]["chg_pct"] - (4120 / 4150 - 1) * 100) < 1e-6
    assert "SGBJAN29IX" not in cm_map, "GB series filter hone chahiye (sirf EQ)"
    print("PASS: CM sec_bhavdata_full parse (delivery %, chg %, EQ filter)")

    # ---- CM format 2: legacy CM bhavcopy (space-style + delivery cols) ----
    cm_csv = (
        "Symbol,Series,Open Price,High Price,Low Price,Close Price,Last Traded Price,Prev Close,"
        "Total Traded Quantity,Total Traded Value,Total Traded Volume,No. of Trades,ISIN,Deliverable Qty,% Deli. Qty to Traded Qty\n"
        "RELIANCE,EQ,2900,2950,2890,2940,2940,2900,10000000,29400000000,10000000,50000,INE002A01018,4500000,45.0\n"
        "INFY,EQ,1500,1520,1490,1510,1510,1500,5000000,7550000000,5000000,30000,INE010A01010,3000000,60.0\n"
    )
    cm_map2 = _parse_cm_bhavcopy(pd.read_csv(io.StringIO(cm_csv)))
    assert cm_map2["INFY"]["deliv_pct"] == 60.0
    assert cm_map2["RELIANCE"]["qty"] == 10000000
    print("PASS: CM legacy bhavcopy parse (space-style columns)")

    # ---- FO format 1: legacy (INSTRUMENT, OPEN_INT, CHG_IN_OI, CONTRACTS, no prev close) ----
    fo_legacy_csv = (
        "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP\n"
        "FUTSTK,RELIANCE,30-OCT-2026,0,XX,2900,2950,2890,2940,2940,40000,98000000,5000000,250000,09-Oct-2026\n"
        "FUTSTK,TCS,30-OCT-2026,0,XX,4100,4150,4090,4120,4120,80000,329600000,3000000,-150000,09-Oct-2026\n"
        "OPTSTK,RELIANCE,30-OCT-2026,2900,CE,100,120,90,110,110,2000,22000,2000000,300000,09-Oct-2026\n"
        "OPTSTK,RELIANCE,30-OCT-2026,2900,PE,50,60,40,45,45,1200,5400,1500000,200000,09-Oct-2026\n"
        "OPTSTK,RELIANCE,30-OCT-2026,3000,CE,60,70,50,65,65,800,5200,800000,50000,09-Oct-2026\n"
        "OPTSTK,RELIANCE,30-OCT-2026,3000,PE,120,130,110,125,125,1600,20000,2500000,250000,09-Oct-2026\n"
    )
    fo_l = _parse_fo_bhavcopy(pd.read_csv(io.StringIO(fo_legacy_csv)))
    ml = fo_l["map"]["RELIANCE"]
    assert ml["fut_oi"] == 5000000 and ml["fut_oi_chg"] == 250000, ml
    assert abs(ml["fut_oi_chg_pct"] - (250000 / 4750000 * 100)) < 1e-6
    assert ml["ce_oi"] == 2800000 and ml["pe_oi"] == 4000000, ml
    assert abs(ml["pcr"] - 4000000 / 2800000) < 1e-6
    assert ml["chg_pct"] is None, "legacy FO me prev close nahi hota"
    assert fo_l["breadth"]["total"] == 0, "legacy FO breadth nahi ban sakta (no prev close)"
    # legacy: price chg nahi hai toh signal option-writing se aata hai (pe_chg 450000 > ce_chg 350000)
    assert ml["oi_signal_en"] == "put_writing", ml["oi_signal"]
    print("PASS: FO legacy parse (INSTRUMENT/OPEN_INT/CHG_IN_OI, option aggregates, PCR)")

    # ---- FO format 2: UDiff (>= Jul-2024): TckrSymb, FinInstrmTp, OpnIntrst, ChngInOpnIntrst ----
    # (subset of real UDiff columns — parser only needs these)
    fo_udiff_csv = (
        "TradDt,TckrSymb,FinInstrmTp,XpryDt,StrkPric,OptnTp,ClsPric,PrvsClsgPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol\n"
        "2026-10-09,RELIANCE,STF,2026-10-30,0,XX,2940,2900,5000000,250000,40000\n"
        "2026-10-09,TCS,STF,2026-10-30,0,XX,4120,4150,3000000,-150000,80000\n"
        "2026-10-09,RELIANCE,STO,2026-10-30,2900,CE,110,105,2000000,300000,2000\n"
        "2026-10-09,RELIANCE,STO,2026-10-30,2900,PE,45,48,1500000,200000,1200\n"
        "2026-10-09,RELIANCE,STO,2026-10-30,3000,CE,65,62,800000,50000,800\n"
        "2026-10-09,RELIANCE,STO,2026-10-30,3000,PE,125,122,2500000,-100000,1600\n"
    )
    fo_u = _parse_fo_bhavcopy(pd.read_csv(io.StringIO(fo_udiff_csv)))
    mu = fo_u["map"]["RELIANCE"]
    # UDiff: ClsPric 2940 vs PrvsClsgPric 2900 => +1.38% up; fut OI +250000 => Long Buildup
    assert mu["chg_pct"] is not None and mu["chg_pct"] > 1.0, mu
    assert mu["fut_oi"] == 5000000 and mu["fut_oi_chg"] == 250000, mu
    assert mu["oi_signal_en"] == "long_buildup", mu["oi_signal"]
    assert mu["ce_oi"] == 2800000 and mu["pe_oi"] == 4000000, mu
    # breadth: STF rows with prev close — RELIANCE up, TCS down
    assert fo_u["breadth"]["up"] == 1 and fo_u["breadth"]["down"] == 1 and fo_u["breadth"]["total"] == 2, fo_u["breadth"]
    assert fo_u["breadth"]["pct_up"] == 50.0
    print("PASS: FO UDiff parse (TckrSymb/FinInstrmTp/OpnIntrst/ChngInOpnIntrst, breadth)")

    # ---- URL builders sanity ----
    d = dt.date(2026, 10, 9)
    assert any("sec_bhavdata_full_09102026.csv" in u for u in _cm_full_urls(d)), _cm_full_urls(d)
    assert any("cm09OCT2026bhav.csv.zip" in u for u in _cm_legacy_urls(d)), _cm_legacy_urls(d)
    assert any("BhavCopy_NSE_CM_0_0_0_20261009_F_0000.csv.zip" in u for u in _cm_udiff_urls(d)), _cm_udiff_urls(d)
    assert any("DERIVATIVES/2026/OCT/fo09OCT2026bhav.csv.zip" in u for u in _fo_legacy_urls(d)), _fo_legacy_urls(d)
    assert any("BhavCopy_NSE_FO_0_0_0_20261009_F_0000.csv.zip" in u for u in _fo_udiff_urls(d)), _fo_udiff_urls(d)
    print("PASS: URL builders (sec_bhavdata_full / CM legacy+UDiff / FO legacy+UDiff)")

    # ---- option chain ----
    oc_payload = {
        "records": {
            "underlyingValue": 24150.0,
            "expiryDates": ["15-OCT-2026", "30-OCT-2026"],
            "data": [
                {"strikePrice": 24000, "expiryDate": "15-OCT-2026",
                 "CE": {"openInterest": 1000, "changeinOpenInterest": 100, "totalTradedVolume": 500},
                 "PE": {"openInterest": 3000, "changeinOpenInterest": 400, "totalTradedVolume": 700}},
                {"strikePrice": 24100, "expiryDate": "15-OCT-2026",
                 "CE": {"openInterest": 2000, "changeinOpenInterest": 200, "totalTradedVolume": 600},
                 "PE": {"openInterest": 2500, "changeinOpenInterest": 300, "totalTradedVolume": 800}},
                {"strikePrice": 24200, "expiryDate": "15-OCT-2026",
                 "CE": {"openInterest": 4000, "changeinOpenInterest": 500, "totalTradedVolume": 900},
                 "PE": {"openInterest": 1000, "changeinOpenInterest": 600, "totalTradedVolume": 300}},
            ],
        }
    }
    oc = parse_option_chain(oc_payload)
    assert oc["pcr_oi"] == round(6500 / 7000, 2), oc["pcr_oi"]
    assert oc["support"] == 24000.0 and oc["resistance"] == 24200.0, (oc["support"], oc["resistance"])
    assert oc["max_pain"] is not None
    assert oc["signal_en"] == "put_writing", oc["signal"]
    print("PASS: option chain parse (PCR, support/resistance, max pain, signal)")

    # ---- top10 + enrichment ----
    zones = pd.DataFrame([
        {"Ticker": "RELIANCE.NS", "Direction": "DEMAND (Buy Zone)", "Timeframe": "Daily", "State": "Fresh",
         "HQ Zone (Rule3 Boring-Colour)": True, "Entry (Proximal)": 2900.0, "Stop Loss (Distal+Buffer)": 2850.0,
         "Target (RR set)": 3050.0, "Distance %": -1.4},
        {"Ticker": "TCS.NS", "Direction": "SUPPLY (Sell Zone)", "Timeframe": "1H", "State": "Tested",
         "HQ Zone (Rule3 Boring-Colour)": False, "Entry (Proximal)": 4200.0, "Stop Loss (Distal+Buffer)": 4250.0,
         "Target (RR set)": 4050.0, "Distance %": 2.0},
    ])
    pulse = {
        "RELIANCE": {"symbol": "RELIANCE", "chg_pct": 1.4, "deliv_pct": 45.0, "deliv_prev": 38.0, "deliv_chg_pp": 7.0,
                     "vol_vs_yday": 2.2, "fut_oi_chg_pct": 5.3, "pcr": 1.12, "oi_signal": "Long Buildup 🟢", "oi_signal_en": "long_buildup"},
        "TCS": {"symbol": "TCS", "chg_pct": -0.7, "deliv_pct": 25.0, "deliv_prev": 30.0, "deliv_chg_pp": -5.0,
                "vol_vs_yday": 1.6, "fut_oi_chg_pct": 5.1, "pcr": 0.8, "oi_signal": "Short Buildup 🔴", "oi_signal_en": "short_buildup"},
    }
    ctx = {"fii_buying": True, "fii_selling": False, "global_bullish": True, "global_bearish": False, "news_bias": {}}
    buy10 = compute_top10(zones, pulse, ctx, "buy", 10)
    sell10 = compute_top10(zones, pulse, ctx, "sell", 10)
    # RELIANCE: DEMAND zone + bullish pulse => buy rank 1. TCS: SUPPLY zone + bearish pulse => sell rank 1.
    assert buy10.iloc[0]["Symbol"] == "RELIANCE", buy10
    assert sell10.iloc[0]["Symbol"] == "TCS", sell10
    assert buy10.iloc[0]["Score"] > buy10.iloc[-1]["Score"]
    assert sell10.iloc[0]["Score"] > sell10.iloc[-1]["Score"]
    print("PASS: compute_top10 (zone + pulse scoring, buy/sell ranking)")

    enriched = enrich_zones_with_pulse(zones.copy(), pulse)
    assert "Delivery %" in enriched.columns and enriched.loc[0, "Delivery %"] == 45.0
    assert enriched.loc[0, "OI Signal"] == "Long Buildup 🟢"
    print("PASS: enrich_zones_with_pulse (new table columns)")

    # ---- AI summary ----
    summ = generate_ai_summary(
        phase="post_market",
        breadth=fo_u["breadth"],
        delivery_stats={"avg_deliv_pct": 43.3, "avg_deliv_chg_pp": 1.0, "pct_deliv_up": 60.0, "pct_deliv_down": 40.0, "n": 2},
        nifty_opt=oc, banknifty_opt={}, fii={"fii_net": 1200, "dii_net": -300},
        glob={"score": 1, "label": "US 🟢", "usdinr": (83.2, 0.2), "crude": (72.0, -1.2)},
        news={"bull": 3, "bear": 1}, d1="2026-10-09", d2="2026-10-08")
    assert summ["bias_en"] in ("bullish", "mild_bullish", "bearish", "mild_bearish", "neutral")
    assert "matlab" in summ["meaning"].lower()
    assert summ["summary"] and summ["meaning"] and summ["forecast"]
    print(f"PASS: generate_ai_summary (bias={summ['bias']}, score={summ['score']})")

    # ---- market phase (offline, fixed timestamps) ----
    import pandas as _pd
    ph_pre = get_market_phase(_pd.Timestamp("2026-10-12 08:00", tz=IST))   # Monday pre-open
    ph_open = get_market_phase(_pd.Timestamp("2026-10-12 11:00", tz=IST))  # Monday open
    ph_post = get_market_phase(_pd.Timestamp("2026-10-12 16:30", tz=IST))  # Monday post-close
    ph_end = get_market_phase(_pd.Timestamp("2026-10-10 12:00", tz=IST))   # Saturday
    assert ph_pre["phase"] == "pre_market" and ph_pre["tab_index"] == 0
    assert ph_open["phase"] == "open" and ph_open["tab_index"] == 1
    assert ph_post["phase"] == "post_market" and ph_post["tab_index"] == 1
    assert ph_end["phase"] == "closed"
    print("PASS: get_market_phase (pre/open/post/closed + default tab)")

    print("=== ALL SELF TESTS PASSED ===")
