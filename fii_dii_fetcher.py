"""
fii_dii_fetcher.py
FII/DII Activity - Bina API key ke free, powerful

NSE API: https://www.nseindia.com/api/fiidiiTradeReact
"""

import requests
import pandas as pd
from datetime import datetime
import streamlit as st

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

@st.cache_data(show_spinner=False, ttl=1800)  # 30 min cache - fast
def get_fii_dii_data():
    """
    FII/DII daily activity - NSE se free, fallback StockEdge + Dhan
    Priority: 1. NSE API, 2. StockEdge free website, 3. Dhan (if configured)
    Returns: DataFrame with FII buy/sell/net, DII buy/sell/net, date
    """
    # Try NSE first
    df_nse = _fetch_nse_fii_dii()
    if not df_nse.empty:
        return df_nse
    
    # Try StockEdge free website as fallback (user requested)
    df_stockedge = _fetch_stockedge_fii_dii()
    if not df_stockedge.empty:
        return df_stockedge
    
    # Try Dhan if configured (optional)
    try:
        from secure_config import is_dhan_configured, get_dhan_creds
        if is_dhan_configured():
            # Dhan doesn't have direct FII/DII, but we can return empty and app will show demo
            pass
    except Exception:
        pass
    
    # Final fallback - empty (app won't crash, fast mode)
    return pd.DataFrame()

def _fetch_nse_fii_dii():
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        session.get("https://www.nseindia.com/all-reports", timeout=10)
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        resp = session.get(url, timeout=15)
        data = resp.json()
        rows = []
        if isinstance(data, list):
            for item in data:
                rows.append({
                    "date": item.get("trdDate") or item.get("date"),
                    "category": item.get("category"),
                    "buy_value": item.get("buyValue"),
                    "sell_value": item.get("sellValue"),
                    "net_value": item.get("netValue"),
                })
        elif isinstance(data, dict):
            for key in ["fii", "dii", "fpi", "data"]:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        rows.append(item)
        df = pd.DataFrame(rows)
        if not df.empty:
            for col in ["buy_value", "sell_value", "net_value"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        print(f"NSE FII DII fetch error: {e}")
        return pd.DataFrame()

def _fetch_stockedge_fii_dii():
    """
    StockEdge free website se FII/DII fetch - https://web.stockedge.com/fii-activity
    StockEdge API: https://api.stockedge.com/Api/FIIActivityDashboard/GetFIIActivity?lang=en
    Free, no key, powerful fallback
    """
    try:
        # Try StockEdge API endpoints (these are public, used by web.stockedge.com)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://web.stockedge.com/fii-activity",
            "Origin": "https://web.stockedge.com",
        }
        
        # Endpoint 1: Last 30 days
        urls_to_try = [
            "https://api.stockedge.com/Api/FIIActivityDashboard/GetFIIActivity?lang=en",
            "https://api.stockedge.com/Api/Dashboard/FIIActivity?lang=en",
            "https://api.stockedge.com/Api/FIIActivityDashboard/GetFIIActivityForLast30Days?lang=en",
        ]
        
        for url in urls_to_try:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    # Parse StockEdge format - usually list with Date, FIIBuy, FIISell, FIINet, DIIBuy, DIISell, DIINet
                    rows = []
                    if isinstance(data, list):
                        for item in data[:10]:  # Last 10 days
                            # StockEdge format may have different keys
                            date = item.get("Date") or item.get("TrdDate") or item.get("date")
                            # FII
                            fii_buy = item.get("FIIBuy") or item.get("FIIBuyValue") or item.get("BuyValue")
                            fii_sell = item.get("FIISell") or item.get("FIISellValue") or item.get("SellValue")
                            fii_net = item.get("FIINet") or item.get("FIINetValue") or item.get("NetValue")
                            # DII
                            dii_buy = item.get("DIIBuy") or item.get("DIIBuyValue")
                            dii_sell = item.get("DIISell") or item.get("DIISellValue")
                            dii_net = item.get("DIINet") or item.get("DIINetValue")
                            
                            if fii_net is not None:
                                rows.append({"date": date, "category": "FII", "buy_value": fii_buy, "sell_value": fii_sell, "net_value": fii_net})
                            if dii_net is not None:
                                rows.append({"date": date, "category": "DII", "buy_value": dii_buy, "sell_value": dii_sell, "net_value": dii_net})
                    
                    elif isinstance(data, dict):
                        # Check nested data
                        for key in ["Data", "data", "FIIActivity"]:
                            if key in data and isinstance(data[key], list):
                                for item in data[key][:10]:
                                    date = item.get("Date") or item.get("TrdDate")
                                    fii_net = item.get("FIINet") or item.get("NetValue")
                                    dii_net = item.get("DIINet")
                                    if fii_net is not None:
                                        rows.append({"date": date, "category": "FII", "buy_value": item.get("FIIBuy"), "sell_value": item.get("FIISell"), "net_value": fii_net})
                                    if dii_net is not None:
                                        rows.append({"date": date, "category": "DII", "buy_value": item.get("DIIBuy"), "sell_value": item.get("DIISell"), "net_value": dii_net})
                    
                    df = pd.DataFrame(rows)
                    if not df.empty:
                        for col in ["buy_value", "sell_value", "net_value"]:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col], errors="coerce")
                        print(f"StockEdge FII/DII fetched: {len(df)} rows from {url}")
                        return df
            except Exception as e:
                print(f"StockEdge URL {url} failed: {e}")
                continue
        
        # If APIs fail, try scraping web page (fallback)
        # For now return empty - NSE will be primary
        return pd.DataFrame()
        
    except Exception as e:
        print(f"StockEdge FII DII fetch error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=1800)
def get_fii_dii_summary():
    """Summary for badges: Last day FII net, DII net, trend"""
    df = get_fii_dii_data()
    if df.empty:
        return {"fii_net": 0, "dii_net": 0, "fii_trend": "Neutral", "dii_trend": "Neutral", "last_date": "N/A"}
    
    try:
        # Try to get latest FII and DII
        fii_df = df[df["category"].str.contains("FII|FPI", case=False, na=False)] if "category" in df.columns else df
        dii_df = df[df["category"].str.contains("DII", case=False, na=False)] if "category" in df.columns else pd.DataFrame()
        
        # Last values
        fii_net = 0
        dii_net = 0
        last_date = "N/A"
        
        if not fii_df.empty and "net_value" in fii_df.columns:
            fii_net = float(fii_df["net_value"].iloc[0]) if len(fii_df) > 0 else 0
            last_date = fii_df["date"].iloc[0] if "date" in fii_df.columns and len(fii_df) > 0 else "N/A"
        if not dii_df.empty and "net_value" in dii_df.columns:
            dii_net = float(dii_df["net_value"].iloc[0]) if len(dii_df) > 0 else 0
        
        # Trend: last 3 days; history na hone par net-sign se (NSE API sirf
        # latest day ki rows deta hai -> pehle hamesha "Neutral" dikhta tha,
        # chahe net -3569 Cr ho = galat/stale lagta tha)
        def _trend_from(sub_df, net):
            if sub_df is not None and not sub_df.empty and len(sub_df) >= 3 and "net_value" in sub_df.columns:
                last3 = sub_df["net_value"].head(3).sum()
                return "Buying" if last3 > 0 else "Selling" if last3 < 0 else "Neutral"
            return "Buying" if net > 0 else "Selling" if net < 0 else "Neutral"

        fii_trend = _trend_from(fii_df, fii_net)
        dii_trend = _trend_from(dii_df, dii_net)
        
        return {
            "fii_net": fii_net,
            "dii_net": dii_net,
            "fii_trend": fii_trend,
            "dii_trend": dii_trend,
            "last_date": last_date,
            "full_df": df
        }
    except Exception as e:
        print(f"FII summary error: {e}")
        return {"fii_net": 0, "dii_net": 0, "fii_trend": "Neutral", "dii_trend": "Neutral", "last_date": "N/A", "full_df": df}

def fii_badge_html():
    """Badge HTML for FII/DII - fast, no API key"""
    try:
        summary = get_fii_dii_summary()
        fii_net = summary["fii_net"]
        dii_net = summary["dii_net"]
        
        fii_color = "#16c784" if fii_net >= 0 else "#ea3943"
        dii_color = "#16c784" if dii_net >= 0 else "#ea3943"
        
        fii_arrow = "▲" if fii_net >= 0 else "▼"
        dii_arrow = "▲" if dii_net >= 0 else "▼"
        
        html = (
            f'<span style="background:{fii_color}22;border:1px solid {fii_color};border-radius:6px;'
            f'padding:4px 10px;margin:3px;display:inline-block;font-size:13px;color:#eaeaea;white-space:nowrap;">'
            f'<b>FII Net</b> <span style="color:{fii_color};">{fii_arrow} {fii_net:,.2f} Cr</span> ({summary["fii_trend"]})</span>'
            f'<span style="background:{dii_color}22;border:1px solid {dii_color};border-radius:6px;'
            f'padding:4px 10px;margin:3px;display:inline-block;font-size:13px;color:#eaeaea;white-space:nowrap;">'
            f'<b>DII Net</b> <span style="color:{dii_color};">{dii_arrow} {dii_net:,.2f} Cr</span> ({summary["dii_trend"]})</span>'
            f'<span style="background:#8b8b8b22;border:1px solid #8b8b8b;border-radius:6px;'
            f'padding:4px 10px;margin:3px;display:inline-block;font-size:11px;color:#aaa;white-space:nowrap;">'
            f'{summary["last_date"]}</span>'
        )
        return html
    except Exception:
        return '<span style="color:#888;">FII/DII data unavailable</span>'
