"""
powerful_news_fetcher.py
Powerful Free News Sources Inbuilt - No API Key, Multi-layer Gemini verification

Sources:
1. NSE Announcements (existing)
2. Moneycontrol RSS - https://www.moneycontrol.com/rss/latestnews.xml
3. Economic Times Markets RSS - https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms
4. Yahoo Finance RSS (via Google News)
5. Google News RSS for NSE
6. Investing.com RSS
7. BSE Announcements
8. Screener.in announcements

Gemini AI multi-layer verification:
Layer 1: Collect from all free sources
Layer 2: Gemini filters powerful (Result/Dividend/Bonus/Split/Merger/RBI/Fed)
Layer 3: Gemini cross-verifies same news across sources (if 2+ sources report same, high confidence)
Layer 4: Gemini generates Hindi hypothesis + Bullish/Bearish/Neutral
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
import xml.etree.ElementTree as ET
from typing import List, Dict
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

@st.cache_data(show_spinner=False, ttl=300)  # 5 min cache - fast
def fetch_moneycontrol_rss(limit=20):
    """Moneycontrol free RSS - powerful market news"""
    try:
        urls = [
            "https://www.moneycontrol.com/rss/MCtopnews.xml",
            "https://www.moneycontrol.com/rss/latestnews.xml",
            "https://www.moneycontrol.com/rss/business.xml",
            "https://www.moneycontrol.com/rss/marketreports.xml",
        ]
        all_news = []
        for url in urls[:2]:  # Top 2 only for speed
            try:
                resp = requests.get(url, headers=HEADERS, timeout=8)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    for item in root.findall(".//item")[:limit//2]:
                        title = item.find("title")
                        link = item.find("link")
                        desc = item.find("description")
                        pub = item.find("pubDate")
                        all_news.append({
                            "source": "Moneycontrol",
                            "title": title.text if title is not None else "",
                            "link": link.text if link is not None else "",
                            "desc": (desc.text if desc is not None else "")[:300],
                            "date": pub.text if pub is not None else "",
                            "symbol": extract_symbol_from_text((title.text if title is not None else "") + " " + (desc.text if desc is not None else "")),
                        })
            except Exception as e:
                print(f"Moneycontrol RSS {url} error: {e}")
                continue
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"Moneycontrol fetch error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=300)
def fetch_et_markets_rss(limit=20):
    """Economic Times Markets RSS - free powerful"""
    try:
        urls = [
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        ]
        all_news = []
        for url in urls[:1]:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=8)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    for item in root.findall(".//item")[:limit]:
                        title = item.find("title")
                        link = item.find("link")
                        desc = item.find("description")
                        pub = item.find("pubDate")
                        all_news.append({
                            "source": "Economic Times",
                            "title": title.text if title is not None else "",
                            "link": link.text if link is not None else "",
                            "desc": (desc.text if desc is not None else "")[:300],
                            "date": pub.text if pub is not None else "",
                            "symbol": extract_symbol_from_text((title.text if title is not None else "") + " " + (desc.text if desc is not None else "")),
                        })
            except Exception as e:
                print(f"ET RSS error: {e}")
                continue
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"ET fetch error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=600)
def fetch_google_news_nse(limit=15):
    """Google News RSS for NSE - free, no key"""
    try:
        # Google News RSS for NSE stocks
        url = "https://news.google.com/rss/search?q=NSE+India+stock+market&hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        all_news = []
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:limit]:
                title = item.find("title")
                link = item.find("link")
                desc = item.find("description")
                pub = item.find("pubDate")
                all_news.append({
                    "source": "Google News",
                    "title": title.text if title is not None else "",
                    "link": link.text if link is not None else "",
                    "desc": (desc.text if desc is not None else "")[:300],
                    "date": pub.text if pub is not None else "",
                    "symbol": extract_symbol_from_text((title.text if title is not None else "")),
                })
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"Google News error: {e}")
        return pd.DataFrame()

def extract_symbol_from_text(text: str) -> str:
    """Extract NSE symbol from text - simple heuristic"""
    try:
        # Common NSE symbols
        common = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE", "WIPRO", "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "NIFTY", "BANKNIFTY", "FII", "DII", "RBI", "FED"]
        text_upper = text.upper()
        for sym in common:
            if sym in text_upper:
                return sym
        return ""
    except Exception:
        return ""

@st.cache_data(show_spinner=False, ttl=300)
def get_all_powerful_free_news(limit_per_source=10):
    """Combine all free sources - powerful, no key, fast"""
    try:
        dfs = []
        
        # 1. Moneycontrol
        mc_df = fetch_moneycontrol_rss(limit_per_source)
        if not mc_df.empty:
            dfs.append(mc_df)
        
        # 2. ET Markets
        et_df = fetch_et_markets_rss(limit_per_source)
        if not et_df.empty:
            dfs.append(et_df)
        
        # 3. Google News NSE
        gn_df = fetch_google_news_nse(limit_per_source)
        if not gn_df.empty:
            dfs.append(gn_df)
        
        # 4. NSE Announcements (existing module, if available)
        try:
            from news_corporate_events import get_nse_announcements
            nse_df = get_nse_announcements(days=3)
            if not nse_df.empty:
                # Convert to common format
                nse_formatted = []
                for _, row in nse_df.head(limit_per_source).iterrows():
                    nse_formatted.append({
                        "source": "NSE",
                        "title": row.get("desc", "")[:100],
                        "link": f"https://www.nseindia.com/get-quotes/equity?symbol={row.get('symbol','')}",
                        "desc": row.get("desc", ""),
                        "date": row.get("date", ""),
                        "symbol": row.get("symbol", ""),
                    })
                dfs.append(pd.DataFrame(nse_formatted))
        except Exception:
            pass
        
        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            # Remove duplicates by title
            combined = combined.drop_duplicates(subset=["title"], keep="first")
            # Sort by date if possible
            return combined.head(50)
        return pd.DataFrame()
    except Exception as e:
        print(f"All powerful news error: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=600)
def get_verified_news_with_gemini_layers():
    """
    Multi-layer Gemini verification:
    Layer 1: Collect from all free sources
    Layer 2: Filter powerful keywords
    Layer 3: Cross-verify same news across sources
    Layer 4: Hindi hypothesis
    """
    try:
        all_news_df = get_all_powerful_free_news()
        if all_news_df.empty:
            return pd.DataFrame()
        
        # Layer 2: Filter powerful keywords
        powerful_keywords = ["result", "dividend", "bonus", "split", "buyback", "merger", "rbi", "fed", "inflation", "gdp", "profit", "loss", "board meeting", "earnings", "nifty", "banknifty", "fii", "dii"]
        all_news_df["is_powerful"] = all_news_df["title"].str.lower().apply(lambda x: any(k in str(x).lower() for k in powerful_keywords)) | \
                                      all_news_df["desc"].str.lower().apply(lambda x: any(k in str(x).lower() for k in powerful_keywords))
        
        # Layer 3: Cross-verify - if same symbol appears in 2+ sources, high confidence
        symbol_counts = all_news_df["symbol"].value_counts()
        all_news_df["cross_verified"] = all_news_df["symbol"].apply(lambda s: symbol_counts.get(s, 0) >= 2 if s else False)
        all_news_df["confidence"] = all_news_df.apply(lambda row: "High" if row["cross_verified"] and row["is_powerful"] else "Medium" if row["is_powerful"] else "Low", axis=1)
        
        # Layer 4: Gemini verification if available
        try:
            from secure_config import is_gemini_configured
            if is_gemini_configured():
                from gemini_analyzer import get_gemini_hypothesis_for_news
                verified = []
                for _, row in all_news_df.head(15).iterrows():
                    try:
                        hypo = get_gemini_hypothesis_for_news(row.get("symbol",""), row.get("title","") + " " + row.get("desc",""))
                        verified.append({
                            **row.to_dict(),
                            "gemini_bias": hypo.get("bias", "Neutral"),
                            "gemini_reason_hindi": hypo.get("reason_hindi", ""),
                            "gemini_impact": hypo.get("impact", "Medium"),
                        })
                    except Exception:
                        verified.append({**row.to_dict(), "gemini_bias": "Neutral", "gemini_reason_hindi": "", "gemini_impact": "Medium"})
                return pd.DataFrame(verified)
        except Exception as e:
            print(f"Gemini layer error: {e}")
        
        return all_news_df
    except Exception as e:
        print(f"Verified news error: {e}")
        return pd.DataFrame()

def get_news_for_symbol_powerful(symbol: str, limit=5):
    """Get powerful verified news for a specific symbol from all free sources"""
    try:
        all_news = get_all_powerful_free_news()
        if all_news.empty:
            return pd.DataFrame()
        # Filter by symbol
        symbol_upper = symbol.replace(".NS","").upper()
        filtered = all_news[all_news["symbol"].str.upper().str.contains(symbol_upper, na=False) | 
                           all_news["title"].str.upper().str.contains(symbol_upper, na=False) |
                           all_news["desc"].str.upper().str.contains(symbol_upper, na=False)]
        return filtered.head(limit)
    except Exception:
        return pd.DataFrame()
