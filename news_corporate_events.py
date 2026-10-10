"""
news_corporate_events.py
News, Events, Corporate Actions, Results - Powerful data for Zone Scanner

Sources:
- NSE India API (free, no key): corporate actions, announcements, results, board meetings
- Dhan / TradingView news
- Optional: NewsAPI, MarketAux for global news
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time

# ---------- NSE India Corporate Actions ----------
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

def parse_nse_dt(val) -> datetime:
    """NSE announcement dates ('30-Jul-2026 13:11:46' ya '30-Jul-2026') -> datetime (safe)."""
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d %b %Y %H:%M:%S", "%d %b %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).to_pydatetime()
    except Exception:
        return None

def _norm_event_text(val: str) -> str:
    """Dedupe ke liye desc/subject ko normalize karo (time/space/Case hatao)."""
    s = str(val or "").lower().strip()
    return " ".join(s.split())

def nse_get_cookies():
    """NSE ko cookie chahiye pehle"""
    try:
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        return s.cookies
    except:
        return None

def get_nse_corporate_actions(symbol: str = None, days: int = 30) -> pd.DataFrame:
    """
    NSE Corporate Actions: Dividend, Bonus, Split, Rights
    API: https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=RELIANCE
    """
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        # First hit to get cookies
        session.get("https://www.nseindia.com/companies-listing/corporate-filings-actions", timeout=10)
        
        url = "https://www.nseindia.com/api/corporates-corporateActions"
        params = {"index": "equities"}
        if symbol:
            params["symbol"] = symbol
        
        resp = session.get(url, params=params, timeout=15)
        data = resp.json()
        
        rows = []
        for item in data:
            # Filter last N days
            try:
                ex_date_str = item.get("exDate") or item.get("ex_date")
                if ex_date_str:
                    ex_date = datetime.strptime(ex_date_str, "%d-%b-%Y")
                    if ex_date < datetime.now() - timedelta(days=days):
                        continue
                rows.append({
                    "symbol": item.get("symbol"),
                    "company": item.get("companyName"),
                    "purpose": item.get("purpose") or item.get("subject"),
                    "ex_date": item.get("exDate"),
                    "record_date": item.get("recordDate"),
                    "bc_start": item.get("bcStartDate"),
                    "bc_end": item.get("bcEndDate"),
                })
            except:
                continue
        
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"NSE corporate actions error: {e}")
        return pd.DataFrame()

def get_nse_announcements(symbol: str = None, days: int = 7) -> pd.DataFrame:
    """
    NSE Announcements - Results, Board Meetings, etc
    API: https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=RELIANCE
    """
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        session.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements", timeout=10)
        
        url = "https://www.nseindia.com/api/corporate-announcements"
        params = {"index": "equities"}
        if symbol:
            params["symbol"] = symbol
        
        resp = session.get(url, params=params, timeout=15)
        data = resp.json()
        
        now = datetime.now()
        cutoff = now - timedelta(days=days)
        rows = []
        seen = set()
        for item in data:
            dt = parse_nse_dt(item.get("an_dt") or item.get("date"))
            desc = item.get("desc") or item.get("subject") or ""
            # RECENCY FILTER (pehle sirf comment thi, filter lagta hi nahi tha ->
            # mahino purani announcements bhi aa jati thi = stale/latency data)
            if dt is not None and dt < cutoff:
                continue
            # DEDUPE: same text (time alag ho) baar-baar na dikhe
            key = _norm_event_text(desc)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            rows.append({
                "symbol": item.get("symbol"),
                "desc": desc,
                "date": item.get("an_dt") or item.get("date"),
                "_dt": dt,
                "attachment": item.get("attchmntText"),
                "category": item.get("category"),
            })
        
        df = pd.DataFrame(rows)
        # USER RULE: sirf NSE F&O universe ke announcements (baaki equities noise hai)
        try:
            from powerful_news_fetcher import get_fno_symbol_set
            fno = get_fno_symbol_set()
            if not df.empty and "symbol" in df.columns:
                df = df[df["symbol"].astype(str).str.upper().str.strip().isin(fno)]
        except Exception:
            pass  # universe list na mile to purana behaviour (filter skip)
        # Sabse fresh pehle
        if not df.empty and "_dt" in df.columns:
            df = df.sort_values("_dt", ascending=False, na_position="last")
        return df.head(100)
    except Exception as e:
        print(f"NSE announcements error: {e}")
        return pd.DataFrame()

def get_nse_results_calendar(days: int = 30) -> pd.DataFrame:
    """
    Upcoming results calendar - earnings se pehle zone avoid karna powerful hai
    API: https://www.nseindia.com/api/corporate-financial-results?index=equities
    """
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        session.get("https://www.nseindia.com/companies-listing/corporate-filings-financial-results", timeout=10)
        
        url = "https://www.nseindia.com/api/corporate-financial-results"
        params = {"index": "equities"}
        
        resp = session.get(url, params=params, timeout=15)
        data = resp.json()
        
        rows = []
        for item in data:
            rows.append({
                "symbol": item.get("symbol"),
                "company": item.get("companyName"),
                "result_date": item.get("date"),
                "purpose": item.get("purpose"),
            })
        
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"Results calendar error: {e}")
        return pd.DataFrame()

# ---------- Dhan News (if available) ----------
def get_dhan_news(symbol: str, dhan_helper=None):
    """Dhan se news - agar Dhan API me news endpoint ho"""
    # DhanHQ v2 me direct news nahi, par aap TradingView ya NSE se le sakte ho
    return pd.DataFrame()

# ---------- Global News via NewsAPI / MarketAux (optional) ----------
def get_global_news(query: str = "NSE NIFTY", api_key: str = None, source: str = "newsapi"):
    """
    Global news - optional, API key chahiye
    NewsAPI: https://newsapi.org (free 100 req/day)
    MarketAux: https://www.marketaux.com (free tier)
    """
    if not api_key:
        return pd.DataFrame()
    
    try:
        if source == "newsapi":
            url = f"https://newsapi.org/v2/everything?q={query}&language=en&sortBy=publishedAt&pageSize=20&apiKey={api_key}"
            resp = requests.get(url, timeout=10).json()
            articles = resp.get("articles", [])
            rows = [{"title": a["title"], "desc": a["description"], "url": a["url"], "published": a["publishedAt"], "source": a["source"]["name"]} for a in articles]
            return pd.DataFrame(rows)
    except Exception as e:
        print(f"Global news error: {e}")
        return pd.DataFrame()

# ---------- Powerful Filter: Zone ke aas paas corporate action hai kya? ----------
def is_zone_risky_due_to_event(symbol: str, zone_created_date, days_before: int = 5, days_after: int = 5) -> dict:
    """
    Check karo ki zone ke aas paas koi risky event hai kya:
    - Dividend / Bonus / Split ex-date
    - Results / Board meeting
    Agar hai to zone risky hai - price manipulation ho sakta hai
    """
    try:
        corp_df = get_nse_corporate_actions(symbol=symbol, days=30)
        ann_df = get_nse_announcements(symbol=symbol, days=15)
        
        now = datetime.now()
        risky = False
        reasons = []
        seen_reasons = set()
        
        # Check corporate actions near zone date
        for _, row in corp_df.iterrows():
            try:
                ex_date = datetime.strptime(row["ex_date"], "%d-%b-%Y")
                zone_date = pd.to_datetime(zone_created_date)
                delta = (ex_date - zone_date).days
                if -days_before <= delta <= days_after:
                    risky = True
                    reason = f"Corporate Action: {row['purpose']} (ex {row['ex_date']})"
                    key = _norm_event_text(reason)
                    if key not in seen_reasons:
                        seen_reasons.add(key)
                        reasons.append(reason)
            except:
                continue
        
        # Check results/announcements - SIRF fresh window ke (pehle koi date-check
        # nahi tha -> mahino purani "Board Meeting" bhi Event Risk dikha rahi thi)
        ann_cutoff = now - timedelta(days=7)
        for _, row in ann_df.iterrows():
            dt = row.get("_dt")
            if dt is None:
                dt = parse_nse_dt(row.get("date"))
            if dt is not None and dt < ann_cutoff:
                continue
            desc = str(row.get("desc", ""))
            if any(k in desc.lower() for k in ["result", "dividend", "bonus", "split", "board meeting"]):
                risky = True
                dpart = dt.strftime("%d-%b-%Y") if dt else str(row.get("date", ""))[:11]
                reason = f"{desc.strip()} ({dpart})"
                key = _norm_event_text(desc)
                if key not in seen_reasons:
                    seen_reasons.add(key)
                    reasons.append(reason)
        
        return {"risky": risky, "reasons": reasons[:3], "corp_actions": corp_df, "announcements": ann_df}
    except Exception as e:
        return {"risky": False, "reasons": [str(e)], "corp_actions": pd.DataFrame(), "announcements": pd.DataFrame()}

# ---------- Example for Streamlit ----------
"""
import streamlit as st
from news_corporate_events import get_nse_corporate_actions, is_zone_risky_due_to_event

# Zone table me har symbol ke liye check karo
symbol = "RELIANCE"
zone_date = "2024-10-01"

risk_info = is_zone_risky_due_to_event(symbol, zone_date)
if risk_info["risky"]:
    st.warning(f"⚠️ {symbol} risky hai: {', '.join(risk_info['reasons'])}")
else:
    st.success(f"✅ {symbol} me near term me koi corporate action nahi")

# Full corporate actions table
corp_df = get_nse_corporate_actions(days=30)
st.dataframe(corp_df)

# Results calendar
results_df = get_nse_results_calendar()
st.dataframe(results_df)
"""
