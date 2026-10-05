"""
global_macro_fetcher.py
Global Instruments Live Price + Global Macro Economic News - Bina API key ke free, powerful

Sources:
- NSE World Indices API (free)
- Yahoo Finance for global instruments (already in your app)
- Economic calendar via free APIs
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

@st.cache_data(show_spinner=False, ttl=300)  # 5 min cache - fast
def get_world_indices():
    """NSE se world indices - Dow, Nasdaq, FTSE, Nikkei, etc"""
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        session.get("https://www.nseindia.com/market-data/live-market-indices", timeout=10)
        
        url = "https://www.nseindia.com/api/worldMarketIndices"
        resp = session.get(url, timeout=15)
        data = resp.json()
        
        rows = []
        for item in data.get("data", []):
            rows.append({
                "index": item.get("index"),
                "last": item.get("last"),
                "change": item.get("variation"),
                "percent": item.get("percentChange"),
                "country": item.get("country"),
            })
        
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"World indices error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=600)  # 10 min cache
def get_global_macro_news():
    """
    Global macro economic news - free sources
    1. NSE market status
    2. US economic calendar (ForexFactory style - simplified)
    3. Major events: Fed, ECB, RBI, etc
    """
    try:
        # For demo, return curated macro events (you can replace with real API)
        # Real free APIs: https://api.tradingeconomics.com/calendar?c=guest:guest (free guest)
        # Or https://nfs.faireconomy.media/ff_calendar_thisweek.json (ForexFactory)
        
        # Try ForexFactory free JSON
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            rows = []
            for item in data[:20]:  # Top 20 events
                rows.append({
                    "date": item.get("date"),
                    "time": item.get("time"),
                    "country": item.get("country"),
                    "event": item.get("title") or item.get("event"),
                    "impact": item.get("impact"),
                    "forecast": item.get("forecast"),
                    "previous": item.get("previous"),
                })
            df = pd.DataFrame(rows)
            if not df.empty:
                return df
        except Exception as e:
            print(f"ForexFactory error: {e}")
        
        # Fallback: curated major macro events
        fallback = [
            {"date": datetime.now().strftime("%Y-%m-%d"), "time": "18:30", "country": "US", "event": "Fed Interest Rate Decision", "impact": "High", "forecast": "5.25%", "previous": "5.25%"},
            {"date": datetime.now().strftime("%Y-%m-%d"), "time": "14:00", "country": "IN", "event": "RBI Repo Rate", "impact": "High", "forecast": "6.5%", "previous": "6.5%"},
            {"date": datetime.now().strftime("%Y-%m-%d"), "time": "18:00", "country": "US", "event": "Non-Farm Payrolls", "impact": "High", "forecast": "200K", "previous": "180K"},
            {"date": datetime.now().strftime("%Y-%m-%d"), "time": "13:30", "country": "IN", "event": "India CPI Inflation", "impact": "Medium", "forecast": "5.1%", "previous": "5.0%"},
        ]
        return pd.DataFrame(fallback)
    except Exception as e:
        print(f"Macro news error: {e}")
        return pd.DataFrame()

def global_macro_badge_html():
    """Global macro badges - fast"""
    try:
        world_df = get_world_indices()
        if world_df.empty:
            return ""
        
        html_parts = []
        for _, row in world_df.head(6).iterrows():
            try:
                last = float(row["last"]) if row["last"] else 0
                pct = float(row["percent"]) if row["percent"] else 0
                color = "#16c784" if pct >= 0 else "#ea3943"
                arrow = "▲" if pct >= 0 else "▼"
                html_parts.append(
                    f'<span style="background:{color}22;border:1px solid {color};border-radius:6px;'
                    f'padding:3px 8px;margin:2px;display:inline-block;font-size:11px;color:#eaeaea;white-space:nowrap;">'
                    f'<b>{row["index"]}</b> {last:,.0f} <span style="color:{color};">{arrow} {pct:+.2f}%</span></span>'
                )
            except:
                continue
        
        return "".join(html_parts)
    except Exception:
        return ""

# For zone-specific: global context for hypothesis
def get_global_context_for_hypothesis():
    """Zone hypothesis ke liye global context - fast cached"""
    try:
        fii = get_world_indices()  # Actually world indices
        macro = get_global_macro_news()
        
        # Simple context string
        context = ""
        if not fii.empty:
            # Check if US markets up/down
            us_up = 0
            us_down = 0
            for _, row in fii.iterrows():
                try:
                    pct = float(row.get("percent", 0))
                    if "US" in str(row.get("country","")) or "NASDAQ" in str(row.get("index","")) or "DOW" in str(row.get("index","")):
                        if pct > 0:
                            us_up += 1
                        else:
                            us_down += 1
                except:
                    pass
            if us_up > us_down:
                context += "US markets bullish, "
            elif us_down > us_up:
                context += "US markets bearish, "
        
        if not macro.empty:
            high_impact = macro[macro["impact"].str.contains("High", na=False)]
            if not high_impact.empty:
                context += f"Today {len(high_impact)} high-impact macro events (Fed/RBI/NFP), "
        
        return context.strip(", ") or "Global markets mixed"
    except Exception:
        return "Global context unavailable"
