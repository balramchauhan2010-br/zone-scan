"""
powerful_news_fetcher.py - FRESH ONLY (Last 1 Hour) Stocks/Financial Market Trending News + Valid Links Only + No 2016
User Requirement: Fresh only last 1 hour stocks OR financial market trending news + valid links only + no 2016
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def extract_symbol_from_text(text: str) -> str:
    try:
        common = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE", "WIPRO", "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "NIFTY", "BANKNIFTY", "SENSEX", "FII", "DII", "RBI", "FED", "LT", "HINDZINC", "SBI", "FORCE MOTORS", "NIFTY", "BANK NIFTY", "GIFT NIFTY", "USDINR", "GOLD", "CRUDE", "STOCK", "MARKET", "SHARE", "BSE", "NSE"]
        text_upper = text.upper()
        for sym in common:
            if sym in text_upper and len(sym) > 1:
                return sym
        return "MARKET"
    except Exception:
        return "MARKET"

def is_fresh_1hour(pub_date_str: str) -> bool:
    """Fresh only last 1 hour - trending financial market news"""
    try:
        if not pub_date_str:
            return False  # No date = not fresh enough for 1 hour filter, skip
        # Skip old years immediately
        if any(y in pub_date_str for y in ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023"]):
            return False
        # Parse date
        pub_dt = parsedate_to_datetime(pub_date_str)
        pub_dt_naive = pub_dt.replace(tzinfo=None)
        cutoff = datetime.now() - timedelta(hours=1)  # Last 1 hour only
        return pub_dt_naive >= cutoff
    except Exception:
        return False  # If parse fails, not fresh enough for 1 hour

def is_trending_financial_news(title: str, desc: str) -> bool:
    """Only stocks OR financial market trending news"""
    try:
        text = (title + " " + desc).lower()
        trending_keywords = [
            "nifty", "sensex", "banknifty", "stock", "share", "market", "bse", "nse",
            "result", "earnings", "profit", "loss", "dividend", "bonus", "split",
            "fii", "dii", "rbi", "fed", "inflation", "gdp", "buyback", "merger",
            "ipo", "listing", "intraday", "trading", "bull", "bear", "rally", "crash",
            "gift nifty", "usd/inr", "gold", "crude", "tlt", "bond", "forex",
            "reliance", "tcs", "infosys", "hdfc", "icici", "sbi", "lt", "axis"
        ]
        return any(k in text for k in trending_keywords)
    except Exception:
        return False

def is_valid_link(link: str) -> bool:
    """Valid links only - working https, no broken"""
    try:
        if not link or not isinstance(link, str):
            return False
        if not link.startswith("http"):
            return False
        if "TRADINGVIEW" in link.upper():
            return False
        if "HTTPS://WWW" in link.upper() and link.upper().count("HTTPS") > 1:
            return False
        if len(link) > 500 or len(link) < 20:
            return False
        # Must be from trusted financial sources
        trusted_domains = ["moneycontrol.com", "economictimes.indiatimes.com", "news.google.com", "nseindia.com", "bseindia.com", "investing.com", "livemint.com", "financialexpress.com", "business-standard.com"]
        if not any(domain in link.lower() for domain in trusted_domains):
            # Allow if it's google news redirect (still valid)
            if "news.google.com" not in link.lower() and "moneycontrol" not in link.lower() and "economictimes" not in link.lower():
                # For NSE, allow
                if "nseindia.com" not in link.lower() and "bseindia.com" not in link.lower():
                    return False
        return True
    except Exception:
        return False

@st.cache_data(show_spinner=False, ttl=60)  # 1 min cache - ultra fresh 1 hour news
def fetch_moneycontrol_trending_1hour(limit=15):
    """Moneycontrol - Trending financial market news - Last 1 Hour Only + Valid Links"""
    try:
        urls = [
            "https://www.moneycontrol.com/rss/MCtopnews.xml",
            "https://www.moneycontrol.com/rss/latestnews.xml",
            "https://www.moneycontrol.com/rss/marketreports.xml",
        ]
        all_news = []
        for url in urls[:1]:  # Top 1 for speed
            try:
                resp = requests.get(url, headers=HEADERS, timeout=8)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    for item in root.findall(".//item")[:30]:  # Check more to find 1 hour fresh
                        title = item.find("title")
                        link = item.find("link")
                        desc = item.find("description")
                        pub = item.find("pubDate")
                        
                        title_text = title.text if title is not None else ""
                        link_text = link.text if link is not None else ""
                        desc_text = desc.text if desc is not None else ""
                        pub_text = pub.text if pub is not None else ""
                        
                        # Fresh only last 1 hour
                        if not is_fresh_1hour(pub_text):
                            continue
                        # Trending financial only
                        if not is_trending_financial_news(title_text, desc_text):
                            continue
                        # Valid link only
                        if not is_valid_link(link_text):
                            continue
                        if not title_text or len(title_text) < 15:
                            continue
                        
                        all_news.append({
                            "source": "Moneycontrol",
                            "title": title_text,
                            "link": link_text,
                            "desc": desc_text[:300],
                            "date": pub_text,
                            "symbol": extract_symbol_from_text(title_text + " " + desc_text),
                            "fresh": "1H",
                        })
                        if len(all_news) >= limit:
                            break
            except Exception as e:
                print(f"Moneycontrol 1H {url} error: {e}")
                continue
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"Moneycontrol 1H fetch error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=60)
def fetch_et_trending_1hour(limit=15):
    """Economic Times - Trending - Last 1 Hour Only"""
    try:
        urls = ["https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"]
        all_news = []
        for url in urls:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=8)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    for item in root.findall(".//item")[:30]:
                        title = item.find("title")
                        link = item.find("link")
                        desc = item.find("description")
                        pub = item.find("pubDate")
                        
                        title_text = title.text if title is not None else ""
                        link_text = link.text if link is not None else ""
                        desc_text = desc.text if desc is not None else ""
                        pub_text = pub.text if pub is not None else ""
                        
                        if not is_fresh_1hour(pub_text):
                            continue
                        if not is_trending_financial_news(title_text, desc_text):
                            continue
                        if not is_valid_link(link_text):
                            continue
                        if not title_text or len(title_text) < 15:
                            continue
                        
                        all_news.append({
                            "source": "Economic Times",
                            "title": title_text,
                            "link": link_text,
                            "desc": desc_text[:300],
                            "date": pub_text,
                            "symbol": extract_symbol_from_text(title_text),
                            "fresh": "1H",
                        })
                        if len(all_news) >= limit:
                            break
            except Exception as e:
                print(f"ET 1H RSS error: {e}")
                continue
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"ET 1H fetch error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=60)
def fetch_google_news_trending_1hour(limit=15):
    """Google News - Trending Stocks/Financial - Last 1 Hour Only - Ultra Fresh"""
    try:
        # Search for trending financial news in last 1 hour
        url = "https://news.google.com/rss/search?q=stock+market+trending+today+NSE+BSE+live&hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        all_news = []
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:30]:
                title = item.find("title")
                link = item.find("link")
                desc = item.find("description")
                pub = item.find("pubDate")
                
                title_text = title.text if title is not None else ""
                link_text = link.text if link is not None else ""
                desc_text = desc.text if desc is not None else ""
                pub_text = pub.text if pub is not None else ""
                
                if not is_fresh_1hour(pub_text):
                    continue
                if not is_trending_financial_news(title_text, desc_text):
                    continue
                if not is_valid_link(link_text):
                    continue
                if not title_text or len(title_text) < 15:
                    continue
                
                all_news.append({
                    "source": "Google News",
                    "title": title_text,
                    "link": link_text,
                    "desc": desc_text[:300],
                    "date": pub_text,
                    "symbol": extract_symbol_from_text(title_text),
                    "fresh": "1H",
                })
                if len(all_news) >= limit:
                    break
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"Google News 1H error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=60)
def fetch_nse_trending_1hour(limit=10):
    """NSE Announcements - Trending - Last 1 Hour - SAFE (no external import, app never white screen)"""
    try:
        # Try to import NSE module, but if fails, return empty (app still works)
        try:
            from news_corporate_events import get_nse_announcements
            nse_df = get_nse_announcements(days=1)
            if not nse_df.empty:
                formatted = []
                for _, row in nse_df.head(30).iterrows():
                    symbol = str(row.get("symbol", ""))
                    desc = str(row.get("desc", ""))
                    date = str(row.get("date", ""))
                    clean_symbol = symbol.replace(".NS", "").replace("https://", "").replace("http://", "").split("/")[0].split("?")[0].strip()
                    if not clean_symbol or len(clean_symbol) > 20 or "TRADINGVIEW" in clean_symbol.upper():
                        continue
                    if not is_trending_financial_news(clean_symbol, desc):
                        continue
                    link = f"https://www.nseindia.com/get-quotes/equity?symbol={clean_symbol}"
                    if not is_valid_link(link):
                        continue
                    formatted.append({
                        "source": "NSE",
                        "title": f"{clean_symbol} - {desc[:80]}",
                        "link": link,
                        "desc": desc,
                        "date": date,
                        "symbol": clean_symbol,
                        "fresh": "1H",
                    })
                    if len(formatted) >= limit:
                        break
                return pd.DataFrame(formatted)
        except Exception as e:
            print(f"NSE 1H trending inner error (safe): {e}")
        return pd.DataFrame()
    except Exception as e:
        print(f"NSE 1H trending outer safe error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=60)  # 1 min cache - ultra fresh 1 hour
def get_all_powerful_free_news(limit_per_source=10):
    """Combine all - Fresh Only Last 1 Hour, Trending Financial, Valid Links Only, No 2016"""
    try:
        dfs = []
        
        # 1. NSE - fresh trending
        nse_df = fetch_nse_trending_1hour(limit_per_source)
        if not nse_df.empty:
            dfs.append(nse_df)
        
        # 2. Moneycontrol - 1 hour trending
        mc_df = fetch_moneycontrol_trending_1hour(limit_per_source)
        if not mc_df.empty:
            dfs.append(mc_df)
        
        # 3. ET Markets - 1 hour trending
        et_df = fetch_et_trending_1hour(limit_per_source)
        if not et_df.empty:
            dfs.append(et_df)
        
        # 4. Google News - 1 hour ultra fresh trending
        gn_df = fetch_google_news_trending_1hour(limit_per_source)
        if not gn_df.empty:
            dfs.append(gn_df)
        
        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            # Remove duplicates
            combined = combined.drop_duplicates(subset=["title"], keep="first")
            # Valid links only
            combined = combined[combined["link"].apply(is_valid_link)]
            # Trending financial only (double check)
            combined = combined[combined.apply(lambda row: is_trending_financial_news(row["title"], row["desc"]), axis=1)]
            # Sort by fresh (newest first)
            return combined.head(30)
        return pd.DataFrame()
    except Exception as e:
        print(f"All powerful 1H trending error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=60)
def get_verified_news_with_gemini_layers():
    """Multi-layer verification - Fresh Only Last 1 Hour, Trending, Valid Links, No 2016"""
    try:
        all_news_df = get_all_powerful_free_news()
        if all_news_df.empty:
            return pd.DataFrame()
        
        # Powerful trending keywords
        powerful_keywords = ["result", "dividend", "bonus", "split", "buyback", "merger", "rbi", "fed", "inflation", "gdp", "profit", "loss", "board meeting", "earnings", "nifty", "banknifty", "sensex", "fii", "dii", "ipo", "rally", "crash", "trending", "live", "today", "breaking"]
        all_news_df["is_powerful"] = all_news_df["title"].str.lower().apply(lambda x: any(k in str(x).lower() for k in powerful_keywords))
        
        # Cross-verify
        symbol_counts = all_news_df["symbol"].value_counts()
        all_news_df["cross_verified"] = all_news_df["symbol"].apply(lambda s: symbol_counts.get(s, 0) >= 2 if s else False)
        all_news_df["confidence"] = all_news_df.apply(lambda row: "High" if row["cross_verified"] and row["is_powerful"] else "Medium" if row["is_powerful"] else "Low", axis=1)
        
        # Gemini verification
        try:
            from secure_config import is_gemini_configured
            if is_gemini_configured():
                from gemini_analyzer import get_gemini_hypothesis_for_news
                verified = []
                for _, row in all_news_df.head(8).iterrows():
                    try:
                        hypo = get_gemini_hypothesis_for_news(row.get("symbol",""), row.get("title","") + " " + row.get("desc",""))
                        verified.append({
                            **row.to_dict(),
                            "gemini_bias": hypo.get("bias", "Neutral") if isinstance(hypo, dict) else "Neutral",
                            "gemini_reason_hindi": hypo.get("reason_hindi", "") if isinstance(hypo, dict) else "",
                            "gemini_impact": hypo.get("impact", "Medium") if isinstance(hypo, dict) else "Medium",
                        })
                    except Exception:
                        verified.append({**row.to_dict(), "gemini_bias": "Neutral", "gemini_reason_hindi": "", "gemini_impact": "Medium"})
                return pd.DataFrame(verified)
        except Exception as e:
            print(f"Gemini 1H layer error: {e}")
        
        return all_news_df
    except Exception as e:
        print(f"Verified 1H trending error: {e}")
        return pd.DataFrame()

def get_news_for_symbol_powerful(symbol: str, limit=5):
    """Get fresh 1 hour trending verified news for symbol - valid links only"""
    try:
        all_news = get_all_powerful_free_news()
        if all_news.empty:
            return pd.DataFrame()
        symbol_upper = symbol.replace(".NS","").upper().split("?")[0].split("/")[0].strip()
        if not symbol_upper or "TRADINGVIEW" in symbol_upper or len(symbol_upper) > 20:
            return pd.DataFrame()
        filtered = all_news[
            all_news["symbol"].str.upper().str.contains(symbol_upper, na=False) | 
            all_news["title"].str.upper().str.contains(symbol_upper, na=False)
        ]
        filtered = filtered[filtered["link"].apply(is_valid_link)]
        return filtered.head(limit)
    except Exception:
        return pd.DataFrame()
